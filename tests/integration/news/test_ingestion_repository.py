import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, select, text

from anxious_news_bot.news.domain import (
    NormalizedArticleCandidate,
    ProvenanceStatus,
    SourceArticleRecord,
    SourceType,
)
from anxious_news_bot.news.infrastructure import models
from anxious_news_bot.news.infrastructure.database import Database
from anxious_news_bot.news.infrastructure.persistence import SQLAlchemyNewsRepository

NOW = datetime(2026, 8, 12, 12, tzinfo=UTC)


async def seed_source(session, *, endpoint: str, due: datetime | None = None):
    source = models.NewsSource(
        id=uuid4(),
        name=endpoint,
        source_type=SourceType.RSS,
        endpoint_url=f"https://{endpoint}.example/feed",
        region="World",
        language_code="en",
        enabled=True,
        polling_interval_seconds=300,
        next_poll_at=due,
    )
    session.add(source)
    await session.flush()
    return source


async def test_migration_installs_extension_and_all_ingestion_tables(
    postgres_engine,
) -> None:
    async with postgres_engine.connect() as connection:
        extension = await connection.scalar(
            text("SELECT extname FROM pg_extension WHERE extname = 'pg_trgm'")
        )
        tables = set(
            (
                await connection.execute(
                    text(
                        "SELECT tablename FROM pg_tables "
                        "WHERE schemaname = 'public' AND tablename LIKE '%news%' "
                        "OR schemaname = 'public' AND tablename IN "
                        "('collection_cycles', 'source_runs', "
                        "'source_article_records', 'normalized_articles')"
                    )
                )
            ).scalars()
        )

    assert extension == "pg_trgm"
    assert {
        "news_sources",
        "collection_cycles",
        "source_runs",
        "source_article_records",
        "normalized_articles",
    } <= tables


async def test_advisory_lock_prevents_overlap(postgres_database_url: str) -> None:
    first_db = Database(postgres_database_url)
    second_db = Database(postgres_database_url)
    first = SQLAlchemyNewsRepository(first_db)
    second = SQLAlchemyNewsRepository(second_db)
    try:
        assert await first.try_acquire_cycle_lock(123456)
        assert not await first.try_acquire_cycle_lock(123456)
        assert not await second.try_acquire_cycle_lock(123456)
        await first.release_cycle_lock(123456)
        assert await second.try_acquire_cycle_lock(123456)
    finally:
        await first.release_cycle_lock(123456)
        await second.release_cycle_lock(123456)
        await first_db.close()
        await second_db.close()


async def test_same_repository_concurrent_lock_attempt_has_single_owner(
    postgres_database_url: str,
) -> None:
    database = Database(postgres_database_url)
    repository = SQLAlchemyNewsRepository(database)
    acquired = asyncio.Event()
    release = asyncio.Event()

    async def attempt() -> bool:
        owns_lock = await repository.try_acquire_cycle_lock(654321)
        if owns_lock:
            acquired.set()
            await release.wait()
            await repository.release_cycle_lock(654321)
        return owns_lock

    first = asyncio.create_task(attempt())
    await acquired.wait()
    second = asyncio.create_task(attempt())
    try:
        assert await second is False
        release.set()
        assert await first is True
        assert await repository.try_acquire_cycle_lock(654321)
        await repository.release_cycle_lock(654321)
    finally:
        release.set()
        await asyncio.gather(first, second, return_exceptions=True)
        await database.close()


async def test_reused_external_id_resolves_original_article_without_orphan(
    postgres_database_url: str,
) -> None:
    database = Database(postgres_database_url)
    repository = SQLAlchemyNewsRepository(database)
    try:
        async with database.session() as session:
            source = await seed_source(session, endpoint=f"reuse-{uuid4().hex}")
            source_id = source.id

        async with repository.unit_of_work() as work:
            first_cycle = await work.create_cycle(NOW, "test")
            first_run = await work.create_source_run(first_cycle.id, source_id, NOW)
            first_candidate = NormalizedArticleCandidate(
                source_id,
                "Original",
                None,
                f"https://example.com/{uuid4().hex}",
                "https://example.com/original",
                NOW,
                NOW,
                "en",
                "original",
                payload_hash="1" * 64,
                external_id="reused-id",
            )
            first_record = SourceArticleRecord(
                uuid4(),
                first_run.id,
                source_id,
                first_candidate.original_url,
                first_candidate.payload_hash,
                NOW,
                ProvenanceStatus.ACCEPTED,
                external_id=first_candidate.external_id,
            )
            first_article, created, first_provenance = await work.ingest_source_article(
                first_candidate, first_record, first_cycle.id
            )
        assert created

        async with repository.unit_of_work() as work:
            second_cycle = await work.create_cycle(NOW + timedelta(minutes=1), "test")
            second_run = await work.create_source_run(
                second_cycle.id, source_id, NOW + timedelta(minutes=1)
            )
            reused_candidate = NormalizedArticleCandidate(
                source_id,
                "Unrelated replacement",
                None,
                f"https://example.com/{uuid4().hex}",
                "https://example.com/replacement",
                NOW,
                NOW + timedelta(minutes=1),
                "en",
                "unrelated replacement",
                payload_hash="2" * 64,
                external_id="reused-id",
            )
            reused_record = SourceArticleRecord(
                uuid4(),
                second_run.id,
                source_id,
                reused_candidate.original_url,
                reused_candidate.payload_hash,
                NOW + timedelta(minutes=1),
                ProvenanceStatus.ACCEPTED,
                external_id=reused_candidate.external_id,
            )
            resolved, reused_created, provenance = await work.ingest_source_article(
                reused_candidate, reused_record, second_cycle.id
            )

        assert not reused_created
        assert resolved.id == first_article.id
        assert provenance.article_id == first_article.id
        assert provenance.source_run_id == second_run.id
        async with database.session() as session:
            article_count = await session.scalar(
                select(func.count()).select_from(models.NormalizedArticle)
            )
            record_count = await session.scalar(
                select(func.count()).select_from(models.SourceArticleRecord)
            )
            first_row = await session.get(
                models.SourceArticleRecord, first_provenance.id
            )
        assert article_count == 1
        assert record_count == 2
        assert first_row is not None
        assert first_row.source_run_id == first_run.id
        assert first_row.original_url == first_candidate.original_url
        assert first_row.payload_hash == first_candidate.payload_hash
    finally:
        async with database.session() as session:
            await session.execute(
                text(
                    "TRUNCATE article_analyses, deduplication_decisions, "
                    "source_article_records, normalized_articles, event_groups, "
                    "source_runs, collection_cycles, news_sources CASCADE"
                )
            )
        await database.close()


async def test_due_sources_polling_source_run_and_idempotent_writes(
    postgres_database_url: str,
) -> None:
    database = Database(postgres_database_url)
    repository = SQLAlchemyNewsRepository(database)
    try:
        async with database.session() as session:
            due = await seed_source(session, endpoint="due")
            await seed_source(session, endpoint="future", due=NOW + timedelta(hours=1))
            disabled = await seed_source(session, endpoint="disabled")
            disabled.enabled = False
            due_id = due.id

        async with repository.unit_of_work() as work:
            sources = await work.list_due_sources(NOW)
            cycle = await work.create_cycle(NOW, "test")
        assert [item.id for item in sources] == [due_id]

        async with repository.unit_of_work() as work:
            run = await work.create_source_run(cycle.id, due_id, NOW)
            retried_run = await work.create_source_run(cycle.id, due_id, NOW)
            await work.finalize_source_run(
                run.id,
                status="processing",
                fetched_count=1,
            )
            await work.update_source_polling(
                due_id,
                polled_at=NOW,
                next_poll_at=NOW + timedelta(seconds=300),
                etag='"v1"',
                last_modified="date",
            )
            candidate = NormalizedArticleCandidate(
                due_id,
                "Title",
                "Summary",
                "https://example.com/story",
                "https://example.com/story?utm_source=x",
                NOW,
                NOW,
                "en",
                "Title Summary",
                payload_hash="a" * 64,
                external_id="story-1",
            )
            article, created = await work.insert_or_resolve_article(candidate, cycle.id)
            duplicate, duplicate_created = await work.insert_or_resolve_article(
                candidate, cycle.id
            )
            record = SourceArticleRecord(
                uuid4(),
                run.id,
                due_id,
                candidate.original_url,
                candidate.payload_hash,
                NOW,
                ProvenanceStatus.ACCEPTED,
                external_id=candidate.external_id,
                article_id=article.id,
            )
            first_record = await work.record_source_article(record)
            second_record = await work.record_source_article(record)
            await work.finalize_source_run(
                run.id,
                status="succeeded",
                completed_at=NOW,
                accepted_count=1,
            )

        assert created
        assert retried_run.id == run.id
        assert not duplicate_created
        assert duplicate.id == article.id
        assert second_record.id == first_record.id

        async with database.session() as session:
            source_row = await session.get(models.NewsSource, due_id)
            run_row = await session.get(models.SourceRun, run.id)
            article_count = await session.scalar(
                select(func.count()).select_from(models.NormalizedArticle)
            )
            provenance_count = await session.scalar(
                select(func.count()).select_from(models.SourceArticleRecord)
            )
        assert source_row is not None
        assert source_row.next_poll_at == NOW + timedelta(seconds=300)
        assert run_row is not None and run_row.status.value == "succeeded"
        assert article_count == 1
        assert provenance_count == 1
    finally:
        await database.close()


async def test_pending_post_processing_is_durable_and_retry_safe(
    postgres_database_url: str,
) -> None:
    database = Database(postgres_database_url)
    repository = SQLAlchemyNewsRepository(database)
    try:
        async with database.session() as session:
            await session.execute(
                text(
                    "TRUNCATE article_analyses, deduplication_decisions, "
                    "source_article_records, normalized_articles, event_groups, "
                    "source_runs, collection_cycles, news_sources CASCADE"
                )
            )
        async with database.session() as session:
            source = await seed_source(session, endpoint=f"post-process-{uuid4().hex}")
            source_id = source.id
        async with repository.unit_of_work() as work:
            cycle = await work.create_cycle(NOW, "test")
            article, _ = await work.insert_or_resolve_article(
                NormalizedArticleCandidate(
                    source_id,
                    "Pending",
                    None,
                    f"https://example.com/{uuid4().hex}",
                    "https://example.com/pending",
                    NOW,
                    NOW,
                    "en",
                    "pending",
                ),
                cycle.id,
            )

        async with repository.unit_of_work() as work:
            assert await work.pending_post_processing_article_ids() == (article.id,)

        async with repository.unit_of_work() as work:
            await work.mark_articles_post_processed((article.id,), NOW)
            await work.mark_articles_post_processed((article.id,), NOW)

        async with repository.unit_of_work() as work:
            assert await work.pending_post_processing_article_ids() == ()
    finally:
        async with database.session() as session:
            await session.execute(
                text(
                    "TRUNCATE article_analyses, deduplication_decisions, "
                    "source_article_records, normalized_articles, event_groups, "
                    "source_runs, collection_cycles, news_sources CASCADE"
                )
            )
        await database.close()
