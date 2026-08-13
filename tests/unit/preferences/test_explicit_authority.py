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
from anxious_news_bot.preferences.schemas import (
    ExplicitPreferenceChangesSchema,
    PreferenceChangesSchema,
)
from anxious_news_bot.preferences.services.apply_changes import (
    DeterministicPreferenceChangeValidator,
)
from anxious_news_bot.preferences.services.authority import derive_effective_authority


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


def _parameter(
    *,
    semantic_key: str = "kirov_city_news",
    name: str = "Kirov city news",
    description: str = "Specific city reporting about Kirov.",
    instructions: str = "Prefer relevant Kirov city reporting.",
    weight: str = "0.40",
    origin: PreferenceOrigin = PreferenceOrigin.QUESTIONNAIRE,
    active: bool = True,
) -> PreferenceParameter:
    now = datetime.now(UTC)
    user_id = uuid4()
    return PreferenceParameter(
        uuid4(),
        user_id,
        semantic_key,
        name,
        description,
        instructions,
        Decimal(weight),
        origin,
        active,
        now,
        now,
    )


def _profile(*parameters: PreferenceParameter) -> ProfileSnapshot:
    return ProfileSnapshot(parameters[0].user_id, 3, parameters)


def _proposal(request_id, change):
    return ExplicitPreferenceChangesSchema.model_validate(
        {
            "schema_version": "1.0",
            "request_id": request_id,
            "base_profile_revision": 3,
            "changes": [change],
        },
        strict=True,
    )


def test_effective_authority_prefers_explicit_evidence_and_falls_back_to_origin() -> (
    None
):
    assert (
        derive_effective_authority(
            PreferenceOrigin.SYSTEM,
            (PreferenceOrigin.QUESTIONNAIRE, PreferenceOrigin.EXPLICIT),
        )
        is PreferenceOrigin.EXPLICIT
    )
    assert (
        derive_effective_authority(PreferenceOrigin.INFERENCE, ())
        is PreferenceOrigin.INFERENCE
    )


def test_specific_explicit_create_is_allowed_when_no_equivalent_exists() -> None:
    broad = _parameter(
        semantic_key="russia_news",
        name="Russia news",
        description="Broad reporting about Russia.",
        instructions="Prefer Russia reporting.",
    )
    request_id = uuid4()
    proposal = _proposal(
        request_id,
        {
            "action": "create",
            "semantic_key": "kirov_city_news",
            "name": "Kirov city news",
            "description": "Specific city reporting about Kirov.",
            "evaluation_instructions": "Prefer relevant Kirov city reporting.",
            "target_weight": "0.80",
            "reason": "User explicitly asked for Kirov city coverage.",
        },
    )

    validated = DeterministicPreferenceChangeValidator().validate(
        proposal,
        ProfileSnapshot(broad.user_id, 3, (broad,)),
        request_id,
        statement="More Kirov city news",
    )

    assert validated.changes[0].action == "create"
    assert validated.changes[0].semantic_key == "kirov_city_news"


@pytest.mark.parametrize(
    "origin",
    [
        PreferenceOrigin.EXPLICIT,
        PreferenceOrigin.QUESTIONNAIRE,
        PreferenceOrigin.INFERENCE,
        PreferenceOrigin.SYSTEM,
    ],
)
@pytest.mark.parametrize("action", ["adjust", "refine", "deactivate", "reactivate"])
def test_explicit_batches_may_target_any_origin_when_semantically_related(
    origin: PreferenceOrigin,
    action: str,
) -> None:
    parameter = _parameter(origin=origin, active=action != "reactivate")
    request_id = uuid4()
    change = {
        "action": action,
        "parameter_id": parameter.id,
        "reason": "User explicitly restated the same Kirov city topic.",
    }
    if action == "adjust":
        change["target_weight"] = "0.80"
    if action == "refine":
        change["description"] = "Specific municipal reporting about Kirov."
    proposal = _proposal(request_id, change)

    validated = DeterministicPreferenceChangeValidator().validate(
        proposal,
        _profile(parameter),
        request_id,
        statement="More Kirov city news",
    )

    assert validated.changes[0].action == action
    assert getattr(validated.changes[0], "parameter_id", parameter.id) == parameter.id


def test_equivalent_create_reuses_inactive_parameter_without_new_creation() -> None:
    parameter = _parameter(active=False)
    request_id = uuid4()
    proposal = _proposal(
        request_id,
        {
            "action": "create",
            "semantic_key": "kirov_city_news",
            "name": "Kirov city news",
            "description": parameter.description,
            "evaluation_instructions": parameter.evaluation_instructions,
            "target_weight": "0.80",
            "reason": "User explicitly requested the same topic again.",
        },
    )

    validated = DeterministicPreferenceChangeValidator().validate(
        proposal,
        _profile(parameter),
        request_id,
        statement="More Kirov city news",
        duplicate_matches={0: parameter.id},
    )

    assert {change.action for change in validated.changes} == {"reactivate", "adjust"}
    assert all(change.action != "create" for change in validated.changes)
    assert {
        getattr(change, "parameter_id", None)
        for change in validated.changes
        if hasattr(change, "parameter_id")
    } == {parameter.id}


def test_broad_only_target_is_rejected_for_narrower_statement() -> None:
    broad = _parameter(
        semantic_key="russia_news",
        name="Russia news",
        description="Broad reporting about Russia.",
        instructions="Prefer Russia reporting.",
    )
    request_id = uuid4()
    proposal = _proposal(
        request_id,
        {
            "action": "adjust",
            "parameter_id": broad.id,
            "target_weight": "0.80",
            "reason": "User explicitly asked for Kirov city coverage.",
        },
    )

    with pytest.raises(PreferenceProposalInvalid, match="specific"):
        DeterministicPreferenceChangeValidator().validate(
            proposal,
            _profile(broad),
            request_id,
            statement="More Kirov city news",
        )


def test_unrelated_explicit_parameter_is_protected() -> None:
    explicit = _parameter(
        semantic_key="moscow_politics",
        name="Moscow politics",
        description="Reporting about Moscow politics.",
        instructions="Prefer Moscow politics reporting.",
        origin=PreferenceOrigin.EXPLICIT,
    )
    request_id = uuid4()
    proposal = _proposal(
        request_id,
        {
            "action": "adjust",
            "parameter_id": explicit.id,
            "target_weight": "0.75",
            "reason": "User explicitly asked for Kirov city coverage.",
        },
    )

    with pytest.raises(PreferenceProposalInvalid, match="unrelated explicit"):
        DeterministicPreferenceChangeValidator().validate(
            proposal,
            _profile(explicit),
            request_id,
            statement="More Kirov city news",
        )


@pytest.mark.parametrize(
    ("parameter", "change"),
    [
        (
            _parameter(),
            lambda parameter: {
                "action": "adjust",
                "parameter_id": parameter.id,
                "target_weight": "0.40",
                "reason": "User explicitly restated the same Kirov city topic.",
            },
        ),
        (
            _parameter(),
            lambda parameter: {
                "action": "refine",
                "parameter_id": parameter.id,
                "name": parameter.name,
                "description": parameter.description,
                "reason": "User explicitly restated the same Kirov city topic.",
            },
        ),
        (
            _parameter(active=False),
            lambda parameter: {
                "action": "deactivate",
                "parameter_id": parameter.id,
                "reason": "User no longer wants this topic.",
            },
        ),
        (
            _parameter(active=True),
            lambda parameter: {
                "action": "reactivate",
                "parameter_id": parameter.id,
                "reason": "User wants this topic again.",
            },
        ),
    ],
)
def test_explicit_noops_are_rejected(parameter, change) -> None:
    profile = _profile(parameter)
    request_id = uuid4()
    proposal = _proposal(request_id, change(parameter))

    with pytest.raises(PreferenceProposalInvalid, match="change"):
        DeterministicPreferenceChangeValidator().validate(
            proposal,
            profile,
            request_id,
            statement="More Kirov city news",
        )


def test_invalid_explicit_change_rejects_whole_batch() -> None:
    kirov = _parameter()
    explicit = _parameter(
        semantic_key="moscow_politics",
        name="Moscow politics",
        description="Reporting about Moscow politics.",
        instructions="Prefer Moscow politics reporting.",
        origin=PreferenceOrigin.EXPLICIT,
    )
    request_id = uuid4()
    proposal = ExplicitPreferenceChangesSchema.model_validate(
        {
            "schema_version": "1.0",
            "request_id": request_id,
            "base_profile_revision": 3,
            "changes": [
                {
                    "action": "adjust",
                    "parameter_id": kirov.id,
                    "target_weight": "0.80",
                    "reason": "User explicitly wants more Kirov city coverage.",
                },
                {
                    "action": "adjust",
                    "parameter_id": explicit.id,
                    "target_weight": "0.70",
                    "reason": "User explicitly wants more Kirov city coverage.",
                },
            ],
        },
        strict=True,
    )

    with pytest.raises(PreferenceProposalInvalid):
        DeterministicPreferenceChangeValidator().validate(
            proposal,
            ProfileSnapshot(kirov.user_id, 3, (kirov, explicit)),
            request_id,
            statement="More Kirov city news",
        )
