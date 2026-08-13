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
from anxious_news_bot.preferences.errors import PreferenceProposalInvalid
from anxious_news_bot.preferences.schemas import PreferenceChangesSchema
from anxious_news_bot.preferences.services.apply_changes import (
    DeterministicPreferenceChangeValidator,
)


@pytest.mark.parametrize(
    "origin",
    [
        PreferenceOrigin.EXPLICIT,
        PreferenceOrigin.INFERENCE,
        PreferenceOrigin.SYSTEM,
    ],
)
@pytest.mark.parametrize("action", ["adjust", "refine", "deactivate", "reactivate"])
def test_questionnaire_cannot_mutate_protected_origins(origin, action) -> None:
    now = datetime.now(UTC)
    parameter = PreferenceParameter(
        uuid4(),
        uuid4(),
        "climate_policy",
        "Climate policy",
        "Specific climate policy reporting",
        "Prefer specific policy reporting",
        Decimal("0.40"),
        origin,
        action == "deactivate",
        now,
        now,
    )
    change = {
        "action": action,
        "parameter_id": parameter.id,
        "reason": "questionnaire answer",
    }
    if action == "adjust":
        change["target_weight"] = "0.80"
    if action == "refine":
        change["name"] = "Climate"
    qid = uuid4()
    proposal = PreferenceChangesSchema.model_validate(
        {
            "schema_version": "1.0",
            "questionnaire_id": qid,
            "base_profile_revision": 1,
            "changes": [change],
        },
        strict=True,
    )
    with pytest.raises(PreferenceProposalInvalid):
        DeterministicPreferenceChangeValidator().validate(
            proposal, ProfileSnapshot(parameter.user_id, 1, (parameter,)), qid
        )
