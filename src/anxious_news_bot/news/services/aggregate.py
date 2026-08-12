from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from anxious_news_bot.news.domain import (
    AggregationResult,
    AggregationStatus,
    ConditionalHeaders,
    CycleStatus,
    DecisionOutcome,
    DecisionType,
    DeduplicationDecision,
    EventGroupStatus,
    FetchStatus,
    NewsSource,
    NormalizedArticleCandidate,
    ProvenanceStatus,
    RawArticle,
    SourceArticleRecord,
    SourceRunStatus,
)
from anxious_news_bot.news.errors import DiagnosticContext, NewsError
from anxious_news_bot.news.ports import (
    ArticleEnricher,
    ArticleNormalizer,
    ArticleDeduplicator,
    Clock,
    EventGrouper,
    NewsFetcher,
    NewsRepository,
)
from anxious_news_bot.news.services.enrich import ArticleEnrichmentService


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


def _raw_hash(raw: RawArticle) -> str:
    payload: Any = raw.payload or {
        "external_id": raw.external_id,
        "url": raw.original_url,
        "title": raw.title,
        "summary": raw.summary,
        "content": raw.content,
        "published_at": raw.published_at.isoformat() if raw.published_at else None,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


class DefaultNewsAggregator:
    def __init__(
        self,
        repository: NewsRepository,
        fetcher: NewsFetcher,
        normalizer: ArticleNormalizer,
        clock: Clock,
        *,
        deduplicator: ArticleDeduplicator | None = None,
        event_grouper: EventGrouper | None = None,
        enricher: ArticleEnricher | None = None,
        analyzer_name: str = "enricher",
        analyzer_version: str = "1.0",
        duplicate_candidate_limit: int = 100,
        duplicate_candidate_minimum_similarity: float = 0.72,
        event_candidate_limit: int = 100,
        event_window_hours: int = 48,
        max_concurrency: int = 5,
        configuration_version: str = "1.0",
        cycle_lock_key: int = 0x414E5853,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        if duplicate_candidate_limit < 1 or event_candidate_limit < 1:
            raise ValueError("candidate limits must be positive")
        if not 0 <= duplicate_candidate_minimum_similarity <= 1:
            raise ValueError(
                "duplicate_candidate_minimum_similarity must be between zero and one"
            )
        if event_window_hours < 1:
            raise ValueError("event_window_hours must be positive")
        self._repository = repository
        self._source_adapter = fetcher
        self._normalizer = normalizer
        self._clock = clock
        self._deduplicator = deduplicator
        self._event_grouper = event_grouper
        self._enrichment_service = (
            ArticleEnrichmentService(
                enricher,
                clock,
                analyzer_name=analyzer_name,
                analyzer_version=analyzer_version,
            )
            if enricher is not None
            else None
        )
        self._duplicate_candidate_limit = duplicate_candidate_limit
        self._duplicate_candidate_minimum_similarity = (
            duplicate_candidate_minimum_similarity
        )
        self._event_candidate_limit = event_candidate_limit
        self._event_window_hours = event_window_hours
        self._max_concurrency = max_concurrency
        self._configuration_version = configuration_version
        self._cycle_lock_key = cycle_lock_key

    async def run_cycle(self) -> AggregationResult:
        if not await self._repository.try_acquire_cycle_lock(self._cycle_lock_key):
            return AggregationResult(AggregationStatus.ALREADY_RUNNING)

        cycle_id: UUID | None = None
        try:
            started_at = self._clock.now()
            async with self._repository.unit_of_work() as work:
                cycle = await work.create_cycle(
                    started_at, self._configuration_version
                )
                cycle_id = cycle.id
                sources = tuple(await work.list_due_sources(started_at))

            semaphore = asyncio.Semaphore(self._max_concurrency)

            async def limited(source: NewsSource) -> tuple[bool, tuple[UUID, ...]]:
                async with semaphore:
                    return await self._process_source(cycle.id, source)

            outcomes = await asyncio.gather(*(limited(source) for source in sources))
            success_count = sum(success for success, _ in outcomes)
            failure_count = len(outcomes) - success_count
            created_ids = tuple(
                article_id
                for _, article_ids in outcomes
                for article_id in article_ids
            )
            async with self._repository.unit_of_work() as work:
                post_processing_ids = tuple(
                    await work.pending_post_processing_article_ids()
                )
            if post_processing_ids and (
                self._deduplicator is not None
                or self._event_grouper is not None
            ):
                await self._consolidate_articles(post_processing_ids)
            if post_processing_ids and self._enrichment_service is not None:
                await self._enrich_articles(post_processing_ids)
            if post_processing_ids:
                async with self._repository.unit_of_work() as work:
                    await work.mark_articles_post_processed(
                        post_processing_ids, self._clock.now()
                    )
            status = (
                CycleStatus.COMPLETED_WITH_ERRORS
                if failure_count
                else CycleStatus.COMPLETED
            )
            async with self._repository.unit_of_work() as work:
                await work.finalize_cycle(
                    cycle.id,
                    completed_at=self._clock.now(),
                    status=status.value,
                    new_article_count=len(created_ids),
                    source_success_count=success_count,
                    source_failure_count=failure_count,
                )
            return AggregationResult(
                AggregationStatus(status.value),
                cycle.id,
                created_ids,
                success_count,
                failure_count,
            )
        except asyncio.CancelledError:
            if cycle_id is not None:
                await asyncio.shield(self._finalize_cancelled_cycle(cycle_id))
            raise
        except Exception:
            if cycle_id is not None:
                async with self._repository.unit_of_work() as work:
                    await work.finalize_cycle(
                        cycle_id,
                        completed_at=self._clock.now(),
                        status=CycleStatus.FAILED.value,
                        new_article_count=0,
                        source_success_count=0,
                        source_failure_count=0,
                    )
            return AggregationResult(AggregationStatus.FAILED, cycle_id)
        finally:
            await self._repository.release_cycle_lock(self._cycle_lock_key)

    async def _process_source(
        self, cycle_id: UUID, source: NewsSource
    ) -> tuple[bool, tuple[UUID, ...]]:
        observed_at = self._clock.now()
        created_ids: list[UUID] = []
        async with self._repository.unit_of_work() as work:
            source_run = await work.create_source_run(
                cycle_id, source.id, observed_at
            )
            await work.finalize_source_run(
                source_run.id, status=SourceRunStatus.FETCHING.value
            )

        try:
            result = await self._source_adapter.fetch(
                source,
                ConditionalHeaders(source.etag, source.last_modified),
            )
            fetched_at = self._clock.now()
            async with self._repository.unit_of_work() as work:
                next_poll = fetched_at + timedelta(
                    seconds=source.polling_interval_seconds
                )
                await work.update_source_polling(
                    source.id,
                    polled_at=fetched_at,
                    next_poll_at=next_poll,
                    etag=result.etag if result.etag is not None else source.etag,
                    last_modified=result.last_modified
                    if result.last_modified is not None
                    else source.last_modified,
                )
                if result.status is FetchStatus.NOT_MODIFIED:
                    await work.finalize_source_run(
                        source_run.id,
                        status=SourceRunStatus.NOT_MODIFIED.value,
                        completed_at=fetched_at,
                    )
                    return True, ()

                await work.finalize_source_run(
                    source_run.id,
                    status=SourceRunStatus.PROCESSING.value,
                    fetched_count=len(result.records),
                )
                accepted_count = 0
                rejected_count = 0
                for raw in result.records:
                    normalization = self._normalizer.normalize(
                        source, raw, observed_at
                    )
                    if not normalization.accepted:
                        rejected_count += 1
                        await work.record_source_article(
                            SourceArticleRecord(
                                id=uuid4(),
                                source_run_id=source_run.id,
                                source_id=source.id,
                                external_id=raw.external_id,
                                original_url=raw.original_url or source.endpoint_url,
                                raw_payload=raw.payload,
                                payload_hash=_raw_hash(raw),
                                observed_at=observed_at,
                                status=ProvenanceStatus.REJECTED,
                                rejection_code=normalization.rejection_code
                                or "record_rejected",
                            )
                        )
                        continue
                    candidate = normalization.candidate
                    if candidate is None:
                        continue
                    provenance = SourceArticleRecord(
                        id=uuid4(),
                        source_run_id=source_run.id,
                        source_id=source.id,
                        external_id=candidate.external_id,
                        original_url=candidate.original_url,
                        raw_payload=raw.payload,
                        payload_hash=candidate.payload_hash,
                        observed_at=observed_at,
                        status=ProvenanceStatus.ACCEPTED,
                    )
                    article, created, _ = (
                        await work.ingest_source_article(
                            candidate, provenance, cycle_id
                        )
                    )
                    accepted_count += 1
                    if created:
                        created_ids.append(article.id)
                await work.finalize_source_run(
                    source_run.id,
                    status=SourceRunStatus.SUCCEEDED.value,
                    completed_at=self._clock.now(),
                    accepted_count=accepted_count,
                    rejected_count=rejected_count,
                )
                return True, tuple(created_ids)
        except asyncio.CancelledError:
            await asyncio.shield(
                self._finalize_cancelled_source(source_run.id)
            )
            raise
        except NewsError as exc:
            async with self._repository.unit_of_work() as work:
                await self._record_source_failure(
                    work, source, source_run.id, observed_at, exc.code, exc.context
                )
            return False, ()
        except Exception:
            async with self._repository.unit_of_work() as work:
                await self._record_source_failure(
                    work,
                    source,
                    source_run.id,
                    observed_at,
                    "unexpected_source_failure",
                    DiagnosticContext.sanitized({}),
                )
            return False, ()

    async def _finalize_cancelled_cycle(self, cycle_id: UUID) -> None:
        async with self._repository.unit_of_work() as work:
            await work.finalize_cycle(
                cycle_id,
                completed_at=self._clock.now(),
                status=CycleStatus.FAILED.value,
                new_article_count=0,
                source_success_count=0,
                source_failure_count=0,
            )

    async def _finalize_cancelled_source(self, source_run_id: UUID) -> None:
        async with self._repository.unit_of_work() as work:
            await work.finalize_source_run(
                source_run_id,
                status=SourceRunStatus.FAILED.value,
                completed_at=self._clock.now(),
                error_code="cycle_cancelled",
                error_context={},
            )

    async def _consolidate_articles(
        self, article_ids: tuple[UUID, ...]
    ) -> None:
        async with self._repository.unit_of_work() as work:
            articles = tuple(await work.get_articles(article_ids))
            for article in sorted(articles, key=lambda item: item.id.int):
                duplicate_result = None
                if self._deduplicator is not None:
                    candidate = NormalizedArticleCandidate(
                        source_id=article.primary_source_id,
                        title=article.title,
                        summary=article.summary,
                        canonical_url=article.canonical_url,
                        original_url=article.canonical_url,
                        published_at=article.published_at,
                        ingested_at=article.ingested_at,
                        language_code=article.language_code,
                        normalized_text=article.normalized_text,
                        geographic_relevance=article.geographic_relevance,
                        topic_metadata=article.topic_metadata,
                        canonicalization_version=article.canonicalization_version,
                    )
                    candidates = tuple(
                        await work.find_duplicate_candidates(
                            candidate,
                            self._duplicate_candidate_limit,
                            self._duplicate_candidate_minimum_similarity,
                        )
                    )
                    duplicate_result = self._deduplicator.classify(
                        candidate, candidates
                    )
                    await self._record_duplicate_decision(
                        work, article.id, duplicate_result
                    )
                if (
                    self._event_grouper is not None
                    and (
                        duplicate_result is None
                        or duplicate_result.outcome
                        is not DecisionOutcome.DUPLICATE
                    )
                ):
                    await self._group_article_event(work, article)

    async def _enrich_articles(self, article_ids: tuple[UUID, ...]) -> None:
        async with self._repository.unit_of_work() as work:
            articles = tuple(await work.get_articles(article_ids))
        for article in sorted(articles, key=lambda item: item.id.int):
            try:
                analysis = await self._enrichment_service.enrich_article(article)
                async with self._repository.unit_of_work() as work:
                    await work.store_analysis(analysis)
            except asyncio.CancelledError:
                raise
            except Exception:
                continue

    async def _record_duplicate_decision(
        self,
        work: NewsRepository,
        article_id: UUID,
        result,
    ) -> None:
        comparison_id = result.matched_article_id
        if comparison_id is None:
            selected = result.evidence.get("selected_candidate_id")
            comparison_id = UUID(selected) if selected else None
        if comparison_id is None or comparison_id == article_id:
            return
        await work.record_decision(
            DeduplicationDecision(
                id=uuid4(),
                left_article_id=article_id,
                right_article_id=comparison_id,
                decision_type=DecisionType.NEAR_DUPLICATE,
                outcome=result.outcome,
                title_similarity=result.title_similarity,
                content_similarity=result.content_similarity,
                threshold_configuration=dict(result.thresholds),
                normalization_version=result.algorithm_version,
                evidence=dict(result.evidence),
                decided_at=self._clock.now(),
            )
        )

    async def _group_article_event(self, work: NewsRepository, article):
        candidates = tuple(
            await work.find_event_candidates(
                article,
                self._event_candidate_limit,
                self._event_window_hours,
            )
        )
        result = self._event_grouper.group_event(article, candidates)
        matched_id_value = result.evidence.get("matched_article_id")
        if matched_id_value is None:
            return article
        matched_id = UUID(matched_id_value)
        matched = next(
            (candidate for candidate in candidates if candidate.id == matched_id),
            None,
        )
        if matched is None:
            return article

        signals = result.evidence.get("signals", {})
        thresholds = result.evidence.get("thresholds", {})
        evidence = dict(result.evidence)
        if result.outcome is DecisionOutcome.SAME_EVENT:
            event_group_id = result.event_group_id
            if event_group_id is None:
                group = await work.create_event_group(
                    representative_article_id=matched.id,
                    created_at=self._clock.now(),
                    status=EventGroupStatus.PROPOSED,
                )
                event_group_id = group.id
                await work.assign_article_to_event(matched.id, event_group_id)
                evidence["created_event_group_id"] = str(event_group_id)
            article = await work.assign_article_to_event(article.id, event_group_id)
            evidence["assigned_event_group_id"] = str(event_group_id)

        await work.record_decision(
            DeduplicationDecision(
                id=uuid4(),
                left_article_id=article.id,
                right_article_id=matched.id,
                decision_type=DecisionType.EVENT_RELATED,
                outcome=result.outcome,
                title_similarity=self._decimal_signal(
                    signals.get("title_similarity")
                ),
                content_similarity=self._decimal_signal(
                    signals.get("content_similarity")
                ),
                threshold_configuration={
                    "thresholds": thresholds,
                    "weights": result.evidence.get("weights", {}),
                    "window_hours": result.evidence.get("window_hours"),
                },
                normalization_version=result.evidence.get(
                    "algorithm_version", "event-v1"
                ),
                evidence=evidence,
                decided_at=self._clock.now(),
            )
        )
        return article

    @staticmethod
    def _decimal_signal(value: object) -> Decimal | None:
        return Decimal(str(value)) if value is not None else None

    async def _record_source_failure(
        self,
        work: NewsRepository,
        source: NewsSource,
        source_run_id: UUID,
        polled_at: datetime,
        error_code: str,
        context: DiagnosticContext,
    ) -> None:
        await work.update_source_polling(
            source.id,
            polled_at=polled_at,
            next_poll_at=polled_at
            + timedelta(seconds=source.polling_interval_seconds),
            etag=source.etag,
            last_modified=source.last_modified,
        )
        await work.finalize_source_run(
            source_run_id,
            status=SourceRunStatus.FAILED.value,
            completed_at=self._clock.now(),
            error_code=error_code,
            error_context=context.as_dict(),
        )


NewsAggregatorService = DefaultNewsAggregator
