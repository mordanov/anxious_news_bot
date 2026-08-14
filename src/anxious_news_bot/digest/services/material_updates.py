"""Versioned deterministic material-update evidence production."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from anxious_news_bot.digest.domain import (
    MaterialUpdateBasis,
    MaterialUpdateEvidence,
    MaterialUpdateOutcome,
)
from anxious_news_bot.news.services.deduplicate import (
    normalize_comparison_text,
    text_similarity,
)


@dataclass(frozen=True, slots=True)
class MaterialUpdatePolicy:
    version: str
    novelty_threshold: Decimal
    max_content_similarity: Decimal
    min_text_chars: int

    def __post_init__(self) -> None:
        if not self.version.strip() or len(self.version) > 100:
            raise ValueError("material-update policy version must be 1..100 characters")
        for name, value in (
            ("novelty_threshold", self.novelty_threshold),
            ("max_content_similarity", self.max_content_similarity),
        ):
            if not value.is_finite() or value < 0 or value > 1:
                raise ValueError(f"{name} must be between zero and one")
        if self.min_text_chars < 1:
            raise ValueError("min_text_chars must be positive")


def canonical_text(value: str) -> str:
    return normalize_comparison_text(value)


def text_hash(text: str) -> str:
    return hashlib.sha256(canonical_text(text).encode("utf-8")).hexdigest()


class MaterialUpdateEvidenceProducer:
    """Apply auditable novelty/content-delta policy without model decisions."""

    def evaluate(
        self,
        *,
        delivery_history_id: UUID,
        prior_article_id: UUID,
        candidate_article_id: UUID,
        candidate_analysis_id: UUID,
        prior_event_group_id: UUID,
        candidate_event_group_id: UUID,
        prior_published_at: datetime,
        candidate_published_at: datetime,
        policy: MaterialUpdatePolicy,
        prior_normalized_text: str,
        candidate_normalized_text: str,
        candidate_novelty_score: Decimal | None,
        has_duplicate_or_review_veto: bool,
    ) -> MaterialUpdateEvidence:
        prior_text = canonical_text(prior_normalized_text)
        candidate_text = canonical_text(candidate_normalized_text)
        prior_hash = hashlib.sha256(prior_text.encode("utf-8")).hexdigest()
        candidate_hash = hashlib.sha256(candidate_text.encode("utf-8")).hexdigest()
        threshold_snapshot = {
            "novelty_threshold": str(policy.novelty_threshold),
            "max_content_similarity": str(policy.max_content_similarity),
            "min_text_chars": policy.min_text_chars,
            "duplicate_review_veto": bool(has_duplicate_or_review_veto),
        }

        def unchanged() -> MaterialUpdateEvidence:
            return MaterialUpdateEvidence(
                delivery_history_id=delivery_history_id,
                candidate_article_id=candidate_article_id,
                candidate_analysis_id=candidate_analysis_id,
                event_group_id=candidate_event_group_id,
                policy_version=policy.version,
                basis=MaterialUpdateBasis.INSUFFICIENT_EVIDENCE,
                outcome=MaterialUpdateOutcome.UNCHANGED,
                prior_text_hash=prior_hash,
                candidate_text_hash=candidate_hash,
                threshold_snapshot=threshold_snapshot,
            )

        if (
            prior_article_id == candidate_article_id
            or prior_event_group_id != candidate_event_group_id
            or candidate_published_at <= prior_published_at
        ):
            return unchanged()

        if (
            candidate_novelty_score is not None
            and candidate_novelty_score >= policy.novelty_threshold
        ):
            return MaterialUpdateEvidence(
                delivery_history_id=delivery_history_id,
                candidate_article_id=candidate_article_id,
                candidate_analysis_id=candidate_analysis_id,
                event_group_id=candidate_event_group_id,
                policy_version=policy.version,
                basis=MaterialUpdateBasis.ACCEPTED_NOVELTY,
                outcome=MaterialUpdateOutcome.MATERIAL_UPDATE,
                prior_text_hash=prior_hash,
                candidate_text_hash=candidate_hash,
                novelty_score=candidate_novelty_score,
                threshold_snapshot=threshold_snapshot,
            )

        if (
            len(prior_text) >= policy.min_text_chars
            and len(candidate_text) >= policy.min_text_chars
            and not has_duplicate_or_review_veto
        ):
            similarity = text_similarity(prior_text, candidate_text)
            if similarity <= policy.max_content_similarity:
                return MaterialUpdateEvidence(
                    delivery_history_id=delivery_history_id,
                    candidate_article_id=candidate_article_id,
                    candidate_analysis_id=candidate_analysis_id,
                    event_group_id=candidate_event_group_id,
                    policy_version=policy.version,
                    basis=MaterialUpdateBasis.CONTENT_DELTA,
                    outcome=MaterialUpdateOutcome.MATERIAL_UPDATE,
                    prior_text_hash=prior_hash,
                    candidate_text_hash=candidate_hash,
                    content_similarity=similarity,
                    threshold_snapshot=threshold_snapshot,
                )
        return unchanged()
