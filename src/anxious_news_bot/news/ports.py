from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any, AsyncContextManager, Protocol, runtime_checkable
from uuid import UUID

from anxious_news_bot.news.domain import (
    AggregationResult,
    ArticleAnalysis,
    CollectionCycle,
    ConditionalHeaders,
    DeduplicationDecision,
    DeduplicationResult,
    EnrichmentResult,
    EventGroup,
    EventGroupStatus,
    EventGroupingResult,
    FetchResult,
    NewsSource,
    NormalizationResult,
    NormalizedArticle,
    NormalizedArticleCandidate,
    RawArticle,
    SourceArticleRecord,
    SourceRun,
)

if TYPE_CHECKING:
    from anxious_news_bot.news.services.source_catalog import (
        CatalogChangePlan,
        CatalogSource,
    )


@runtime_checkable
class NewsFetcher(Protocol):
    async def fetch(
        self,
        source: NewsSource,
        conditional_headers: ConditionalHeaders,
    ) -> FetchResult: ...


@runtime_checkable
class ArticleNormalizer(Protocol):
    def normalize(
        self,
        source: NewsSource,
        raw_article: RawArticle,
        observed_at: datetime,
    ) -> NormalizationResult: ...


@runtime_checkable
class ArticleDeduplicator(Protocol):
    def classify(
        self,
        candidate: NormalizedArticleCandidate,
        candidates: Sequence[NormalizedArticle],
    ) -> DeduplicationResult: ...


@runtime_checkable
class EventGrouper(Protocol):
    def group_event(
        self,
        article: NormalizedArticle,
        candidates: Sequence[NormalizedArticle],
    ) -> EventGroupingResult: ...


@runtime_checkable
class ArticleEnricher(Protocol):
    async def enrich(
        self, article: NormalizedArticle
    ) -> EnrichmentResult | Mapping[str, Any]: ...


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime: ...


@runtime_checkable
class NewsRepository(Protocol):
    def unit_of_work(self) -> AsyncContextManager["NewsRepository"]: ...

    async def try_acquire_cycle_lock(self, lock_key: int) -> bool: ...

    async def release_cycle_lock(self, lock_key: int) -> None: ...

    async def create_cycle(
        self, started_at: datetime, configuration_version: str
    ) -> CollectionCycle: ...

    async def finalize_cycle(
        self,
        cycle_id: UUID,
        *,
        completed_at: datetime,
        status: str,
        new_article_count: int,
        source_success_count: int,
        source_failure_count: int,
    ) -> None: ...

    async def list_due_sources(self, now: datetime) -> Sequence[NewsSource]: ...

    async def plan_source_catalog(
        self, entries: Sequence["CatalogSource"]
    ) -> "CatalogChangePlan": ...

    async def upsert_source_catalog(
        self, entries: Sequence["CatalogSource"]
    ) -> "CatalogChangePlan": ...

    async def create_source_run(
        self, cycle_id: UUID, source_id: UUID, started_at: datetime
    ) -> SourceRun: ...

    async def finalize_source_run(
        self, source_run_id: UUID, **changes: Any
    ) -> None: ...

    async def update_source_polling(
        self,
        source_id: UUID,
        *,
        polled_at: datetime,
        next_poll_at: datetime,
        etag: str | None,
        last_modified: str | None,
    ) -> None: ...

    async def record_source_article(
        self, record: SourceArticleRecord
    ) -> SourceArticleRecord: ...

    async def ingest_source_article(
        self,
        candidate: NormalizedArticleCandidate,
        record: SourceArticleRecord,
        cycle_id: UUID,
    ) -> tuple[NormalizedArticle, bool, SourceArticleRecord]: ...

    async def insert_or_resolve_article(
        self, candidate: NormalizedArticleCandidate, cycle_id: UUID
    ) -> tuple[NormalizedArticle, bool]: ...

    async def get_articles(
        self, article_ids: Sequence[UUID]
    ) -> Sequence[NormalizedArticle]: ...

    async def find_duplicate_candidates(
        self,
        candidate: NormalizedArticleCandidate,
        limit: int,
        minimum_similarity: float,
    ) -> Sequence[NormalizedArticle]: ...

    async def find_event_candidates(
        self, article: NormalizedArticle, limit: int, window_hours: int
    ) -> Sequence[NormalizedArticle]: ...

    async def record_decision(
        self, decision: DeduplicationDecision
    ) -> DeduplicationDecision: ...

    async def create_event_group(
        self,
        *,
        representative_article_id: UUID,
        created_at: datetime,
        status: EventGroupStatus,
    ) -> EventGroup: ...

    async def assign_article_to_event(
        self, article_id: UUID, event_group_id: UUID
    ) -> NormalizedArticle: ...

    async def store_analysis(self, analysis: ArticleAnalysis) -> ArticleAnalysis: ...

    async def article_ids_created_by_cycle(self, cycle_id: UUID) -> tuple[UUID, ...]: ...

    async def pending_post_processing_article_ids(self) -> tuple[UUID, ...]: ...

    async def mark_articles_post_processed(
        self, article_ids: Sequence[UUID], completed_at: datetime
    ) -> None: ...


@runtime_checkable
class NewsAggregator(Protocol):
    async def run_cycle(self) -> AggregationResult: ...
