from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import case, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from anxious_news_bot.news import domain
from anxious_news_bot.news.infrastructure import models
from anxious_news_bot.news.infrastructure.database import Database
from anxious_news_bot.news.services.source_catalog import (
    CatalogChangePlan,
    CatalogSource,
)


def _source(row: models.NewsSource) -> domain.NewsSource:
    return domain.NewsSource(
        id=row.id,
        name=row.name,
        source_type=row.source_type,
        endpoint_url=row.endpoint_url,
        region=row.region,
        language_code=row.language_code,
        enabled=row.enabled,
        country_code=row.country_code,
        quality_score=row.quality_score,
        polling_interval_seconds=row.polling_interval_seconds,
        last_polled_at=row.last_polled_at,
        next_poll_at=row.next_poll_at,
        etag=row.etag,
        last_modified=row.last_modified,
        credential_ref=row.credential_ref,
    )


def _cycle(row: models.CollectionCycle) -> domain.CollectionCycle:
    return domain.CollectionCycle(
        row.id,
        row.status,
        row.started_at,
        row.configuration_version,
        row.completed_at,
        row.new_article_count,
        row.source_success_count,
        row.source_failure_count,
    )


def _source_run(row: models.SourceRun) -> domain.SourceRun:
    return domain.SourceRun(
        row.id,
        row.cycle_id,
        row.source_id,
        row.status,
        row.started_at,
        row.completed_at,
        row.fetched_count,
        row.accepted_count,
        row.rejected_count,
        row.error_code,
        row.error_context,
    )


def _article(row: models.NormalizedArticle) -> domain.NormalizedArticle:
    return domain.NormalizedArticle(
        id=row.id,
        title=row.title,
        summary=row.summary,
        canonical_url=row.canonical_url,
        canonicalization_version=row.canonicalization_version,
        primary_source_id=row.primary_source_id,
        published_at=row.published_at,
        ingested_at=row.ingested_at,
        language_code=row.language_code,
        normalized_text=row.normalized_text,
        created_in_cycle_id=row.created_in_cycle_id,
        geographic_relevance=tuple(row.geographic_relevance),
        topic_metadata=tuple(row.topic_metadata),
        event_group_id=row.event_group_id,
    )


def _record(row: models.SourceArticleRecord) -> domain.SourceArticleRecord:
    return domain.SourceArticleRecord(
        id=row.id,
        source_run_id=row.source_run_id,
        source_id=row.source_id,
        original_url=row.original_url,
        payload_hash=row.payload_hash,
        observed_at=row.observed_at,
        status=row.status,
        external_id=row.external_id,
        raw_payload=row.raw_payload,
        rejection_code=row.rejection_code,
        article_id=row.article_id,
    )


def _decision(row: models.DeduplicationDecision) -> domain.DeduplicationDecision:
    return domain.DeduplicationDecision(
        id=row.id,
        left_article_id=row.left_article_id,
        right_article_id=row.right_article_id,
        decision_type=row.decision_type,
        outcome=row.outcome,
        threshold_configuration=row.threshold_configuration,
        normalization_version=row.normalization_version,
        evidence=row.evidence,
        decided_at=row.decided_at,
        title_similarity=row.title_similarity,
        content_similarity=row.content_similarity,
    )


def _event_group(row: models.EventGroup) -> domain.EventGroup:
    return domain.EventGroup(
        id=row.id,
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
        label=row.label,
        event_type=row.event_type,
        representative_article_id=row.representative_article_id,
    )


def _analysis(row: models.ArticleAnalysis) -> domain.ArticleAnalysis:
    return domain.ArticleAnalysis(
        id=row.id,
        article_id=row.article_id,
        status=row.status,
        schema_version=row.schema_version,
        analyzer_name=row.analyzer_name,
        analyzer_version=row.analyzer_version,
        created_at=row.created_at,
        topics=tuple(row.topics),
        countries=tuple(row.countries),
        cities=tuple(row.cities),
        locations=tuple(row.locations),
        people=tuple(row.people),
        organizations=tuple(row.organizations),
        event_type=row.event_type,
        importance_score=row.importance_score,
        novelty_score=row.novelty_score,
        source_quality_score=row.source_quality_score,
        semantic_metadata=row.semantic_metadata,
        error_code=row.error_code,
    )


def _source_configuration(row: models.NewsSource) -> tuple[Any, ...]:
    return (
        row.name,
        row.source_type,
        row.endpoint_url,
        row.region,
        row.country_code,
        row.language_code,
        row.enabled,
        row.quality_score,
        row.polling_interval_seconds,
        row.credential_ref,
    )


def _catalog_configuration(entry: CatalogSource) -> tuple[Any, ...]:
    return (
        entry.name,
        entry.source_type,
        entry.endpoint_url,
        entry.region,
        entry.country_code,
        entry.language_code,
        entry.enabled,
        entry.quality_score,
        entry.polling_interval_seconds,
        entry.credential_ref,
    )


class SQLAlchemyNewsRepository:
    def __init__(
        self,
        database: Database,
        session: AsyncSession | None = None,
    ) -> None:
        self._database = database
        self._session = session
        self._lock_connection: AsyncConnection | None = None
        self._lock_owners: dict[int, asyncio.Task[Any] | None] = {}
        self._lock_guard = asyncio.Lock()

    def _require_session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("repository operation requires a unit of work")
        return self._session

    @asynccontextmanager
    async def unit_of_work(self):
        if self._session is not None:
            yield self
            return
        async with self._database.session() as session:
            yield SQLAlchemyNewsRepository(self._database, session)

    async def try_acquire_cycle_lock(self, lock_key: int) -> bool:
        if self._session is not None:
            raise RuntimeError("cycle locks must be acquired by the root repository")
        async with self._lock_guard:
            if lock_key in self._lock_owners:
                return False
            if self._lock_connection is None:
                self._lock_connection = await self._database.engine.connect()
            acquired = bool(
                await self._lock_connection.scalar(
                    text("SELECT pg_try_advisory_lock(:key)"), {"key": lock_key}
                )
            )
            if acquired:
                self._lock_owners[lock_key] = asyncio.current_task()
            elif not self._lock_owners:
                await self._lock_connection.close()
                self._lock_connection = None
            return acquired

    async def release_cycle_lock(self, lock_key: int) -> None:
        async with self._lock_guard:
            if (
                self._lock_connection is None
                or self._lock_owners.get(lock_key) is not asyncio.current_task()
            ):
                return
            await self._lock_connection.execute(
                text("SELECT pg_advisory_unlock(:key)"), {"key": lock_key}
            )
            self._lock_owners.pop(lock_key, None)
            if not self._lock_owners:
                await self._lock_connection.close()
                self._lock_connection = None

    async def create_cycle(
        self, started_at: datetime, configuration_version: str
    ) -> domain.CollectionCycle:
        row = models.CollectionCycle(
            id=uuid4(),
            status=domain.CycleStatus.RUNNING,
            started_at=started_at,
            configuration_version=configuration_version,
        )
        self._require_session().add(row)
        await self._require_session().flush()
        return _cycle(row)

    async def finalize_cycle(
        self,
        cycle_id: UUID,
        *,
        completed_at: datetime,
        status: str,
        new_article_count: int,
        source_success_count: int,
        source_failure_count: int,
    ) -> None:
        await self._require_session().execute(
            update(models.CollectionCycle)
            .where(models.CollectionCycle.id == cycle_id)
            .values(
                completed_at=completed_at,
                status=domain.CycleStatus(status),
                new_article_count=new_article_count,
                source_success_count=source_success_count,
                source_failure_count=source_failure_count,
            )
        )

    async def list_due_sources(
        self, now: datetime
    ) -> tuple[domain.NewsSource, ...]:
        rows = (
            await self._require_session().scalars(
                select(models.NewsSource)
                .where(
                    models.NewsSource.enabled.is_(True),
                    or_(
                        models.NewsSource.next_poll_at.is_(None),
                        models.NewsSource.next_poll_at <= now,
                    ),
                )
                .order_by(
                    models.NewsSource.next_poll_at.asc().nullsfirst(),
                    models.NewsSource.id,
                )
            )
        ).all()
        return tuple(_source(row) for row in rows)

    async def plan_source_catalog(
        self, entries: tuple[CatalogSource, ...] | list[CatalogSource]
    ) -> CatalogChangePlan:
        if not entries:
            return CatalogChangePlan()
        existing = {
            row.id: row
            for row in (
                await self._require_session().scalars(
                    select(models.NewsSource).where(
                        models.NewsSource.id.in_([entry.id for entry in entries])
                    )
                )
            ).all()
        }
        added: list[UUID] = []
        updated: list[UUID] = []
        unchanged: list[UUID] = []
        for entry in entries:
            row = existing.get(entry.id)
            if row is None:
                added.append(entry.id)
            elif _source_configuration(row) == _catalog_configuration(entry):
                unchanged.append(entry.id)
            else:
                updated.append(entry.id)
        key = lambda value: value.int
        return CatalogChangePlan(
            added=tuple(sorted(added, key=key)),
            updated=tuple(sorted(updated, key=key)),
            unchanged=tuple(sorted(unchanged, key=key)),
        )

    async def upsert_source_catalog(
        self, entries: tuple[CatalogSource, ...] | list[CatalogSource]
    ) -> CatalogChangePlan:
        plan = await self.plan_source_catalog(entries)
        if not entries:
            return plan
        statement = insert(models.NewsSource).values(
            [
                {
                    "id": entry.id,
                    "name": entry.name,
                    "source_type": entry.source_type,
                    "endpoint_url": entry.endpoint_url,
                    "region": entry.region,
                    "country_code": entry.country_code,
                    "language_code": entry.language_code,
                    "enabled": entry.enabled,
                    "quality_score": entry.quality_score,
                    "polling_interval_seconds": entry.polling_interval_seconds,
                    "credential_ref": entry.credential_ref,
                }
                for entry in entries
            ]
        )
        excluded = statement.excluded
        conditional_identity_changed = or_(
            models.NewsSource.source_type != excluded.source_type,
            models.NewsSource.endpoint_url != excluded.endpoint_url,
        )
        await self._require_session().execute(
            statement.on_conflict_do_update(
                index_elements=[models.NewsSource.id],
                set_={
                    "name": excluded.name,
                    "source_type": excluded.source_type,
                    "endpoint_url": excluded.endpoint_url,
                    "region": excluded.region,
                    "country_code": excluded.country_code,
                    "language_code": excluded.language_code,
                    "enabled": excluded.enabled,
                    "quality_score": excluded.quality_score,
                    "polling_interval_seconds": excluded.polling_interval_seconds,
                    "credential_ref": excluded.credential_ref,
                    "etag": case(
                        (conditional_identity_changed, None),
                        else_=models.NewsSource.etag,
                    ),
                    "last_modified": case(
                        (conditional_identity_changed, None),
                        else_=models.NewsSource.last_modified,
                    ),
                    "updated_at": func.now(),
                },
            )
        )
        return plan

    async def create_source_run(
        self, cycle_id: UUID, source_id: UUID, started_at: datetime
    ) -> domain.SourceRun:
        run_id = uuid4()
        result = await self._require_session().execute(
            insert(models.SourceRun)
            .values(
                id=run_id,
                cycle_id=cycle_id,
                source_id=source_id,
                status=domain.SourceRunStatus.PENDING,
                started_at=started_at,
            )
            .on_conflict_do_nothing(
                constraint="uq_source_runs_cycle_source"
            )
            .returning(models.SourceRun.id)
        )
        resolved_id = result.scalar_one_or_none()
        row = await self._require_session().scalar(
            select(models.SourceRun).where(
                models.SourceRun.id
                == (resolved_id if resolved_id is not None else run_id)
            )
        )
        if row is None:
            row = await self._require_session().scalar(
                select(models.SourceRun).where(
                    models.SourceRun.cycle_id == cycle_id,
                    models.SourceRun.source_id == source_id,
                )
            )
        if row is None:
            raise RuntimeError("source run could not be resolved")
        return _source_run(row)

    async def finalize_source_run(
        self, source_run_id: UUID, **changes: Any
    ) -> None:
        values = dict(changes)
        if "status" in values:
            values["status"] = domain.SourceRunStatus(values["status"])
        allowed = {
            "status",
            "completed_at",
            "fetched_count",
            "accepted_count",
            "rejected_count",
            "error_code",
            "error_context",
        }
        await self._require_session().execute(
            update(models.SourceRun)
            .where(models.SourceRun.id == source_run_id)
            .values(**{key: value for key, value in values.items() if key in allowed})
        )

    async def update_source_polling(
        self,
        source_id: UUID,
        *,
        polled_at: datetime,
        next_poll_at: datetime,
        etag: str | None,
        last_modified: str | None,
    ) -> None:
        await self._require_session().execute(
            update(models.NewsSource)
            .where(models.NewsSource.id == source_id)
            .values(
                last_polled_at=polled_at,
                next_poll_at=next_poll_at,
                etag=etag,
                last_modified=last_modified,
            )
        )

    async def record_source_article(
        self, record: domain.SourceArticleRecord
    ) -> domain.SourceArticleRecord:
        values = {
            "id": record.id,
            "source_run_id": record.source_run_id,
            "source_id": record.source_id,
            "external_id": record.external_id,
            "original_url": record.original_url,
            "raw_payload": dict(record.raw_payload) if record.raw_payload else None,
            "payload_hash": record.payload_hash,
            "observed_at": record.observed_at,
            "status": record.status,
            "rejection_code": record.rejection_code,
            "article_id": record.article_id,
        }
        await self._require_session().execute(
            insert(models.SourceArticleRecord).values(**values).on_conflict_do_nothing()
        )
        criteria = [
            models.SourceArticleRecord.source_run_id == record.source_run_id,
            models.SourceArticleRecord.source_id == record.source_id,
        ]
        if record.external_id is not None:
            criteria.append(
                or_(
                    models.SourceArticleRecord.external_id == record.external_id,
                    models.SourceArticleRecord.payload_hash == record.payload_hash,
                )
            )
        else:
            criteria.append(
                models.SourceArticleRecord.payload_hash == record.payload_hash
            )
        row = await self._require_session().scalar(
            select(models.SourceArticleRecord).where(*criteria)
        )
        if row is None:
            raise RuntimeError("source article record could not be resolved")
        return _record(row)

    async def ingest_source_article(
        self,
        candidate: domain.NormalizedArticleCandidate,
        record: domain.SourceArticleRecord,
        cycle_id: UUID,
    ) -> tuple[
        domain.NormalizedArticle,
        bool,
        domain.SourceArticleRecord,
    ]:
        session = self._require_session()
        existing_observation = None
        if record.external_id is not None:
            existing_observation = await session.scalar(
                select(models.SourceArticleRecord).where(
                    models.SourceArticleRecord.source_run_id
                    == record.source_run_id,
                    models.SourceArticleRecord.source_id == record.source_id,
                    models.SourceArticleRecord.external_id == record.external_id,
                )
            )
        if existing_observation is None:
            existing_observation = await session.scalar(
                select(models.SourceArticleRecord).where(
                    models.SourceArticleRecord.source_run_id
                    == record.source_run_id,
                    models.SourceArticleRecord.source_id == record.source_id,
                    models.SourceArticleRecord.payload_hash == record.payload_hash,
                )
            )
        if existing_observation is not None:
            if existing_observation.article_id is None:
                raise RuntimeError(
                    "accepted source observation is missing its article"
                )
            article_row = await session.get(
                models.NormalizedArticle, existing_observation.article_id
            )
            if article_row is None:
                raise RuntimeError("source observation is missing its article")
            return _article(article_row), False, _record(existing_observation)

        prior_observation = None
        if record.external_id is not None:
            prior_observation = await session.scalar(
                select(models.SourceArticleRecord)
                .where(
                    models.SourceArticleRecord.source_id == record.source_id,
                    models.SourceArticleRecord.external_id == record.external_id,
                    models.SourceArticleRecord.article_id.is_not(None),
                )
                .order_by(
                    models.SourceArticleRecord.observed_at,
                    models.SourceArticleRecord.id,
                )
                .limit(1)
            )
        if prior_observation is None:
            prior_observation = await session.scalar(
                select(models.SourceArticleRecord)
                .where(
                    models.SourceArticleRecord.source_id == record.source_id,
                    models.SourceArticleRecord.payload_hash == record.payload_hash,
                    models.SourceArticleRecord.article_id.is_not(None),
                )
                .order_by(
                    models.SourceArticleRecord.observed_at,
                    models.SourceArticleRecord.id,
                )
                .limit(1)
            )

        existing_article = None
        if prior_observation is not None:
            existing_article = await session.get(
                models.NormalizedArticle, prior_observation.article_id
            )
            if existing_article is None:
                raise RuntimeError("source identity is missing its article")

        article = _article(existing_article) if existing_article is not None else None
        created = False
        if article is None:
            article, created = await self.insert_or_resolve_article(
                candidate, cycle_id
            )
        values = {
            "id": record.id,
            "source_run_id": record.source_run_id,
            "source_id": record.source_id,
            "external_id": record.external_id,
            "original_url": record.original_url,
            "raw_payload": dict(record.raw_payload) if record.raw_payload else None,
            "payload_hash": record.payload_hash,
            "observed_at": record.observed_at,
            "rejection_code": record.rejection_code,
            "article_id": article.id,
            "status": (
                domain.ProvenanceStatus.DUPLICATE
                if not created
                and record.status is domain.ProvenanceStatus.ACCEPTED
                else record.status
            ),
        }
        inserted_id = (
            await session.execute(
                insert(models.SourceArticleRecord)
                .values(**values)
                .on_conflict_do_nothing()
                .returning(models.SourceArticleRecord.id)
            )
        ).scalar_one_or_none()

        row = None
        if inserted_id is not None:
            row = await session.scalar(
                select(models.SourceArticleRecord)
                .where(models.SourceArticleRecord.id == inserted_id)
                .with_for_update()
            )
        if row is None and record.external_id is not None:
            row = await session.scalar(
                select(models.SourceArticleRecord)
                .where(
                    models.SourceArticleRecord.source_run_id
                    == record.source_run_id,
                    models.SourceArticleRecord.source_id == record.source_id,
                    models.SourceArticleRecord.external_id == record.external_id,
                )
                .with_for_update()
            )
        if row is None:
            row = await session.scalar(
                select(models.SourceArticleRecord)
                .where(
                    models.SourceArticleRecord.source_run_id
                    == record.source_run_id,
                    models.SourceArticleRecord.source_id == record.source_id,
                    models.SourceArticleRecord.payload_hash == record.payload_hash,
                )
                .with_for_update()
            )
        if row is None:
            raise RuntimeError("source article identity could not be reserved")

        if row.article_id != article.id:
            raise RuntimeError("source observation resolved to a different article")
        return article, created, _record(row)

    async def insert_or_resolve_article(
        self,
        candidate: domain.NormalizedArticleCandidate,
        cycle_id: UUID,
    ) -> tuple[domain.NormalizedArticle, bool]:
        article_id = uuid4()
        result = await self._require_session().execute(
            insert(models.NormalizedArticle)
            .values(
                id=article_id,
                title=candidate.title,
                summary=candidate.summary,
                canonical_url=candidate.canonical_url,
                canonicalization_version=candidate.canonicalization_version,
                primary_source_id=candidate.source_id,
                published_at=candidate.published_at,
                ingested_at=candidate.ingested_at,
                language_code=candidate.language_code,
                normalized_text=candidate.normalized_text,
                geographic_relevance=list(candidate.geographic_relevance),
                topic_metadata=list(candidate.topic_metadata),
                created_in_cycle_id=cycle_id,
            )
            .on_conflict_do_nothing(index_elements=["canonical_url"])
            .returning(models.NormalizedArticle.id)
        )
        inserted_id = result.scalar_one_or_none()
        row = await self._require_session().scalar(
            select(models.NormalizedArticle).where(
                models.NormalizedArticle.id
                == (inserted_id if inserted_id is not None else article_id)
            )
        )
        if row is None:
            row = await self._require_session().scalar(
                select(models.NormalizedArticle).where(
                    models.NormalizedArticle.canonical_url == candidate.canonical_url
                )
            )
        if row is None:
            raise RuntimeError("canonical article could not be resolved")
        return _article(row), inserted_id is not None

    async def find_duplicate_candidates(
        self,
        candidate: domain.NormalizedArticleCandidate,
        limit: int,
        minimum_similarity: float,
    ) -> tuple[domain.NormalizedArticle, ...]:
        if limit < 1:
            return ()
        if not 0 <= minimum_similarity <= 1:
            raise ValueError("minimum_similarity must be between zero and one")
        session = self._require_session()
        await session.execute(
            select(
                func.set_config(
                    "pg_trgm.similarity_threshold",
                    str(minimum_similarity),
                    True,
                )
            )
        )
        title_similarity = func.similarity(
            models.NormalizedArticle.title, candidate.title
        )
        content_similarity = func.similarity(
            models.NormalizedArticle.normalized_text, candidate.normalized_text
        )
        rows = (
            await session.scalars(
                select(models.NormalizedArticle)
                .where(
                    models.NormalizedArticle.language_code == candidate.language_code,
                    models.NormalizedArticle.canonical_url != candidate.canonical_url,
                    or_(
                        models.NormalizedArticle.title.op("%")(candidate.title),
                        models.NormalizedArticle.normalized_text.op("%")(
                            candidate.normalized_text
                        ),
                    ),
                )
                .order_by(
                    func.greatest(title_similarity, content_similarity).desc(),
                    models.NormalizedArticle.id,
                )
                .limit(limit)
            )
        ).all()
        return tuple(_article(row) for row in rows)

    async def get_articles(
        self, article_ids: tuple[UUID, ...] | list[UUID]
    ) -> tuple[domain.NormalizedArticle, ...]:
        if not article_ids:
            return ()
        rows = (
            await self._require_session().scalars(
                select(models.NormalizedArticle)
                .where(models.NormalizedArticle.id.in_(article_ids))
                .order_by(models.NormalizedArticle.id)
            )
        ).all()
        return tuple(_article(row) for row in rows)

    async def find_event_candidates(
        self,
        article: domain.NormalizedArticle,
        limit: int,
        window_hours: int,
    ) -> tuple[domain.NormalizedArticle, ...]:
        if limit < 1 or window_hours < 1:
            return ()
        event_time = article.published_at or article.ingested_at
        effective_time = func.coalesce(
            models.NormalizedArticle.published_at,
            models.NormalizedArticle.ingested_at,
        )
        rows = (
            await self._require_session().scalars(
                select(models.NormalizedArticle)
                .where(
                    models.NormalizedArticle.id != article.id,
                    models.NormalizedArticle.primary_source_id
                    != article.primary_source_id,
                    models.NormalizedArticle.language_code == article.language_code,
                    effective_time
                    >= event_time - timedelta(hours=window_hours),
                    effective_time
                    <= event_time + timedelta(hours=window_hours),
                )
                .order_by(
                    func.abs(
                        func.extract("epoch", effective_time - event_time)
                    ),
                    models.NormalizedArticle.id,
                )
                .limit(limit)
            )
        ).all()
        return tuple(_article(row) for row in rows)

    async def record_decision(
        self, decision: domain.DeduplicationDecision
    ) -> domain.DeduplicationDecision:
        left_id, right_id = sorted(
            (decision.left_article_id, decision.right_article_id),
            key=lambda value: value.int,
        )
        if left_id == right_id:
            raise ValueError("decision article ids must be distinct")
        decision_id = decision.id
        result = await self._require_session().execute(
            insert(models.DeduplicationDecision)
            .values(
                id=decision.id,
                left_article_id=left_id,
                right_article_id=right_id,
                decision_type=decision.decision_type,
                outcome=decision.outcome,
                title_similarity=decision.title_similarity,
                content_similarity=decision.content_similarity,
                threshold_configuration=dict(decision.threshold_configuration),
                normalization_version=decision.normalization_version,
                evidence=dict(decision.evidence),
                decided_at=decision.decided_at,
            )
            .on_conflict_do_nothing(
                constraint="uq_decisions_pair_type_version"
            )
            .returning(models.DeduplicationDecision.id)
        )
        inserted_id = result.scalar_one_or_none()
        row = await self._require_session().scalar(
            select(models.DeduplicationDecision).where(
                models.DeduplicationDecision.id
                == (inserted_id if inserted_id is not None else decision_id)
            )
        )
        if row is None:
            row = await self._require_session().scalar(
                select(models.DeduplicationDecision).where(
                    models.DeduplicationDecision.left_article_id == left_id,
                    models.DeduplicationDecision.right_article_id == right_id,
                    models.DeduplicationDecision.decision_type
                    == decision.decision_type,
                    models.DeduplicationDecision.normalization_version
                    == decision.normalization_version,
                )
            )
        if row is None:
            raise RuntimeError("deduplication decision could not be resolved")
        return _decision(row)

    async def create_event_group(
        self,
        *,
        representative_article_id: UUID,
        created_at: datetime,
        status: domain.EventGroupStatus,
    ) -> domain.EventGroup:
        row = models.EventGroup(
            id=uuid4(),
            status=status,
            representative_article_id=representative_article_id,
            created_at=created_at,
            updated_at=created_at,
        )
        self._require_session().add(row)
        await self._require_session().flush()
        return _event_group(row)

    async def assign_article_to_event(
        self, article_id: UUID, event_group_id: UUID
    ) -> domain.NormalizedArticle:
        row = await self._require_session().scalar(
            update(models.NormalizedArticle)
            .where(models.NormalizedArticle.id == article_id)
            .values(event_group_id=event_group_id)
            .returning(models.NormalizedArticle)
        )
        if row is None:
            raise RuntimeError("article could not be assigned to event group")
        return _article(row)

    async def store_analysis(
        self, analysis: domain.ArticleAnalysis
    ) -> domain.ArticleAnalysis:
        if not isinstance(analysis, domain.ArticleAnalysis):
            raise TypeError("analysis must be a validated ArticleAnalysis")
        result = await self._require_session().execute(
            insert(models.ArticleAnalysis)
            .values(
                id=analysis.id,
                article_id=analysis.article_id,
                status=analysis.status,
                schema_version=analysis.schema_version,
                analyzer_name=analysis.analyzer_name,
                analyzer_version=analysis.analyzer_version,
                topics=list(analysis.topics),
                countries=list(analysis.countries),
                cities=list(analysis.cities),
                locations=list(analysis.locations),
                people=list(analysis.people),
                organizations=list(analysis.organizations),
                event_type=analysis.event_type,
                importance_score=analysis.importance_score,
                novelty_score=analysis.novelty_score,
                source_quality_score=analysis.source_quality_score,
                semantic_metadata=(
                    dict(analysis.semantic_metadata)
                    if analysis.semantic_metadata is not None
                    else None
                ),
                error_code=analysis.error_code,
                created_at=analysis.created_at,
            )
            .on_conflict_do_nothing(constraint="uq_article_analyses_version")
            .returning(models.ArticleAnalysis.id)
        )
        inserted_id = result.scalar_one_or_none()
        row = await self._require_session().scalar(
            select(models.ArticleAnalysis).where(
                models.ArticleAnalysis.id
                == (inserted_id if inserted_id is not None else analysis.id)
            )
        )
        if row is None:
            row = await self._require_session().scalar(
                select(models.ArticleAnalysis).where(
                    models.ArticleAnalysis.article_id == analysis.article_id,
                    models.ArticleAnalysis.analyzer_name == analysis.analyzer_name,
                    models.ArticleAnalysis.analyzer_version
                    == analysis.analyzer_version,
                    models.ArticleAnalysis.schema_version == analysis.schema_version,
                )
            )
        if row is None:
            raise RuntimeError("article analysis could not be resolved")
        return _analysis(row)

    async def article_ids_created_by_cycle(self, cycle_id: UUID) -> tuple[UUID, ...]:
        return tuple(
            (
                await self._require_session().scalars(
                    select(models.NormalizedArticle.id)
                    .where(models.NormalizedArticle.created_in_cycle_id == cycle_id)
                    .order_by(models.NormalizedArticle.id)
                )
            ).all()
        )

    async def pending_post_processing_article_ids(self) -> tuple[UUID, ...]:
        return tuple(
            (
                await self._require_session().scalars(
                    select(models.NormalizedArticle.id)
                    .where(models.NormalizedArticle.post_processed_at.is_(None))
                    .order_by(
                        models.NormalizedArticle.ingested_at,
                        models.NormalizedArticle.id,
                    )
                )
            ).all()
        )

    async def mark_articles_post_processed(
        self,
        article_ids: tuple[UUID, ...] | list[UUID],
        completed_at: datetime,
    ) -> None:
        if not article_ids:
            return
        await self._require_session().execute(
            update(models.NormalizedArticle)
            .where(models.NormalizedArticle.id.in_(article_ids))
            .values(post_processed_at=completed_at)
        )


NewsRepository = SQLAlchemyNewsRepository
