"""Deterministic delivery-history filtering before personal evaluation."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from anxious_news_bot.digest.domain import (
    CandidateDecision,
    CandidateFilterDecision,
    CandidateFilterResult,
    MaterialUpdateOutcome,
)
from anxious_news_bot.digest.services.material_updates import (
    MaterialUpdateEvidenceProducer,
    MaterialUpdatePolicy,
)


class DigestHistoryFilter:
    def __init__(
        self,
        repository: object,
        *,
        producer: MaterialUpdateEvidenceProducer | None = None,
        policy: MaterialUpdatePolicy | None = None,
    ) -> None:
        self._repository = repository
        self._producer = producer or MaterialUpdateEvidenceProducer()
        self._policy = policy or MaterialUpdatePolicy(
            version="1.0",
            novelty_threshold=Decimal("0.7000"),
            max_content_similarity=Decimal("0.60000"),
            min_text_chars=200,
        )

    async def filter(
        self, user_id: UUID, candidate_ids: Sequence[UUID], ranking_at: datetime
    ) -> CandidateFilterResult:
        del ranking_at
        ordered_ids = tuple(candidate_ids)
        if not ordered_ids:
            return CandidateFilterResult(eligible_article_ids=(), decisions=())

        delivered_ids = await self._repository.get_user_history_article_ids(
            user_id,
            ordered_ids,
        )
        update_inputs = await self._repository.load_material_update_inputs(
            user_id,
            ordered_ids,
        )
        by_candidate = defaultdict(list)
        for value in update_inputs:
            by_candidate[value.candidate.article_id].append(value)

        eligible: list[UUID] = []
        decisions: list[CandidateFilterDecision] = []
        for article_id in ordered_ids:
            if article_id in delivered_ids:
                decisions.append(
                    CandidateFilterDecision(
                        article_id=article_id,
                        outcome=CandidateDecision.SAME_ARTICLE,
                    )
                )
                continue

            relevant_inputs = by_candidate.get(article_id, ())
            if not relevant_inputs:
                eligible.append(article_id)
                decisions.append(
                    CandidateFilterDecision(
                        article_id=article_id,
                        outcome=CandidateDecision.ELIGIBLE,
                    )
                )
                continue

            material_update = False
            evidence_history_id = None
            analysis_id = None
            for value in relevant_inputs:
                evidence_history_id = value.delivered.history_id
                analysis_id = value.candidate.article_analysis_id
                evidence = await self._repository.load_material_update_evidence(
                    value.delivered.history_id,
                    value.candidate.article_id,
                    self._policy.version,
                )
                if evidence is None:
                    proposed = self._producer.evaluate(
                        delivery_history_id=value.delivered.history_id,
                        prior_article_id=value.delivered.article_id,
                        candidate_article_id=value.candidate.article_id,
                        candidate_analysis_id=value.candidate.article_analysis_id,
                        prior_event_group_id=value.delivered.event_group_id,
                        candidate_event_group_id=value.candidate.event_group_id,
                        prior_published_at=value.delivered.publication_time,
                        candidate_published_at=value.candidate.publication_time,
                        policy=self._policy,
                        prior_normalized_text=value.delivered.normalized_text,
                        candidate_normalized_text=value.candidate.normalized_text,
                        candidate_novelty_score=value.candidate.novelty_score,
                        has_duplicate_or_review_veto=(
                            value.has_duplicate_or_review_veto
                        ),
                    )
                    evidence = await self._repository.save_material_update_evidence(
                        proposed
                    )
                if evidence.outcome is MaterialUpdateOutcome.MATERIAL_UPDATE:
                    material_update = True
                    break

            if material_update:
                eligible.append(article_id)
                outcome = CandidateDecision.ELIGIBLE
            else:
                outcome = CandidateDecision.UNCHANGED_STORY
            decisions.append(
                CandidateFilterDecision(
                    article_id=article_id,
                    outcome=outcome,
                    evidence_history_id=evidence_history_id,
                    analysis_id=analysis_id,
                )
            )

        return CandidateFilterResult(
            eligible_article_ids=tuple(eligible),
            decisions=tuple(decisions),
        )
