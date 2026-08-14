from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from anxious_news_bot.news.domain import (
    AggregationStatus,
    AnalysisStatus,
    CollectionCycle,
    ConditionalHeaders,
    CycleStatus,
    DecisionOutcome,
    DecisionType,
    EventGroup,
    FetchResult,
    FetchStatus,
    NewsSource,
    RawArticle,
    SourceRun,
    SourceRunStatus,
    SourceType,
)
from anxious_news_bot.news.errors import SourceUnavailable
from anxious_news_bot.news.services.aggregate import DefaultNewsAggregator
from anxious_news_bot.news.services.deduplicate import DeterministicArticleDeduplicator
from anxious_news_bot.news.services.event_grouping import DeterministicEventGrouper
from anxious_news_bot.news.services.normalize import DeterministicArticleNormalizer

NOW = datetime(2026, 8, 12, 12, tzinfo=UTC)


class FixedClock:
    def now(self) -> datetime:
        return NOW


class MutableClock:
    def __init__(self) -> None:
        self.value = NOW

    def now(self) -> datetime:
        return self.value


class FakeFetcher:
    async def fetch(
        self, source: NewsSource, conditional_headers: ConditionalHeaders
    ) -> FetchResult:
        del conditional_headers
        if source.name == "failed":
            raise SourceUnavailable("timed out", code="source_timeout")
        records = (
            RawArticle(
                source.id,
                f"https://example.com/{source.name}/valid",
                f"{source.name} title",
                content="Useful content",
                external_id=f"{source.name}-1",
            ),
            RawArticle(source.id, "", None),
        )
        return FetchResult(FetchStatus.FETCHED, records, '"new"', "date")


class ConsolidationFetcher:
    _records = {
        "duplicate-one": ("Duplicate report", "Identical duplicate content"),
        "duplicate-two": ("Duplicate report", "Identical duplicate content"),
        "event-one": ("abcdefgh", "First independent account"),
        "event-two": ("abcdeXYZ", "Second independent account"),
    }

    async def fetch(
        self, source: NewsSource, conditional_headers: ConditionalHeaders
    ) -> FetchResult:
        del conditional_headers
        title, content = self._records[source.name]
        return FetchResult(
            FetchStatus.FETCHED,
            (
                RawArticle(
                    source.id,
                    f"https://{source.name}.example.com/report",
                    title,
                    content=content,
                    external_id=source.name,
                ),
            ),
        )


class CompletionAdvancingFetcher(FakeFetcher):
    def __init__(self, clock: MutableClock) -> None:
        self.clock = clock

    async def fetch(
        self, source: NewsSource, conditional_headers: ConditionalHeaders
    ) -> FetchResult:
        result = await super().fetch(source, conditional_headers)
        self.clock.value = NOW.replace(minute=NOW.minute + 2)
        return result


class FakeRepository:
    def __init__(self, sources: list[NewsSource], *, lock: bool = True) -> None:
        self.sources = sources
        self.lock = lock
        self.cycle = CollectionCycle(uuid4(), CycleStatus.RUNNING, NOW, "test")
        self.runs: dict[UUID, dict[str, object]] = {}
        self.articles: dict[str, object] = {}
        self.final_cycle: dict[str, object] = {}
        self.poll_updates: list[UUID] = []
        self.polling_changes: list[dict[str, object]] = []
        self.records: list[object] = []
        self.decisions: list[object] = []
        self.groups: dict[UUID, EventGroup] = {}
        self.analyses: list[object] = []
        self.lock_released = False
        self.post_processed: set[UUID] = set()

    @asynccontextmanager
    async def unit_of_work(self):
        yield self

    async def try_acquire_cycle_lock(self, lock_key: int) -> bool:
        del lock_key
        return self.lock

    async def release_cycle_lock(self, lock_key: int) -> None:
        del lock_key
        self.lock_released = True

    async def create_cycle(self, started_at: datetime, configuration_version: str):
        del started_at, configuration_version
        return self.cycle

    async def finalize_cycle(self, cycle_id: UUID, **changes: object) -> None:
        assert cycle_id == self.cycle.id
        self.final_cycle = changes

    async def list_due_sources(self, now: datetime):
        return [
            source
            for source in self.sources
            if source.enabled
            and (source.next_poll_at is None or source.next_poll_at <= now)
        ]

    async def create_source_run(
        self, cycle_id: UUID, source_id: UUID, started_at: datetime
    ):
        run = SourceRun(
            uuid4(), cycle_id, source_id, SourceRunStatus.PENDING, started_at
        )
        self.runs[source_id] = {}
        return run

    async def finalize_source_run(self, source_run_id: UUID, **changes: object):
        for _source_id, values in self.runs.items():
            if not values or values.get("id") == source_run_id:
                values.update(changes)
                values["id"] = source_run_id
                return

    async def update_source_polling(self, source_id: UUID, **changes: object):
        self.poll_updates.append(source_id)
        self.polling_changes.append({"source_id": source_id, **changes})

    async def record_source_article(self, record):
        self.records.append(record)
        return record

    async def insert_or_resolve_article(self, candidate, cycle_id: UUID):
        del cycle_id
        from anxious_news_bot.news.domain import NormalizedArticle

        article = self.articles.get(candidate.canonical_url)
        created = article is None
        if article is None:
            article = NormalizedArticle(
                uuid4(),
                candidate.title,
                candidate.summary,
                candidate.canonical_url,
                candidate.canonicalization_version,
                candidate.source_id,
                candidate.published_at,
                candidate.ingested_at,
                candidate.language_code,
                candidate.normalized_text,
                self.cycle.id,
                candidate.geographic_relevance,
                candidate.topic_metadata,
            )
            self.articles[candidate.canonical_url] = article
        return article, created

    async def ingest_source_article(self, candidate, record, cycle_id: UUID):
        article, created = await self.insert_or_resolve_article(candidate, cycle_id)
        if not any(
            existing.source_id == record.source_id
            and (
                existing.payload_hash == record.payload_hash
                or (
                    record.external_id is not None
                    and existing.external_id == record.external_id
                )
            )
            for existing in self.records
        ):
            self.records.append(replace(record, article_id=article.id))
        stored = next(
            existing
            for existing in self.records
            if existing.source_id == record.source_id
            and (
                existing.payload_hash == record.payload_hash
                or (
                    record.external_id is not None
                    and existing.external_id == record.external_id
                )
            )
        )
        existing_article = next(
            (
                value
                for value in self.articles.values()
                if value.id == stored.article_id
            ),
            article,
        )
        return existing_article, created and existing_article.id == article.id, stored

    async def get_articles(self, article_ids):
        wanted = set(article_ids)
        return tuple(
            sorted(
                (article for article in self.articles.values() if article.id in wanted),
                key=lambda article: article.id,
            )
        )

    async def find_duplicate_candidates(
        self, candidate, limit: int, minimum_similarity: float
    ):
        del minimum_similarity
        return tuple(
            article
            for article in sorted(
                self.articles.values(), key=lambda article: article.id
            )
            if article.canonical_url != candidate.canonical_url
        )[:limit]

    async def find_event_candidates(self, article, limit: int, window_hours: int):
        del window_hours
        return tuple(
            candidate
            for candidate in sorted(self.articles.values(), key=lambda item: item.id)
            if candidate.id != article.id
        )[:limit]

    async def record_decision(self, decision):
        pair = {
            decision.left_article_id,
            decision.right_article_id,
        }
        existing = next(
            (
                item
                for item in self.decisions
                if {item.left_article_id, item.right_article_id} == pair
                and item.decision_type is decision.decision_type
                and item.normalization_version == decision.normalization_version
            ),
            None,
        )
        if existing is not None:
            return existing
        self.decisions.append(decision)
        return decision

    async def create_event_group(
        self, *, representative_article_id, created_at, status
    ):
        group = EventGroup(
            uuid4(),
            status,
            created_at,
            created_at,
            representative_article_id=representative_article_id,
        )
        self.groups[group.id] = group
        return group

    async def assign_article_to_event(self, article_id, event_group_id):
        for url, article in self.articles.items():
            if article.id == article_id:
                assigned = replace(article, event_group_id=event_group_id)
                self.articles[url] = assigned
                return assigned
        raise AssertionError("article not found")

    async def article_ids_created_by_cycle(self, cycle_id: UUID):
        del cycle_id
        return tuple(article.id for article in self.articles.values())

    async def pending_post_processing_article_ids(self):
        return tuple(
            article.id
            for article in self.articles.values()
            if article.id not in self.post_processed
        )

    async def mark_articles_post_processed(self, article_ids, completed_at):
        del completed_at
        self.post_processed.update(article_ids)

    async def store_analysis(self, analysis):
        self.analyses.append(analysis)
        return analysis


class PostDurableEnricher:
    def __init__(self, repository: FakeRepository, *, fail: bool = False) -> None:
        self.repository = repository
        self.fail = fail

    async def enrich(self, article):
        assert article in self.repository.articles.values()
        if self.fail:
            raise RuntimeError("provider unavailable")
        return {
            "schema_version": "1.0",
            "status": "complete",
            "sections": {"topics": ["world"], "importance": Decimal("0.8")},
        }


class FailOnceDeduplicator:
    def __init__(self) -> None:
        self.calls = 0
        self.delegate = DeterministicArticleDeduplicator()

    def classify(self, candidate, candidates):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("post-processing crashed")
        return self.delegate.classify(candidate, candidates)


class BlockingFetcher:
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def fetch(self, source, conditional_headers):
        del source, conditional_headers
        self.started.set()
        await asyncio.Event().wait()


def make_source(
    name: str, *, enabled: bool = True, due: datetime | None = None
) -> NewsSource:
    return NewsSource(
        uuid4(),
        name,
        SourceType.RSS,
        f"https://{name}.example.com/feed",
        "World",
        "en",
        enabled=enabled,
        next_poll_at=due,
        polling_interval_seconds=300,
    )


async def test_cycle_logs_source_and_cycle_counts(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(
        "INFO",
        logger="anxious_news_bot.news.services.aggregate",
    )
    repository = FakeRepository([make_source("one")])

    result = await DefaultNewsAggregator(
        repository,
        FakeFetcher(),
        DeterministicArticleNormalizer(),
        FixedClock(),
    ).run_cycle()

    assert result.status is AggregationStatus.COMPLETED
    source_record = next(
        record for record in caplog.records if record.message == "news_source_completed"
    )
    assert source_record.news["fetched_count"] == 2
    assert source_record.news["accepted_count"] == 1
    assert source_record.news["rejected_count"] == 1
    assert source_record.news["rejection_code_counts"] == {"missing_title": 1}
    assert source_record.news["new_article_count"] == 1
    cycle_record = next(
        record for record in caplog.records if record.message == "news_cycle_completed"
    )
    assert cycle_record.news["due_source_count"] == 1
    assert cycle_record.news["source_success_count"] == 1
    assert cycle_record.news["new_article_count"] == 1


async def test_cycle_isolates_sources_records_rejections_and_returns_only_new() -> None:
    disabled = make_source("disabled", enabled=False)
    future = make_source("future", due=datetime(2026, 8, 13, tzinfo=UTC))
    sources = [
        make_source("one"),
        make_source("two"),
        make_source("failed"),
        disabled,
        future,
    ]
    repository = FakeRepository(sources)
    aggregator = DefaultNewsAggregator(
        repository,
        FakeFetcher(),
        DeterministicArticleNormalizer(),
        FixedClock(),
        max_concurrency=2,
        configuration_version="test",
    )

    first = await aggregator.run_cycle()
    second = await aggregator.run_cycle()

    assert first.status is AggregationStatus.COMPLETED_WITH_ERRORS
    assert first.source_success_count == 2
    assert first.source_failure_count == 1
    assert len(first.article_ids) == 2
    assert second.article_ids == ()
    assert disabled.id not in repository.poll_updates
    assert future.id not in repository.poll_updates
    assert len(repository.poll_updates) == 6
    assert (
        sum(
            getattr(record, "rejection_code", None) == "missing_title"
            for record in repository.records
        )
        == 4
    )


async def test_cycle_returns_already_running_without_creating_cycle() -> None:
    repository = FakeRepository([], lock=False)
    result = await DefaultNewsAggregator(
        repository,
        FakeFetcher(),
        DeterministicArticleNormalizer(),
        FixedClock(),
    ).run_cycle()

    assert result.status is AggregationStatus.ALREADY_RUNNING
    assert result.cycle_id is None


async def test_polling_schedule_uses_fetch_completion_time() -> None:
    source = make_source("one")
    repository = FakeRepository([source])
    clock = MutableClock()

    await DefaultNewsAggregator(
        repository,
        CompletionAdvancingFetcher(clock),
        DeterministicArticleNormalizer(),
        clock,
    ).run_cycle()

    assert repository.polling_changes[0]["polled_at"] == clock.value
    assert repository.polling_changes[0]["next_poll_at"] == (
        clock.value + timedelta(seconds=source.polling_interval_seconds)
    )


async def test_failed_post_processing_is_recovered_without_new_articles() -> None:
    repository = FakeRepository([make_source("one")])
    deduplicator = FailOnceDeduplicator()
    aggregator = DefaultNewsAggregator(
        repository,
        FakeFetcher(),
        DeterministicArticleNormalizer(),
        FixedClock(),
        deduplicator=deduplicator,
    )

    first = await aggregator.run_cycle()
    article_id = next(iter(repository.articles.values())).id
    repository.sources = []
    second = await aggregator.run_cycle()

    assert first.status is AggregationStatus.FAILED
    assert second.status is AggregationStatus.COMPLETED
    assert second.article_ids == ()
    assert deduplicator.calls == 2
    assert repository.post_processed == {article_id}


async def test_cycle_persists_duplicate_and_event_evidence_after_concurrent_ingestion() -> (
    None
):
    repository = FakeRepository(
        [
            make_source("duplicate-one"),
            make_source("duplicate-two"),
            make_source("event-one"),
            make_source("event-two"),
        ]
    )
    aggregator = DefaultNewsAggregator(
        repository,
        ConsolidationFetcher(),
        DeterministicArticleNormalizer(),
        FixedClock(),
        deduplicator=DeterministicArticleDeduplicator(),
        event_grouper=DeterministicEventGrouper(
            title_weight=Decimal(1),
            content_weight=Decimal(0),
            topic_weight=Decimal(0),
            geography_weight=Decimal(0),
        ),
        max_concurrency=4,
    )

    result = await aggregator.run_cycle()

    assert result.status is AggregationStatus.COMPLETED
    assert len(result.article_ids) == 4
    assert any(
        decision.decision_type is DecisionType.NEAR_DUPLICATE
        and decision.outcome is DecisionOutcome.DUPLICATE
        for decision in repository.decisions
    )
    assert any(
        decision.decision_type is DecisionType.EVENT_RELATED
        and decision.outcome is DecisionOutcome.SAME_EVENT
        and decision.evidence["assigned_event_group_id"]
        for decision in repository.decisions
    )
    event_articles = [
        article
        for article in repository.articles.values()
        if article.title in {"abcdefgh", "abcdeXYZ"}
    ]
    assert len({article.event_group_id for article in event_articles}) == 1
    assert event_articles[0].event_group_id is not None
    assert {record.original_url for record in repository.records} == {
        "https://duplicate-one.example.com/report",
        "https://duplicate-two.example.com/report",
        "https://event-one.example.com/report",
        "https://event-two.example.com/report",
    }


async def test_optional_enrichment_runs_after_articles_are_durable() -> None:
    repository = FakeRepository([make_source("one")])
    result = await DefaultNewsAggregator(
        repository,
        FakeFetcher(),
        DeterministicArticleNormalizer(),
        FixedClock(),
        enricher=PostDurableEnricher(repository),
        analyzer_name="fake",
        analyzer_version="v1",
    ).run_cycle()

    assert result.status is AggregationStatus.COMPLETED
    assert len(result.article_ids) == 1
    assert len(repository.analyses) == 1
    assert repository.analyses[0].status is AnalysisStatus.COMPLETE


async def test_enrichment_failure_never_rolls_back_a_valid_article() -> None:
    repository = FakeRepository([make_source("one")])
    result = await DefaultNewsAggregator(
        repository,
        FakeFetcher(),
        DeterministicArticleNormalizer(),
        FixedClock(),
        enricher=PostDurableEnricher(repository, fail=True),
        analyzer_name="fake",
        analyzer_version="v1",
    ).run_cycle()

    assert result.status is AggregationStatus.COMPLETED
    assert len(result.article_ids) == 1
    assert len(repository.articles) == 1
    assert repository.analyses[0].status is AnalysisStatus.FAILED


async def test_cancellation_finalizes_cycle_and_source_then_releases_lock() -> None:
    source = make_source("blocked")
    repository = FakeRepository([source])
    fetcher = BlockingFetcher()
    task = asyncio.create_task(
        DefaultNewsAggregator(
            repository,
            fetcher,
            DeterministicArticleNormalizer(),
            FixedClock(),
        ).run_cycle()
    )
    await fetcher.started.wait()

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    else:
        raise AssertionError("cycle cancellation must be re-raised")

    assert repository.final_cycle["status"] == CycleStatus.FAILED.value
    assert repository.runs[source.id]["status"] == SourceRunStatus.FAILED.value
    assert repository.runs[source.id]["error_code"] == "cycle_cancelled"
    assert repository.lock_released
