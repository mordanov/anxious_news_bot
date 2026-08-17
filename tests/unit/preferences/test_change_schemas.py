from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest
from pydantic import ValidationError

from anxious_news_bot.preferences.schemas import PreferenceChangesSchema


def _proposal(weight: str = "0.50"):
    return {
        "schema_version": "1.0",
        "questionnaire_id": uuid4(),
        "base_profile_revision": 0,
        "changes": [
            {
                "action": "create",
                "semantic_key": "local_news",
                "name": "Local news",
                "description": "Local reporting",
                "evaluation_instructions": "Prefer relevant local reporting",
                "target_weight": weight,
                "reason": "Selected local coverage",
            }
        ],
    }


@pytest.mark.parametrize("weight", ["-1.00", "-0.99", "0.00", "0.01", "1.00"])
def test_accepts_canonical_decimal_boundaries(weight: str) -> None:
    value = PreferenceChangesSchema.model_validate(_proposal(weight), strict=True)
    assert f"{value.changes[0].weight:.2f}" == weight.replace("-0.00", "0.00")


@pytest.mark.parametrize(
    "weight", ["-0.00", "0", "1", "5.01", "-5.01", "0.1", "0.001", "1e-1"]
)
def test_rejects_noncanonical_or_out_of_range_weights(weight: str) -> None:
    with pytest.raises(ValidationError):
        PreferenceChangesSchema.model_validate(_proposal(weight), strict=True)


def test_rejects_duplicate_targets_and_extra_fields() -> None:
    parameter_id = uuid4()
    value = _proposal()
    value["changes"] = [
        {
            "action": "adjust",
            "parameter_id": parameter_id,
            "target_weight": "0.20",
            "reason": "one",
        },
        {
            "action": "deactivate",
            "parameter_id": parameter_id,
            "reason": "two",
        },
    ]
    with pytest.raises(ValidationError):
        PreferenceChangesSchema.model_validate(value, strict=True)
    extra = deepcopy(_proposal())
    extra["changes"][0]["origin"] = "explicit"
    with pytest.raises(ValidationError):
        PreferenceChangesSchema.model_validate(extra, strict=True)
