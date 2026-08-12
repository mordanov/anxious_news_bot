from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func, select, text

from anxious_news_bot.news.domain import (
    DecisionOutcome,
    DecisionType,
    DeduplicationDecision,
    EventGroupStatus,
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


async def seed(repository: SQLAlchemyNewsRepository):
    async with repository.unit_of_work() as work:
        session = work._require_session()
        source = models.NewsSource(
            id=uuid4(),
            name="source",
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
        return source.id, cycle.id


async def insert_article(repository, source_id, cycle_id, title, text_value, offset=0):
    async with repository.unit_of_work() as work:
        article, _ = await work.insert_or_resolve_article(
            NormalizedArticleCandidate(
                source_id,
                title,
                None,
                f"https://example.com/{uuid4().hex}",
                "https://example.com/original",
                NOW + timedelta(hours=offset),
                NOW + timedelta(hours=offset),
                "en",
                text_value,
            ),
            cycle_id,
        )
        return article


async def test_pg_trgm_candidate_search_is_bounded_ranked_and_indexable(
    postgres_database_url: str,
) -> None:
    database = Database(postgres_database_url)
    repository = SQLAlchemyNewsRepository(database)
    try:
        await reset_news_tables(database)
        source_id, cycle_id = await seed(repository)
        closest = await insert_article(
            repository,
            source_id,
            cycle_id,
            "Central bank cuts interest rates",
            "policy",
        )
        await insert_article(
            repository, source_id, cycle_id, "Volcano closes island airport", "eruption"
        )
        candidate = NormalizedArticleCandidate(
            source_id,
            "Central bank cuts rates",
            None,
            "https://new.example/story",
            "https://new.example/story",
            NOW,
            NOW,
            "en",
            "policy",
        )
        async with repository.unit_of_work() as work:
            found = await work.find_duplicate_candidates(candidate, 1, 0.3)
        assert [item.id for item in found] == [closest.id]

        async with database.session() as session:
            await session.execute(text("SET LOCAL enable_seqscan = off"))
            plan = "\n".join(
                (
                    await session.execute(
                        text(
                            "EXPLAIN SELECT id FROM normalized_articles "
                            "WHERE title % :title ORDER BY similarity(title, :title) DESC LIMIT 10"
                        ),
                        {"title": candidate.title},
                    )
                ).scalars()
            )
        assert "ix_articles_title_trgm" in plan
    finally:
        await reset_news_tables(database)
        await database.close()


async def test_pg_trgm_candidate_search_honors_threshold_below_database_default(
    postgres_database_url: str,
) -> None:
    database = Database(postgres_database_url)
    repository = SQLAlchemyNewsRepository(database)
    try:
        await reset_news_tables(database)
        source_id, cycle_id = await seed(repository)
        low_similarity = await insert_article(
            repository, source_id, cycle_id, "abcdefghij", "unrelated stored text"
        )
        candidate = NormalizedArticleCandidate(
            source_id,
            "abczzzzzzz",
            None,
            "https://new.example/low-threshold",
            "https://new.example/low-threshold",
            NOW,
            NOW,
            "en",
            "different candidate text",
        )
        async with repository.unit_of_work() as work:
            found = await work.find_duplicate_candidates(candidate, 10, 0.1)

        assert low_similarity.id in {item.id for item in found}
    finally:
        await reset_news_tables(database)
        await database.close()


async def test_decision_pair_order_and_uniqueness_are_idempotent(
    postgres_database_url: str,
) -> None:
    database = Database(postgres_database_url)
    repository = SQLAlchemyNewsRepository(database)
    try:
        await reset_news_tables(database)
        source_id, cycle_id = await seed(repository)
        left = await insert_article(repository, source_id, cycle_id, "left", "left")
        right = await insert_article(repository, source_id, cycle_id, "right", "right")
        decision = DeduplicationDecision(
            uuid4(),
            right.id,
            left.id,
            DecisionType.NEAR_DUPLICATE,
            DecisionOutcome.REVIEW,
            {"review": "0.72000"},
            "duplicate-v1",
            {"reason": "boundary"},
            NOW,
            Decimal("0.75"),
            Decimal("0.70"),
        )
        async with repository.unit_of_work() as work:
            first = await work.record_decision(decision)
            second = await work.record_decision(decision)

        assert first.id == second.id
        assert first.left_article_id.int < first.right_article_id.int
        async with database.session() as session:
            count = await session.scalar(
                select(func.count()).select_from(models.DeduplicationDecision)
            )
        assert count == 1
    finally:
        await reset_news_tables(database)
        await database.close()


async def test_event_assignment_reassignment_and_provenance_urls_are_retained(
    postgres_database_url: str,
) -> None:
    database = Database(postgres_database_url)
    repository = SQLAlchemyNewsRepository(database)
    try:
        await reset_news_tables(database)
        source_id, cycle_id = await seed(repository)
        first = await insert_article(repository, source_id, cycle_id, "one", "one")
        second = await insert_article(repository, source_id, cycle_id, "two", "two")
        async with repository.unit_of_work() as work:
            group = await work.create_event_group(
                representative_article_id=first.id,
                created_at=NOW,
                status=EventGroupStatus.PROPOSED,
            )
            await work.assign_article_to_event(first.id, group.id)
            await work.assign_article_to_event(second.id, group.id)
            await work.assign_article_to_event(second.id, group.id)

        async with database.session() as session:
            rows = (
                await session.scalars(
                    select(models.NormalizedArticle)
                    .where(models.NormalizedArticle.id.in_([first.id, second.id]))
                    .order_by(models.NormalizedArticle.id)
                )
            ).all()
        assert {row.event_group_id for row in rows} == {group.id}
        assert {row.canonical_url for row in rows} == {
            first.canonical_url,
            second.canonical_url,
        }
    finally:
        await reset_news_tables(database)
        await database.close()
