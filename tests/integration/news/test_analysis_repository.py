from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text

from anxious_news_bot.news.domain import (
    AnalysisStatus,
    ArticleAnalysis,
    NormalizedArticleCandidate,
    SourceType,
)
from anxious_news_bot.news.infrastructure import models
from anxious_news_bot.news.infrastructure.database import Database
from anxious_news_bot.news.infrastructure.persistence import SQLAlchemyNewsRepository

NOW = datetime(2026, 8, 12, 12, tzinfo=UTC)


async def reset_news_tables(database: Database) -> None:
    async with database.session() as session:
        await session.execute(
            text(
                "TRUNCATE article_analyses, deduplication_decisions, "
                "source_article_records, normalized_articles, event_groups, "
                "source_runs, collection_cycles, news_sources CASCADE"
            )
        )


async def seed_article(repository: SQLAlchemyNewsRepository):
    async with repository.unit_of_work() as work:
        session = work._require_session()
        source = models.NewsSource(
            id=uuid4(),
            name="analysis-source",
            source_type=SourceType.RSS,
            endpoint_url=f"https://{uuid4().hex}.example/feed",
            region="World",
            language_code="en",
            enabled=True,
            polling_interval_seconds=300,
        )
        session.add(source)
        cycle = await work.create_cycle(NOW, "test")
        await session.flush()
        article, _ = await work.insert_or_resolve_article(
            NormalizedArticleCandidate(
                source.id,
                "Analysis article",
                None,
                f"https://example.com/{uuid4().hex}",
                "https://example.com/original",
                NOW,
                NOW,
                "en",
                "analysis article",
            ),
            cycle.id,
        )
        return article


def analysis(article_id, *, analyzer_version: str = "v1") -> ArticleAnalysis:
    return ArticleAnalysis(
        id=uuid4(),
        article_id=article_id,
        status=AnalysisStatus.PARTIAL,
        schema_version="1.0",
        analyzer_name="fake",
        analyzer_version=analyzer_version,
        created_at=NOW,
        topics=("economy",),
        locations=("Community of Madrid",),
        importance_score=Decimal("0.75"),
        error_code="invalid_sections:countries",
    )


async def test_analysis_versions_are_idempotent_and_validated_sections_persist(
    postgres_database_url: str,
) -> None:
    database = Database(postgres_database_url)
    repository = SQLAlchemyNewsRepository(database)
    try:
        await reset_news_tables(database)
        article = await seed_article(repository)
        first_value = analysis(article.id)
        async with repository.unit_of_work() as work:
            first = await work.store_analysis(first_value)
            repeated = await work.store_analysis(analysis(article.id))
            second_version = await work.store_analysis(
                analysis(article.id, analyzer_version="v2")
            )

        assert repeated.id == first.id
        assert second_version.id != first.id
        async with database.session() as session:
            rows = (
                await session.scalars(
                    select(models.ArticleAnalysis).order_by(
                        models.ArticleAnalysis.analyzer_version
                    )
                )
            ).all()
            count = await session.scalar(
                select(func.count()).select_from(models.ArticleAnalysis)
            )
        assert count == 2
        assert rows[0].topics == ["economy"]
        assert rows[0].countries == []
        assert rows[0].locations == ["Community of Madrid"]
        assert rows[0].importance_score == Decimal("0.7500")
    finally:
        await reset_news_tables(database)
        await database.close()


async def test_repository_rejects_unvalidated_values(
    postgres_database_url: str,
) -> None:
    database = Database(postgres_database_url)
    repository = SQLAlchemyNewsRepository(database)
    try:
        await reset_news_tables(database)
        article = await seed_article(repository)
        async with repository.unit_of_work() as work:
            with pytest.raises(TypeError):
                await work.store_analysis(
                    {
                        "article_id": article.id,
                        "importance_score": 2,
                        "user_id": uuid4(),
                    }
                )
    finally:
        await reset_news_tables(database)
        await database.close()
