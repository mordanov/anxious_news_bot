from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from anxious_news_bot.preferences.domain import (
    PreferenceOrigin,
    PreferenceParameter,
    ProfileSnapshot,
)
from anxious_news_bot.preferences.schemas import CreateChangeSchema
from anxious_news_bot.preferences.services.duplicates import (
    PreferenceDuplicateDetector,
    normalize_semantic_key,
)


class Classifier:
    def __init__(self, candidate_id=None):
        self.candidate_id = candidate_id
        self.calls = 0

    async def classify(self, proposal, candidates):
        del proposal
        self.calls += 1
        return {
            "schema_version": "1.0",
            "outcome": "equivalent" if self.candidate_id else "distinct",
            "candidate_parameter_id": (
                str(self.candidate_id) if self.candidate_id else None
            ),
            "confidence": 0.95,
            "reason": f"Compared {len(candidates.parameters)} candidates",
        }


def _parameter(active=False):
    now = datetime.now(UTC)
    user_id = uuid4()
    return PreferenceParameter(
        uuid4(),
        user_id,
        "local_news",
        "Local News",
        "Local reporting",
        "Prefer local reporting",
        Decimal("0.50"),
        PreferenceOrigin.QUESTIONNAIRE,
        active,
        now,
        now,
    )


def _create(key="local_news", name="Local News"):
    return CreateChangeSchema.model_validate(
        {
            "action": "create",
            "semantic_key": key,
            "name": name,
            "description": "Local reporting",
            "evaluation_instructions": "Prefer local reporting",
            "target_weight": "0.40",
            "reason": "answer",
        },
        strict=True,
    )


async def test_exact_semantic_key_reuses_inactive_parameter_without_model() -> None:
    parameter = _parameter()
    classifier = Classifier()
    result = await PreferenceDuplicateDetector(classifier).resolve(
        _create(), ProfileSnapshot(parameter.user_id, 1, (parameter,))
    )
    assert result.equivalent_parameter_id == parameter.id
    assert classifier.calls == 0


async def test_ambiguous_candidate_uses_read_only_classifier() -> None:
    parameter = _parameter()
    classifier = Classifier(parameter.id)
    result = await PreferenceDuplicateDetector(
        classifier, candidate_threshold=0.40
    ).resolve(
        _create("nearby_news", "Nearby reporting"),
        ProfileSnapshot(parameter.user_id, 1, (parameter,)),
    )
    assert result.equivalent_parameter_id == parameter.id
    assert result.checked_by_model


def test_semantic_key_normalization_is_stable() -> None:
    assert normalize_semantic_key(" Local  NEWS ") == "local-news"
