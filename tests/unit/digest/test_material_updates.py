"""Material update evidence producer tests."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from anxious_news_bot.digest.domain import (
    MaterialUpdateBasis,
    MaterialUpdateOutcome,
)
from anxious_news_bot.digest.services.material_updates import (
    MaterialUpdateEvidenceProducer,
    MaterialUpdatePolicy,
    text_hash,
)


class TestMaterialUpdateProducer:
    def setup_method(self):
        self.producer = MaterialUpdateEvidenceProducer()
        self.policy = MaterialUpdatePolicy(
            version="1.0",
            novelty_threshold=Decimal("0.7000"),
            max_content_similarity=Decimal("0.60000"),
            min_text_chars=200,
        )
        self.prior_article_id = uuid4()
        self.candidate_article_id = uuid4()
        self.event_group_id = uuid4()
        self.prior_published_at = datetime(2026, 1, 1, tzinfo=UTC)

    def _evaluate(self, **overrides):
        values = {
            "delivery_history_id": uuid4(),
            "prior_article_id": self.prior_article_id,
            "candidate_article_id": self.candidate_article_id,
            "candidate_analysis_id": uuid4(),
            "prior_event_group_id": self.event_group_id,
            "candidate_event_group_id": self.event_group_id,
            "prior_published_at": self.prior_published_at,
            "candidate_published_at": self.prior_published_at + timedelta(hours=1),
            "policy": self.policy,
            "prior_normalized_text": "prior source text " * 30,
            "candidate_normalized_text": "candidate development " * 30,
            "candidate_novelty_score": Decimal("0.3000"),
            "has_duplicate_or_review_veto": False,
        }
        values.update(overrides)
        return self.producer.evaluate(**values)

    def test_accepted_novelty(self):
        result = self._evaluate(
            candidate_novelty_score=Decimal("0.8000"),
        )
        assert result.basis == MaterialUpdateBasis.ACCEPTED_NOVELTY
        assert result.outcome == MaterialUpdateOutcome.MATERIAL_UPDATE

    def test_content_delta(self):
        result = self._evaluate(
            prior_normalized_text="unique words in text " * 30,
            candidate_normalized_text="completely different content here " * 30,
        )
        assert result.basis == MaterialUpdateBasis.CONTENT_DELTA
        assert result.outcome == MaterialUpdateOutcome.MATERIAL_UPDATE

    def test_veto_blocks_content_delta(self):
        result = self._evaluate(
            prior_normalized_text="text " * 200,
            candidate_normalized_text="different " * 200,
            has_duplicate_or_review_veto=True,
        )
        assert result.basis == MaterialUpdateBasis.INSUFFICIENT_EVIDENCE
        assert result.outcome == MaterialUpdateOutcome.UNCHANGED

    def test_insufficient_text_length(self):
        result = self._evaluate(
            prior_normalized_text="short",
            candidate_normalized_text="also short",
        )
        assert result.outcome == MaterialUpdateOutcome.UNCHANGED

    def test_hashes_are_deterministic(self):
        h1 = text_hash("hello world")
        h2 = text_hash("hello world")
        assert h1 == h2
        assert len(h1) == 64

    def test_same_article_is_never_a_material_update(self):
        result = self._evaluate(candidate_article_id=self.prior_article_id)

        assert result.basis == MaterialUpdateBasis.INSUFFICIENT_EVIDENCE
        assert result.outcome == MaterialUpdateOutcome.UNCHANGED

    def test_different_event_is_not_a_material_update(self):
        result = self._evaluate(
            candidate_event_group_id=uuid4(),
            candidate_novelty_score=Decimal("0.9999"),
        )

        assert result.outcome == MaterialUpdateOutcome.UNCHANGED

    def test_candidate_must_be_published_later(self):
        result = self._evaluate(
            candidate_published_at=self.prior_published_at,
            candidate_novelty_score=Decimal("0.9999"),
        )

        assert result.outcome == MaterialUpdateOutcome.UNCHANGED

    def test_policy_validates_thresholds_and_version(self):
        with pytest.raises(ValueError):
            MaterialUpdatePolicy(
                version="",
                novelty_threshold=Decimal("0.7000"),
                max_content_similarity=Decimal("0.60000"),
                min_text_chars=200,
            )
