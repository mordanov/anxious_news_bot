from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select

from anxious_news_bot.news.domain import AnalysisStatus, CycleStatus, SourceType
from anxious_news_bot.news.infrastructure.models import (
    ArticleAnalysis,
    CollectionCycle,
    NewsSource,
    NormalizedArticle,
)
from anxious_news_bot.preferences.infrastructure.models import (
    ApplicationUser,
    PreferenceProfile,
)
from anxious_news_bot.ranking.infrastructure.persistence import (
    SQLAlchemyRankingRepository,
)


async def test_prepares_baseline_analysis_and_delivery_metadata(
    ranking_database,
) -> None:
    now = datetime.now(UTC)
    async with ranking_database.session() as session:
        user = ApplicationUser(telegram_user_id=777, language_code="en")
        source = NewsSource(
            name="Example News",
            source_type=SourceType.RSS,
            endpoint_url="https://example.com/feed.xml",
            region="World",
            language_code="en",
            enabled=True,
            quality_score="0.80",
            polling_interval_seconds=300,
        )
        cycle = CollectionCycle(
            status=CycleStatus.RUNNING,
            started_at=now,
            configuration_version="test",
        )
        session.add_all((user, source, cycle))
        await session.flush()
        session.add(PreferenceProfile(user_id=user.id, revision=0))
        article = NormalizedArticle(
            id=uuid4(),
            title="A recent article",
            summary="Summary",
            canonical_url="https://example.com/article",
            canonicalization_version="1.0",
            primary_source_id=source.id,
            published_at=now,
            ingested_at=now,
            language_code="en",
            normalized_text="A recent article summary.",
            topic_metadata=["technology"],
            created_in_cycle_id=cycle.id,
        )
        session.add(article)
        await session.flush()
        article_id = article.id

    repository = SQLAlchemyRankingRepository(ranking_database)
    candidates = await repository.prepare_delivery_candidates(
        limit=10,
        ranking_at=now,
        freshness_horizon_seconds=259_200,
    )
    items = await repository.load_delivery_articles(candidates)

    assert candidates == (article_id,)
    assert items[0].source_name == "Example News"
    async with ranking_database.session() as session:
        analysis = await session.scalar(
            select(ArticleAnalysis).where(ArticleAnalysis.article_id == article_id)
        )
        assert analysis is not None
        assert analysis.status is AnalysisStatus.COMPLETE
        assert analysis.topics == ["technology"]
