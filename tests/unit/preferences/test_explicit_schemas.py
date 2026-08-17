from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest
from pydantic import ValidationError

from anxious_news_bot.preferences.domain import PreferenceOrigin
from anxious_news_bot.preferences.schemas import ExplicitPreferenceChangesSchema


def _proposal(change: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "request_id": uuid4(),
        "base_profile_revision": 3,
        "changes": [change],
    }


@pytest.mark.parametrize(
    "change",
    [
        {
            "action": "create",
            "semantic_key": "kirov_city_news",
            "name": "Kirov city news",
            "description": "Specific reporting about Kirov city.",
            "evaluation_instructions": "Prefer relevant Kirov city reporting.",
            "target_weight": "0.80",
            "reason": "User explicitly requested more Kirov news.",
        },
        {
            "action": "adjust",
            "parameter_id": uuid4(),
            "target_weight": "-0.45",
            "reason": "User wants less of this topic.",
        },
        {
            "action": "refine",
            "parameter_id": uuid4(),
            "name": "Kirov municipal news",
            "reason": "User specified a narrower city scope.",
        },
        {
            "action": "deactivate",
            "parameter_id": uuid4(),
            "reason": "User no longer wants this topic.",
        },
        {
            "action": "reactivate",
            "parameter_id": uuid4(),
            "reason": "User asked to see this topic again.",
        },
    ],
)
def test_accepts_every_explicit_action_and_request_identity(
    change: dict[str, object],
) -> None:
    request_id = uuid4()
    value = ExplicitPreferenceChangesSchema.model_validate(
        {
            "schema_version": "1.0",
            "request_id": request_id,
            "base_profile_revision": 3,
            "changes": [change],
        },
        strict=True,
    )
    assert value.request_id == request_id
    assert value.source is PreferenceOrigin.EXPLICIT
    assert value.source_request_id == request_id


@pytest.mark.parametrize("weight", ["-1.00", "-0.99", "0.00", "0.01", "1.00"])
def test_accepts_canonical_explicit_weights(weight: str) -> None:
    value = ExplicitPreferenceChangesSchema.model_validate(
        _proposal(
            {
                "action": "adjust",
                "parameter_id": uuid4(),
                "target_weight": weight,
                "reason": "Explicitly restated preference.",
            }
        ),
        strict=True,
    )
    assert f"{value.changes[0].weight:.2f}" == weight.replace("-0.00", "0.00")


@pytest.mark.parametrize(
    "weight",
    ["-0.00", "0", "0.1", "0.001", "1e-1", "5.01", "-5.01"],
)
def test_rejects_negative_zero_precision_and_range_violations(weight: str) -> None:
    with pytest.raises(ValidationError):
        ExplicitPreferenceChangesSchema.model_validate(
            _proposal(
                {
                    "action": "create",
                    "semantic_key": "kirov_city_news",
                    "name": "Kirov city news",
                    "description": "Specific reporting about Kirov city.",
                    "evaluation_instructions": "Prefer relevant Kirov city reporting.",
                    "target_weight": weight,
                    "reason": "User explicitly requested more Kirov news.",
                }
            ),
            strict=True,
        )


def test_rejects_duplicate_targets_unknown_fields_and_duplicate_creates() -> None:
    parameter_id = uuid4()
    value = {
        "schema_version": "1.0",
        "request_id": uuid4(),
        "base_profile_revision": 3,
        "changes": [
            {
                "action": "adjust",
                "parameter_id": parameter_id,
                "target_weight": "0.30",
                "reason": "one",
            },
            {
                "action": "deactivate",
                "parameter_id": parameter_id,
                "reason": "two",
            },
        ],
    }
    with pytest.raises(ValidationError):
        ExplicitPreferenceChangesSchema.model_validate(value, strict=True)

    duplicate_create = deepcopy(
        _proposal(
            {
                "action": "create",
                "semantic_key": "kirov_city_news",
                "name": "Kirov city news",
                "description": "Specific reporting about Kirov city.",
                "evaluation_instructions": "Prefer relevant Kirov city reporting.",
                "target_weight": "0.60",
                "reason": "User explicitly requested more Kirov news.",
            }
        )
    )
    duplicate_create["changes"].append(
        {
            "action": "create",
            "semantic_key": "kirov_city_news",
            "name": "Kirov municipal news",
            "description": "Another exact semantic duplicate.",
            "evaluation_instructions": "Prefer city reporting.",
            "target_weight": "0.70",
            "reason": "Still the same concept.",
        }
    )
    with pytest.raises(ValidationError):
        ExplicitPreferenceChangesSchema.model_validate(duplicate_create, strict=True)

    extra = deepcopy(
        _proposal(
            {
                "action": "create",
                "semantic_key": "kirov_city_news",
                "name": "Kirov city news",
                "description": "Specific reporting about Kirov city.",
                "evaluation_instructions": "Prefer relevant Kirov city reporting.",
                "target_weight": "0.60",
                "reason": "User explicitly requested more Kirov news.",
            }
        )
    )
    extra["changes"][0]["effective_authority"] = "explicit"
    with pytest.raises(ValidationError):
        ExplicitPreferenceChangesSchema.model_validate(extra, strict=True)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("request_id", 123),
        ("base_profile_revision", "3"),
        ("changes", {"action": "adjust"}),
    ],
)
def test_rejects_malformed_top_level_types(field: str, value: object) -> None:
    proposal = _proposal(
        {
            "action": "adjust",
            "parameter_id": uuid4(),
            "target_weight": "0.60",
            "reason": "Explicitly requested more coverage.",
        }
    )
    proposal[field] = value
    with pytest.raises(ValidationError):
        ExplicitPreferenceChangesSchema.model_validate(proposal, strict=True)


def test_rejects_malformed_change_types() -> None:
    proposal = _proposal(
        {
            "action": "adjust",
            "parameter_id": str(uuid4()),
            "target_weight": 0.60,
            "reason": ["bad"],
        }
    )
    with pytest.raises(ValidationError):
        ExplicitPreferenceChangesSchema.model_validate(proposal, strict=True)
