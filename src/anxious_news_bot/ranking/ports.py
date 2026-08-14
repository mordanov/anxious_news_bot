from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from anxious_news_bot.preferences.domain import ProfileSnapshot
from anxious_news_bot.ranking.domain import (
    ArticleEvaluation,
    ArticleEvaluationIdentity,
    DeliveryArticle,
    RankingArticleSnapshot,
    RankingConfiguration,
    RankingIdentity,
    RankingPreference,
    RankingRecord,
    RankingResult,
    RankingRetentionResult,
    RetentionPolicy,
)
from anxious_news_bot.ranking.schemas import RankingExplanationSchema
from anxious_news_bot.ranking.services.diversify import DiversitySelection


@runtime_checkable
class ArticlePreferenceEvaluator(Protocol):
    async def evaluate(
        self,
        article_snapshot: RankingArticleSnapshot,
        profile_snapshot: ProfileSnapshot,
        evaluation_identity: ArticleEvaluationIdentity,
    ) -> Mapping[str, Any]: ...


@runtime_checkable
class CandidateFilterOutcome(Protocol):
    """Structural result of a generic candidate filter.

    Any object exposing ``eligible_article_ids`` (preserving the input
    candidate order) satisfies this protocol, including richer filter results
    such as the digest module's delivery-history filter outcome.
    """

    eligible_article_ids: Sequence[UUID]


@runtime_checkable
class CandidateFilter(Protocol):
    async def filter(
        self,
        user_id: UUID,
        candidate_ids: Sequence[UUID],
        ranking_at: datetime,
    ) -> CandidateFilterOutcome: ...


@runtime_checkable
class RankingRepository(Protocol):
    async def resolve_user_id(self, telegram_user_id: int) -> UUID | None: ...

    async def resolve_profile_revision(self, user_id: UUID) -> int: ...

    async def prepare_delivery_candidates(
        self,
        *,
        limit: int,
        ranking_at: datetime,
        freshness_horizon_seconds: int,
    ) -> tuple[UUID, ...]: ...

    async def load_delivery_articles(
        self,
        article_ids: Sequence[UUID],
    ) -> tuple[DeliveryArticle, ...]: ...

    async def has_active_nonzero_preferences(self, user_id: UUID) -> bool: ...

    async def claim_evaluation(
        self,
        identity: ArticleEvaluationIdentity,
    ) -> ArticleEvaluation: ...

    async def load_evaluation_context(
        self,
        user_id: UUID,
        article_id: UUID,
    ) -> tuple[
        RankingArticleSnapshot, ProfileSnapshot, tuple[RankingPreference, ...]
    ]: ...

    async def record_attempt(
        self,
        run_id: UUID,
        ordinal: int,
        payload: Mapping[str, Any] | None,
        status: str,
        *,
        error_code: str | None = None,
    ) -> UUID: ...

    async def accept_evaluation(
        self,
        run_id: UUID,
        accepted_attempt_id: UUID | None,
        evaluation: ArticleEvaluation,
    ) -> ArticleEvaluation: ...

    async def fail_evaluation(
        self,
        run_id: UUID,
        status: str,
        *,
        error_code: str | None = None,
    ) -> ArticleEvaluation: ...

    async def load_ranking_snapshot(
        self,
        user_id: UUID,
        candidate_article_ids: Sequence[UUID],
    ) -> tuple[
        int,
        tuple[RankingPreference, ...],
        tuple[RankingArticleSnapshot, ...],
        tuple[ArticleEvaluation, ...],
    ]: ...

    async def find_complete_run(
        self,
        identity: RankingIdentity,
        configuration: RankingConfiguration,
    ) -> RankingResult | None: ...

    async def persist_complete_run(
        self,
        result: RankingResult,
        configuration: RankingConfiguration,
    ) -> RankingResult: ...

    async def mark_stale_or_failed(
        self,
        identity: RankingIdentity,
        configuration: RankingConfiguration,
        status: str,
        *,
        error_code: str | None = None,
    ) -> RankingResult | None: ...


@runtime_checkable
class RankingConfigurationProvider(Protocol):
    def current(self) -> RankingConfiguration: ...


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime: ...


@runtime_checkable
class RankingScorer(Protocol):
    def score(
        self,
        article_snapshot: RankingArticleSnapshot,
        configuration: RankingConfiguration,
        preferences: Sequence[RankingPreference],
        evaluation: ArticleEvaluation | None,
        *,
        ranking_at: datetime,
    ) -> RankingRecord: ...


@runtime_checkable
class DiversitySelector(Protocol):
    def select(
        self,
        records: Sequence[RankingRecord],
        *,
        requested_count: int,
        configuration: RankingConfiguration,
    ) -> DiversitySelection: ...


@runtime_checkable
class RankingExplainer(Protocol):
    def explain(
        self,
        ranking_run_id: UUID,
        record: RankingRecord,
        *,
        configuration_version: str,
        contribution_limit: int,
    ) -> RankingExplanationSchema: ...


@runtime_checkable
class RankingRetentionRepository(Protocol):
    async def cleanup(
        self,
        now: datetime,
        policy: RetentionPolicy,
    ) -> RankingRetentionResult: ...
