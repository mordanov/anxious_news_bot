from __future__ import annotations

from anxious_news_bot.preferences.schemas import (
    CreateChangeSchema,
    ExplicitPreferenceChangesSchema,
)
from anxious_news_bot.preferences.services.apply_changes import (
    DeterministicPreferenceChangeValidator,
)
from tests.fixtures.explicit_preference_cases import (
    REVIEWED_EQUIVALENCE_CASES,
    REVIEWED_SPECIFICITY_CASES,
)


def _proposal(case, request_id):
    return ExplicitPreferenceChangesSchema.model_validate(
        {
            "schema_version": "1.0",
            "request_id": request_id,
            "base_profile_revision": case.profile.revision,
            "changes": [case.proposal_change],
        },
        strict=True,
    )


def _targeted_semantic_keys(profile, validated) -> set[str]:
    parameters = {parameter.id: parameter for parameter in profile.parameters}
    keys: set[str] = set()
    for change in validated.changes:
        if isinstance(change, CreateChangeSchema):
            keys.add(change.semantic_key)
        else:
            keys.add(parameters[change.parameter_id].semantic_key)
    return keys


def test_reviewed_specificity_cases_cover_create_adjust_refine_and_reactivate() -> None:
    slugs = {case.slug for case in REVIEWED_SPECIFICITY_CASES}

    assert {
        "create-specific-over-broad",
        "adjust-existing-specific-alongside-broad",
        "reactivate-inactive-specific-equivalent",
        "refine-existing-system-specific",
        "strengthen-questionnaire-specific",
    } <= slugs


def test_reviewed_specificity_cases_meet_sc001_threshold() -> None:
    validator = DeterministicPreferenceChangeValidator()
    preserved_specificity = 0

    for case in REVIEWED_SPECIFICITY_CASES:
        request_id = case.profile.parameters[0].id
        validated = validator.validate(
            _proposal(case, request_id),
            case.profile,
            request_id,
            statement=case.statement,
            duplicate_matches=dict(case.duplicate_matches),
        )

        assert {change.action for change in validated.changes} == case.expected_actions
        if case.expected_specific_semantic_key in _targeted_semantic_keys(
            case.profile,
            validated,
        ):
            preserved_specificity += 1

    assert preserved_specificity / len(REVIEWED_SPECIFICITY_CASES) == 1.0


def test_reviewed_equivalence_cases_meet_sc002_threshold() -> None:
    validator = DeterministicPreferenceChangeValidator()
    reused_or_refined = 0
    exact_semantic_duplicate_creations = 0

    for case in REVIEWED_EQUIVALENCE_CASES:
        request_id = case.profile.parameters[0].id
        validated = validator.validate(
            _proposal(case, request_id),
            case.profile,
            request_id,
            statement=case.statement,
            duplicate_matches=dict(case.duplicate_matches),
        )

        actions = {change.action for change in validated.changes}
        assert actions == case.expected_actions
        if actions & {"adjust", "refine", "reactivate"} and not any(
            isinstance(change, CreateChangeSchema) for change in validated.changes
        ):
            reused_or_refined += 1
        if case.exact_match:
            exact_semantic_duplicate_creations += sum(
                isinstance(change, CreateChangeSchema) for change in validated.changes
            )

    assert reused_or_refined / len(REVIEWED_EQUIVALENCE_CASES) >= 0.95
    assert exact_semantic_duplicate_creations == 0
