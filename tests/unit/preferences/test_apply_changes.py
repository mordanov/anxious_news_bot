from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from anxious_news_bot.preferences.domain import (
    PreferenceOrigin,
    PreferenceParameter,
    ProfileSnapshot,
)
from anxious_news_bot.preferences.schemas import PreferenceChangesSchema
from anxious_news_bot.preferences.services.apply_changes import (
    DeterministicPreferenceChangeValidator,
    proposal_hash,
)


def _parameter(origin=PreferenceOrigin.QUESTIONNAIRE, *, active=True):
    now = datetime.now(UTC)
    return PreferenceParameter(
        id=uuid4(),
        user_id=uuid4(),
        semantic_key="local_news",
        name="Local news",
        description="Local reporting",
        evaluation_instructions="Prefer local reporting",
        weight=Decimal("0.50"),
        origin=origin,
        active=active,
        created_at=now,
        updated_at=now,
    )


def _proposal(questionnaire_id, revision, change):
    return PreferenceChangesSchema.model_validate(
        {
            "schema_version": "1.0",
            "questionnaire_id": questionnaire_id,
            "base_profile_revision": revision,
            "changes": [change],
        },
        strict=True,
    )


def test_proposal_hash_is_stable() -> None:
    qid = uuid4()
    proposal = _proposal(
        qid,
        2,
        {
            "action": "create",
            "semantic_key": "science_news",
            "name": "Science",
            "description": "Science reporting",
            "evaluation_instructions": "Prefer science reporting",
            "target_weight": "0.60",
            "reason": "answer evidence",
        },
    )
    assert proposal_hash(proposal) == proposal_hash(proposal)
    assert len(proposal_hash(proposal)) == 64


@pytest.mark.parametrize(
    "change",
    [
        lambda parameter: {
            "action": "adjust",
            "parameter_id": parameter.id,
            "target_weight": "0.50",
            "reason": "same",
        },
        lambda parameter: {
            "action": "refine",
            "parameter_id": parameter.id,
            "name": parameter.name,
            "reason": "same",
        },
        lambda parameter: {
            "action": "reactivate",
            "parameter_id": parameter.id,
            "reason": "already active",
        },
    ],
)
def test_filters_unchanged_questionnaire_actions(change) -> None:
    parameter = _parameter()
    qid = uuid4()
    profile = ProfileSnapshot(parameter.user_id, 1, (parameter,))
    result = DeterministicPreferenceChangeValidator().validate(
        _proposal(qid, 1, change(parameter)), profile, qid
    )
    assert len(result.changes) == 0
