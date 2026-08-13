from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from anxious_news_bot.ranking.domain import (
    ArticleEvaluation,
    RankingArticleSnapshot,
    RankingIdentity,
    RankingRecord,
    RankingResult,
    RankingStatus,
)
from anxious_news_bot.ranking.errors import RankingRunError, StaleSnapshotError
from anxious_news_bot.ranking.observability import (
    log_diversity_cap_rejection,
    log_diversity_completion,
    log_diversity_protection,
    log_diversity_relaxation,
    log_diversity_selection,
    log_diversity_shortage,
    log_diversity_veto,
)
from anxious_news_bot.ranking.ports import (
    Clock,
    DiversitySelector,
    RankingConfigurationProvider,
    RankingRepository,
    RankingScorer,
)
from anxious_news_bot.ranking.services.diversify import (
    DeterministicDiversitySelector,
    DiversitySelection,
)
from anxious_news_bot.ranking.services.score import (
    order_records,
    with_initial_positions,
)


def _decimal_text(value: Decimal | None, places: int) -> str | None:
    if value is None:
        return None
    return f"{value:.{places}f}"


def _json_hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode()
    ).hexdigest()


def _selected_records(records: tuple[RankingRecord, ...]) -> tuple[RankingRecord, ...]:
    return tuple(
        sorted(
            (record for record in records if record.selection.selected),
            key=lambda item: item.selection.position or 0,
        )
    )


def candidate_snapshot_hash(
    articles: tuple[RankingArticleSnapshot, ...],
    evaluations: tuple[ArticleEvaluation, ...],
) -> str:
    evaluations_by_article = {
        evaluation.identity.article_id: evaluation for evaluation in evaluations
    }
    payload = [
        {
            "article_id": str(article.article_id),
            "article_analysis_id": str(article.article_analysis_id)
            if article.article_analysis_id is not None
            else None,
            "source_id": str(article.source_id),
            "event_group_id": str(article.event_group_id)
            if article.event_group_id is not None
            else None,
            "topic_key": article.topic_key,
            "published_at": article.published_at.isoformat()
            if article.published_at is not None
            else None,
            "importance_score": _decimal_text(article.importance_score, 4),
            "novelty_score": _decimal_text(article.novelty_score, 4),
            "source_quality_score": _decimal_text(article.source_quality_score, 4),
            "duplicate_outcome": article.duplicate_outcome.value
            if article.duplicate_outcome is not None
            else None,
            "evaluation": (
                {
                    "run_id": str(evaluation.run_id),
                    "status": evaluation.status.value,
                    "article_analysis_id": str(evaluation.identity.article_analysis_id),
                    "profile_revision": evaluation.identity.profile_revision,
                    "parameter_set_hash": evaluation.identity.parameter_set_hash,
                }
                if (evaluation := evaluations_by_article.get(article.article_id))
                is not None
                else None
            ),
        }
        for article in sorted(articles, key=lambda item: item.article_id.int)
    ]
    return _json_hash(payload)


class PersonalRankingService:
    def __init__(
        self,
        repository: RankingRepository,
        configuration_provider: RankingConfigurationProvider,
        scorer: RankingScorer,
        clock: Clock,
        selector: DiversitySelector | None = None,
    ) -> None:
        self._repository = repository
        self._configuration_provider = configuration_provider
        self._scorer = scorer
        self._clock = clock
        self._selector = selector or DeterministicDiversitySelector()

    async def rank(
        self,
        user_id: UUID,
        request_id: str,
        candidate_article_ids: tuple[UUID, ...] | list[UUID],
        *,
        requested_count: int,
        ranking_at: datetime | None = None,
    ) -> RankingResult:
        configuration = self._configuration_provider.current()
        candidate_ids = tuple(candidate_article_ids)
        if len(candidate_ids) > configuration.maximum_candidate_count:
            raise RankingRunError(
                "candidate count exceeds maximum candidate count",
                code="candidate_count_exceeded",
            )
        if requested_count > configuration.maximum_candidate_count:
            raise RankingRunError(
                "requested count exceeds maximum candidate count",
                code="requested_count_exceeded",
            )
        if len(set(candidate_ids)) != len(candidate_ids):
            raise RankingRunError(
                "candidate article ids must be unique",
                code="duplicate_candidate_ids",
            )

        ranking_time = ranking_at or self._clock.now()
        (
            profile_revision,
            preferences,
            articles,
            evaluations,
        ) = await self._repository.load_ranking_snapshot(
            user_id,
            candidate_ids,
        )
        identity = RankingIdentity(
            request_id=request_id,
            user_id=user_id,
            profile_revision=profile_revision,
            candidate_set_hash=candidate_snapshot_hash(articles, evaluations),
            configuration_version=configuration.version,
            ranking_at=ranking_time,
            requested_count=requested_count,
        )
        replay = await self._repository.find_complete_run(identity, configuration)
        if replay is not None:
            return replay

        evaluation_map = {
            evaluation.identity.article_id: evaluation for evaluation in evaluations
        }
        ordered_records = with_initial_positions(
            order_records(
                tuple(
                    self._scorer.score(
                        article,
                        configuration,
                        preferences,
                        evaluation_map.get(article.article_id),
                        ranking_at=ranking_time,
                    )
                    for article in articles
                )
            )
        )
        diversity = self._selector.select(
            ordered_records,
            requested_count=requested_count,
            configuration=configuration,
        )
        self._log_diversity(identity, diversity)

        selected_records = _selected_records(diversity.records)
        result = RankingResult(
            ranking_run_id=uuid4(),
            identity=identity,
            status=RankingStatus.COMPLETE,
            records=diversity.records,
            selected_count=len(selected_records),
            excluded_count=len(diversity.records) - len(selected_records),
            selected_cap_vector=diversity.selected_cap_vector,
            unsatisfied_limits=diversity.unsatisfied_limits,
            completed_at=self._clock.now(),
        )
        try:
            persisted = await self._repository.persist_complete_run(
                result, configuration
            )
        except StaleSnapshotError as exc:
            stale = await self._repository.mark_stale_or_failed(
                identity,
                configuration,
                RankingStatus.STALE.value,
                error_code=exc.code,
            )
            if stale is None:
                raise
            log_diversity_completion(
                user_id=identity.user_id,
                request_id=identity.request_id,
                ranking_run_id=stale.ranking_run_id,
                status=stale.status.value,
                selected_count=stale.selected_count,
                excluded_count=stale.excluded_count,
                cap_vector=stale.selected_cap_vector,
                unsatisfied_limits=stale.unsatisfied_limits,
            )
            return stale

        log_diversity_completion(
            user_id=identity.user_id,
            request_id=identity.request_id,
            ranking_run_id=persisted.ranking_run_id,
            status=persisted.status.value,
            selected_count=persisted.selected_count,
            excluded_count=persisted.excluded_count,
            cap_vector=persisted.selected_cap_vector,
            unsatisfied_limits=persisted.unsatisfied_limits,
        )
        return persisted

    @staticmethod
    def _log_diversity(
        identity: RankingIdentity,
        diversity: DiversitySelection,
    ) -> None:
        protected_ids = tuple(
            record.article_id
            for record in diversity.records
            if record.eligible and record.explicit_protected
        )
        if protected_ids:
            log_diversity_protection(
                user_id=identity.user_id,
                request_id=identity.request_id,
                protected_count=len(protected_ids),
                article_ids=protected_ids,
            )

        vetoed_ids = tuple(
            record.article_id for record in diversity.records if record.explicit_veto
        )
        if vetoed_ids:
            log_diversity_veto(
                user_id=identity.user_id,
                request_id=identity.request_id,
                vetoed_count=len(vetoed_ids),
                article_ids=vetoed_ids,
            )

        for index, summary in enumerate(diversity.passes):
            for rejection in summary.rejections:
                log_diversity_cap_rejection(
                    user_id=identity.user_id,
                    request_id=identity.request_id,
                    pass_number=summary.pass_number,
                    cap_vector=summary.cap_vector,
                    reason=rejection.reason.value,
                    rejected_count=rejection.count,
                    article_ids=rejection.sample_article_ids,
                )
            if index + 1 < len(diversity.passes):
                next_summary = diversity.passes[index + 1]
                log_diversity_relaxation(
                    user_id=identity.user_id,
                    request_id=identity.request_id,
                    from_pass=summary.pass_number,
                    from_vector=summary.cap_vector,
                    to_pass=next_summary.pass_number,
                    to_vector=next_summary.cap_vector,
                    selected_count=summary.selected_count,
                    requested_count=identity.requested_count,
                )

        selected_records = _selected_records(diversity.records)
        selected_ids = tuple(record.article_id for record in selected_records)
        if len(selected_ids) < identity.requested_count:
            log_diversity_shortage(
                user_id=identity.user_id,
                request_id=identity.request_id,
                pass_number=diversity.selected_pass,
                cap_vector=diversity.selected_cap_vector,
                selected_count=len(selected_ids),
                requested_count=identity.requested_count,
                unsatisfied_limits=diversity.unsatisfied_limits,
            )
        log_diversity_selection(
            user_id=identity.user_id,
            request_id=identity.request_id,
            pass_number=diversity.selected_pass,
            cap_vector=diversity.selected_cap_vector,
            selected_count=len(selected_ids),
            requested_count=identity.requested_count,
            article_ids=selected_ids,
            unsatisfied_limits=diversity.unsatisfied_limits,
        )


__all__ = [
    "PersonalRankingService",
    "candidate_snapshot_hash",
]
