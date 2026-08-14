"""PostgreSQL fixtures and migration lifecycle helpers for digest tests."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import psycopg
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url

from anxious_news_bot.digest.infrastructure.persistence import (
    SQLAlchemyDigestRepository,
)
from anxious_news_bot.infrastructure.database import Database
from anxious_news_bot.infrastructure.users import (
    ApplicationUserProvisioner,
    DigestDefaults,
    ProvisionedUser,
)


@dataclass(frozen=True)
class SeededDigestArticle:
    article_id: UUID
    analysis_id: UUID
    event_group_id: UUID | None
    title: str
    summary: str
    normalized_text: str
    published_at: datetime
    canonical_url: str
    source_name: str


@dataclass(frozen=True)
class SeededDigestGraph:
    ranking_run_id: UUID
    articles: tuple[SeededDigestArticle, ...]


TRUNCATE_DIGEST_GRAPH = text(
    "TRUNCATE application_users, news_sources, collection_cycles, event_groups, "
    "ranking_configuration_snapshots CASCADE"
)


@pytest_asyncio.fixture
async def digest_database(
    postgres_database_url: str,
) -> AsyncIterator[Database]:
    database = Database(postgres_database_url)
    try:
        yield database
    finally:
        async with database.session() as session:
            await session.execute(TRUNCATE_DIGEST_GRAPH)
        await database.close()


@pytest_asyncio.fixture
async def digest_repository(
    digest_database: Database,
) -> SQLAlchemyDigestRepository:
    return SQLAlchemyDigestRepository(digest_database)


@pytest.fixture
def provision_digest_user(
    digest_database: Database,
) -> Callable[..., object]:
    async def provision(
        telegram_user_id: int = 123_456,
        language_hint: str | None = "en",
        defaults: DigestDefaults | None = None,
    ) -> ProvisionedUser:
        async with digest_database.session() as session:
            return await ApplicationUserProvisioner(defaults).ensure(
                session,
                telegram_user_id=telegram_user_id,
                language_hint=language_hint,
            )

    return provision


@pytest.fixture
def enable_digest_user(digest_database: Database):
    async def enable(
        user_id,
        *,
        due_at: datetime | None = None,
        digest_count: int = 10,
        timezone_name: str = "UTC",
        local_time: str = "09:00",
    ) -> datetime:
        scheduled_at = due_at or datetime(2026, 1, 15, 9, 0, tzinfo=UTC)
        async with digest_database.session() as session:
            await session.execute(
                text(
                    "UPDATE digest_configurations "
                    "SET enabled = true, digest_count = :count, "
                    "schedule_local_time = CAST(:local_time AS time), "
                    "timezone_name = :timezone_name, next_due_at = :due_at, "
                    "schedule_revision = schedule_revision + 1 "
                    "WHERE user_id = :user_id"
                ),
                {
                    "count": digest_count,
                    "local_time": local_time,
                    "timezone_name": timezone_name,
                    "due_at": scheduled_at,
                    "user_id": user_id,
                },
            )
        return scheduled_at

    return enable


@pytest.fixture
def seed_digest_graph(digest_database: Database):
    async def seed(
        user_id: UUID,
        *,
        count: int = 1,
        event_group_id: UUID | None = None,
        novelty_scores: tuple[Decimal, ...] | None = None,
        normalized_texts: tuple[str, ...] | None = None,
        published_at: datetime | None = None,
    ) -> SeededDigestGraph:
        now = published_at or datetime(2026, 1, 14, 12, tzinfo=UTC)
        source_id = uuid4()
        cycle_id = uuid4()
        ranking_run_id = uuid4()
        configuration_version = f"digest-test-{uuid4()}"
        articles: list[SeededDigestArticle] = []
        async with digest_database.session() as session:
            await session.execute(
                text(
                    "INSERT INTO news_sources "
                    "(id, name, source_type, endpoint_url, region, language_code, "
                    "quality_score, polling_interval_seconds) VALUES "
                    "(:id, :name, 'rss', :url, 'global', 'en', 0.80, 60)"
                ),
                {
                    "id": source_id,
                    "name": f"Digest Source {source_id}",
                    "url": f"https://feeds.example/{source_id}",
                },
            )
            await session.execute(
                text(
                    "INSERT INTO collection_cycles "
                    "(id, status, started_at, completed_at, new_article_count, "
                    "source_success_count, source_failure_count, configuration_version) "
                    "VALUES (:id, 'completed', :now, :now, :count, 1, 0, 'test')"
                ),
                {"id": cycle_id, "now": now, "count": count},
            )
            if event_group_id is not None:
                await session.execute(
                    text(
                        "INSERT INTO event_groups (id, status) "
                        "VALUES (:id, 'confirmed') ON CONFLICT (id) DO NOTHING"
                    ),
                    {"id": event_group_id},
                )
            for index in range(count):
                article_id = uuid4()
                analysis_id = uuid4()
                article_time = now + timedelta(minutes=index)
                normalized_text = (
                    normalized_texts[index]
                    if normalized_texts is not None
                    else f"normalized article {index} " * 30
                )
                novelty = (
                    novelty_scores[index]
                    if novelty_scores is not None
                    else Decimal("0.5000")
                )
                canonical_url = f"https://example.com/digest/{article_id}"
                await session.execute(
                    text(
                        "INSERT INTO normalized_articles "
                        "(id, title, summary, canonical_url, canonicalization_version, "
                        "primary_source_id, published_at, ingested_at, language_code, "
                        "normalized_text, event_group_id, created_in_cycle_id) VALUES "
                        "(:id, :title, :summary, :url, '1.0', :source_id, "
                        ":published_at, :published_at, 'en', :normalized_text, "
                        ":event_group_id, :cycle_id)"
                    ),
                    {
                        "id": article_id,
                        "title": f"Article {index + 1}",
                        "summary": f"Summary {index + 1}",
                        "url": canonical_url,
                        "source_id": source_id,
                        "published_at": article_time,
                        "normalized_text": normalized_text,
                        "event_group_id": event_group_id,
                        "cycle_id": cycle_id,
                    },
                )
                await session.execute(
                    text(
                        "INSERT INTO article_analyses "
                        "(id, article_id, status, schema_version, analyzer_name, "
                        "analyzer_version, importance_score, novelty_score, "
                        "source_quality_score) VALUES "
                        "(:id, :article_id, 'complete', '1.0', 'test', '1.0', "
                        "0.7000, :novelty, 0.8000)"
                    ),
                    {
                        "id": analysis_id,
                        "article_id": article_id,
                        "novelty": novelty,
                    },
                )
                articles.append(
                    SeededDigestArticle(
                        article_id=article_id,
                        analysis_id=analysis_id,
                        event_group_id=event_group_id,
                        title=f"Article {index + 1}",
                        summary=f"Summary {index + 1}",
                        normalized_text=normalized_text,
                        published_at=article_time,
                        canonical_url=canonical_url,
                        source_name=f"Digest Source {source_id}",
                    )
                )
            await session.execute(
                text(
                    "INSERT INTO ranking_configuration_snapshots "
                    "(version, configuration_hash, personal_coefficient, "
                    "importance_coefficient, freshness_coefficient, "
                    "quality_coefficient, novelty_coefficient, "
                    "freshness_horizon_seconds, future_tolerance_seconds, "
                    "minimum_source_quality, maximum_candidate_count, event_cap, "
                    "topic_cap, source_cap, explicit_weight_threshold, "
                    "explicit_relevance_threshold, explanation_contribution_limit, "
                    "tie_policy_version, retention_policy_version) VALUES "
                    "(:version, :hash, 0.45000, 0.20000, 0.15000, 0.10000, "
                    "0.10000, 259200, 300, 0.35000, 500, 20, 20, 20, "
                    "0.75, 0.6000, 3, '1.0', '1.0')"
                ),
                {
                    "version": configuration_version,
                    "hash": uuid4().hex + uuid4().hex,
                },
            )
            await session.execute(
                text(
                    "INSERT INTO ranking_runs "
                    "(id, request_id, user_id, profile_revision, candidate_set_hash, "
                    "configuration_version, ranking_at, requested_count, status, "
                    "selected_count, excluded_count, completed_at) VALUES "
                    "(:id, :request_id, :user_id, 0, :hash, :version, :now, "
                    ":count, 'complete', :count, 0, :now)"
                ),
                {
                    "id": ranking_run_id,
                    "request_id": f"digest-test:{ranking_run_id}",
                    "user_id": user_id,
                    "hash": uuid4().hex + uuid4().hex,
                    "version": configuration_version,
                    "now": now,
                    "count": count,
                },
            )
        return SeededDigestGraph(ranking_run_id, tuple(articles))

    return seed


def _admin_url() -> str:
    return os.getenv(
        "TEST_POSTGRES_ADMIN_URL",
        "postgresql+psycopg://postgres:postgres@localhost:5432/postgres",
    )


def _sync_url(value: str) -> str:
    return (
        make_url(value)
        .set(drivername="postgresql")
        .render_as_string(hide_password=False)
    )


@pytest.fixture
def digest_pre_migration_database_url() -> str:
    """Create an isolated database migrated only through revision 004."""
    database_name = f"anxious_digest_migration_{uuid4().hex}"
    try:
        with psycopg.connect(_sync_url(_admin_url()), autocommit=True) as connection:
            connection.execute(f'CREATE DATABASE "{database_name}"')
    except psycopg.Error as exc:
        pytest.skip(f"ephemeral PostgreSQL is unavailable: {exc}")

    database_url = (
        make_url(_admin_url())
        .set(drivername="postgresql+psycopg", database=database_name)
        .render_as_string(hide_password=False)
    )
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    previous_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    try:
        command.upgrade(config, "004_question_dimension_context")
        yield database_url
    finally:
        if previous_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_url
        with psycopg.connect(_sync_url(_admin_url()), autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (database_name,),
            )
            connection.execute(f'DROP DATABASE IF EXISTS "{database_name}"')
