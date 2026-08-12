from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import UUID, uuid4

from anxious_news_bot.news.domain import (
    AggregationStatus,
    CollectionCycle,
    ConditionalHeaders,
    CycleStatus,
    FetchResult,
    FetchStatus,
    NewsSource,
    NormalizedArticle,
    RawArticle,
    SourceRun,
    SourceRunStatus,
    SourceType,
)
from anxious_news_bot.news.services.aggregate import DefaultNewsAggregator
from anxious_news_bot.news.services.normalize import DeterministicArticleNormalizer


class RealtimeClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class InstrumentedFetcher:
    def __init__(self, delay_seconds: float = 0.005) -> None:
        self.delay_seconds = delay_seconds
        self.active = 0
        self.maximum_active = 0
        self.sequence = 0
        self.last_response_at = 0.0

    async def fetch(
        self, source: NewsSource, conditional_headers: ConditionalHeaders
    ) -> FetchResult:
        del conditional_headers
        self.active += 1
        self.maximum_active = max(self.maximum_active, self.active)
        try:
            await asyncio.sleep(self.delay_seconds)
            self.sequence += 1
            return FetchResult(
                FetchStatus.FETCHED,
                (
                    RawArticle(
                        source.id,
                        f"https://example.com/{source.id}/{self.sequence}",
                        f"Acceptance article {self.sequence}",
                        content=f"Acceptance body {self.sequence}",
                    ),
                ),
            )
        finally:
            self.last_response_at = time.monotonic()
            self.active -= 1


class PerformanceRepository:
    def __init__(self, sources: list[NewsSource]) -> None:
        self.sources = sources
        self.cycles: dict[UUID, CollectionCycle] = {}
        self.articles: dict[str, NormalizedArticle] = {}
        self.post_processed: set[UUID] = set()
        self.completed_at = 0.0

    @asynccontextmanager
    async def unit_of_work(self):
        yield self

    async def try_acquire_cycle_lock(self, lock_key: int) -> bool:
        del lock_key
        return True

    async def release_cycle_lock(self, lock_key: int) -> None:
        del lock_key

    async def create_cycle(self, started_at: datetime, configuration_version: str):
        cycle = CollectionCycle(
            uuid4(), CycleStatus.RUNNING, started_at, configuration_version
        )
        self.cycles[cycle.id] = cycle
        return cycle

    async def list_due_sources(self, now: datetime):
        del now
        return self.sources

    async def create_source_run(
        self, cycle_id: UUID, source_id: UUID, started_at: datetime
    ):
        return SourceRun(
            uuid4(), cycle_id, source_id, SourceRunStatus.PENDING, started_at
        )

    async def finalize_source_run(self, source_run_id: UUID, **changes: object):
        del source_run_id, changes

    async def update_source_polling(self, source_id: UUID, **changes: object):
        del source_id, changes

    async def record_source_article(self, record):
        return record

    async def insert_or_resolve_article(self, candidate, cycle_id: UUID):
        article = self.articles.get(candidate.canonical_url)
        if article is not None:
            return article, False
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
            cycle_id,
        )
        self.articles[candidate.canonical_url] = article
        return article, True

    async def ingest_source_article(self, candidate, record, cycle_id: UUID):
        article, created = await self.insert_or_resolve_article(candidate, cycle_id)
        return article, created, record

    async def pending_post_processing_article_ids(self):
        return tuple(
            article.id
            for article in self.articles.values()
            if article.id not in self.post_processed
        )

    async def mark_articles_post_processed(self, article_ids, completed_at):
        del completed_at
        self.post_processed.update(article_ids)

    async def finalize_cycle(self, cycle_id: UUID, **changes: object) -> None:
        del cycle_id, changes
        self.completed_at = time.monotonic()


def _sources(count: int) -> list[NewsSource]:
    return [
        NewsSource(
            uuid4(),
            f"source-{index}",
            SourceType.RSS,
            f"https://source-{index}.example/feed",
            "World",
            "en",
        )
        for index in range(count)
    ]


async def test_cycles_bound_concurrency_and_meet_ten_minute_readiness_slo() -> None:
    repository = PerformanceRepository(_sources(8))
    fetcher = InstrumentedFetcher()
    aggregator = DefaultNewsAggregator(
        repository,
        fetcher,
        DeterministicArticleNormalizer(),
        RealtimeClock(),
        max_concurrency=3,
    )
    readiness_latencies: list[float] = []

    for _ in range(20):
        result = await aggregator.run_cycle()
        assert result.status is AggregationStatus.COMPLETED
        assert len(result.article_ids) == 8
        readiness_latencies.append(
            repository.completed_at - fetcher.last_response_at
        )

    ready_within_ten_minutes = sum(
        latency <= 10 * 60 for latency in readiness_latencies
    )
    assert fetcher.maximum_active <= 3
    assert ready_within_ten_minutes / len(readiness_latencies) >= 0.95
