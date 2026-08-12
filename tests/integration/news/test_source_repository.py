from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from anxious_news_bot.news.domain import SourceType
from anxious_news_bot.news.infrastructure import models
from anxious_news_bot.news.infrastructure.database import Database
from anxious_news_bot.news.infrastructure.persistence import SQLAlchemyNewsRepository
from anxious_news_bot.news.services.source_catalog import CatalogSource


NOW = datetime(2026, 8, 12, 12, tzinfo=UTC)


def entry(
    source_id,
    endpoint,
    *,
    name="Source",
    enabled=True,
    region="World",
    interval=300,
    source_type=SourceType.RSS,
):
    return CatalogSource(
        id=source_id,
        name=name,
        source_type=source_type,
        endpoint_url=endpoint,
        region=region,
        country_code=None,
        language_code="en",
        enabled=enabled,
        quality_score=Decimal("0.8"),
        polling_interval_seconds=interval,
        credential_ref=None,
    )


async def test_catalog_upsert_preserves_omitted_sources_and_polling_metadata(
    postgres_database_url: str,
) -> None:
    database = Database(postgres_database_url)
    repository = SQLAlchemyNewsRepository(database)
    updated_id, type_changed_id, disabled_id, omitted_id, unchanged_id, added_id = (
        uuid4() for _ in range(6)
    )
    try:
        async with database.session() as session:
            session.add_all(
                [
                    models.NewsSource(
                        id=updated_id,
                        name="Old",
                        source_type=SourceType.RSS,
                        endpoint_url="https://old.example/feed",
                        region="World",
                        language_code="en",
                        enabled=True,
                        polling_interval_seconds=300,
                        last_polled_at=NOW,
                        next_poll_at=NOW + timedelta(hours=1),
                        etag='"old"',
                        last_modified="old-date",
                    ),
                    models.NewsSource(
                        id=type_changed_id,
                        name="Source",
                        source_type=SourceType.RSS,
                        endpoint_url="https://type-change.example/feed",
                        region="World",
                        country_code=None,
                        language_code="en",
                        enabled=True,
                        quality_score=Decimal("0.8"),
                        polling_interval_seconds=300,
                        etag='"rss"',
                        last_modified="rss-date",
                    ),
                    models.NewsSource(
                        id=disabled_id,
                        name="Disable me",
                        source_type=SourceType.RSS,
                        endpoint_url="https://disable.example/feed",
                        region="World",
                        language_code="en",
                        enabled=True,
                        polling_interval_seconds=300,
                    ),
                    models.NewsSource(
                        id=omitted_id,
                        name="Omitted",
                        source_type=SourceType.RSS,
                        endpoint_url="https://omitted.example/feed",
                        region="World",
                        language_code="en",
                        enabled=True,
                        polling_interval_seconds=300,
                    ),
                    models.NewsSource(
                        id=unchanged_id,
                        name="Source",
                        source_type=SourceType.RSS,
                        endpoint_url="https://unchanged.example/feed",
                        region="World",
                        country_code=None,
                        language_code="en",
                        enabled=True,
                        quality_score=Decimal("0.8"),
                        polling_interval_seconds=300,
                        etag='"unchanged"',
                        last_modified="unchanged-date",
                    ),
                ]
            )

        entries = (
            entry(
                updated_id,
                "https://updated.example/feed",
                name="Updated",
                interval=600,
                region="Antarctica",
            ),
            entry(
                type_changed_id,
                "https://type-change.example/feed",
                source_type=SourceType.ATOM,
            ),
            entry(
                disabled_id,
                "https://disable.example/feed",
                enabled=False,
            ),
            entry(
                added_id,
                "https://added.example/feed",
                name="Added",
            ),
            entry(unchanged_id, "https://unchanged.example/feed"),
        )
        async with repository.unit_of_work() as work:
            plan = await work.upsert_source_catalog(entries)

        assert plan.added == (added_id,)
        assert plan.updated == tuple(
            sorted((updated_id, type_changed_id, disabled_id), key=lambda x: x.int)
        )
        assert plan.unchanged == (unchanged_id,)
        async with database.session() as session:
            rows = {
                row.id: row
                for row in (
                    await session.scalars(
                        select(models.NewsSource).where(
                            models.NewsSource.id.in_(
                                [
                                    updated_id,
                                    type_changed_id,
                                    disabled_id,
                                    omitted_id,
                                    unchanged_id,
                                    added_id,
                                ]
                            )
                        )
                    )
                ).all()
            }
        assert rows[updated_id].name == "Updated"
        assert rows[updated_id].region == "Antarctica"
        assert rows[updated_id].last_polled_at == NOW
        assert rows[updated_id].next_poll_at == NOW + timedelta(hours=1)
        assert rows[updated_id].etag is None
        assert rows[updated_id].last_modified is None
        assert rows[type_changed_id].source_type is SourceType.ATOM
        assert rows[type_changed_id].etag is None
        assert rows[type_changed_id].last_modified is None
        assert not rows[disabled_id].enabled
        assert rows[omitted_id].enabled
        assert rows[omitted_id].name == "Omitted"
        assert rows[unchanged_id].etag == '"unchanged"'
        assert rows[unchanged_id].last_modified == "unchanged-date"
        assert rows[added_id].next_poll_at is None

        async with repository.unit_of_work() as work:
            due = await work.list_due_sources(NOW)
        assert {source.id for source in due} == {
            added_id,
            omitted_id,
            type_changed_id,
            unchanged_id,
        }
    finally:
        await database.close()


async def test_catalog_conflict_rolls_back_every_upsert(
    postgres_database_url: str,
) -> None:
    database = Database(postgres_database_url)
    repository = SQLAlchemyNewsRepository(database)
    first_id, second_id = uuid4(), uuid4()
    try:
        async with database.session() as session:
            session.add(
                models.NewsSource(
                    id=second_id,
                    name="Existing",
                    source_type=SourceType.RSS,
                    endpoint_url="https://existing.example/feed",
                    region="World",
                    language_code="en",
                    enabled=True,
                    polling_interval_seconds=300,
                )
            )

        with pytest.raises(IntegrityError):
            async with repository.unit_of_work() as work:
                await work.upsert_source_catalog(
                    (
                        entry(first_id, "https://new.example/feed", name="New"),
                        entry(
                            second_id,
                            "https://new.example/feed",
                            name="Conflicting",
                        ),
                    )
                )

        async with database.session() as session:
            assert await session.get(models.NewsSource, first_id) is None
            existing = await session.get(models.NewsSource, second_id)
        assert existing is not None
        assert existing.name == "Existing"
        assert existing.endpoint_url == "https://existing.example/feed"
    finally:
        await database.close()
