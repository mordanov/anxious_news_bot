from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest
from pydantic import ValidationError

from anxious_news_bot.ranking.domain import ArticleEvaluationIdentity
from anxious_news_bot.ranking.errors import EvaluationError
from anxious_news_bot.ranking.services.evaluate import (
    parameter_set_hash,
    validate_evaluation_document,
)
from tests.fixtures.ranking import ranking_preference


def _identity(preferences):
    return ArticleEvaluationIdentity(
        user_id=preferences[0].user_id,
        article_id=uuid4(),
        article_analysis_id=uuid4(),
        profile_revision=3,
        parameter_set_hash=parameter_set_hash(preferences),
        schema_version="1.0",
        evaluator_name="test-evaluator",
        evaluator_version="1.0",
        prompt_version="prompt-v1",
    )


def _document(identity, relevances):
    return {
        "schema_version": identity.schema_version,
        "article_id": identity.article_id,
        "article_analysis_id": identity.article_analysis_id,
        "profile_revision": identity.profile_revision,
        "parameter_set_hash": identity.parameter_set_hash,
        "relevances": list(relevances),
    }


def test_accepts_matching_identity_and_exact_active_parameter_coverage() -> None:
    user_id = uuid4()
    preferences = (
        ranking_preference(
            parameter_id=uuid4(),
            user_id=user_id,
            semantic_key="kirov_city_news",
            name="Kirov city news",
            weight="0.80",
        ),
        ranking_preference(
            parameter_id=uuid4(),
            user_id=user_id,
            semantic_key="budget_policy",
            name="Budget policy",
            weight="-0.45",
        ),
    )
    identity = _identity(preferences)

    result = validate_evaluation_document(
        _document(
            identity,
            (
                {
                    "parameter_id": preferences[0].id,
                    "relevance": "0.8750",
                    "reason_code": "clear_match",
                },
                {
                    "parameter_id": preferences[1].id,
                    "relevance": "-0.6250",
                    "reason_code": "policy_conflict",
                },
            ),
        ),
        identity,
        preferences,
    )

    assert result.identity == identity
    assert result.status.value == "complete"
    assert [item.parameter_id for item in result.relevances] == [
        preferences[0].id,
        preferences[1].id,
    ]


@pytest.mark.parametrize("relevance", ["-1.0000", "0.0000", "0.0001", "1.0000"])
def test_accepts_canonical_four_decimal_relevance_boundaries(relevance: str) -> None:
    preference = ranking_preference(
        parameter_id=uuid4(), user_id=uuid4(), weight="0.60"
    )
    identity = _identity((preference,))

    result = validate_evaluation_document(
        _document(
            identity,
            (
                {
                    "parameter_id": preference.id,
                    "relevance": relevance,
                    "reason_code": "bounded_value",
                },
            ),
        ),
        identity,
        (preference,),
    )

    assert f"{result.relevances[0].relevance:.4f}" == relevance


@pytest.mark.parametrize(
    "relevance",
    ["-0.0000", "0", "0.1", "0.00001", "1.0001", "-1.0001"],
)
def test_rejects_negative_zero_precision_and_range_violations(relevance: str) -> None:
    preference = ranking_preference(
        parameter_id=uuid4(), user_id=uuid4(), weight="0.60"
    )
    identity = _identity((preference,))

    with pytest.raises(ValidationError):
        validate_evaluation_document(
            _document(
                identity,
                (
                    {
                        "parameter_id": preference.id,
                        "relevance": relevance,
                        "reason_code": "bounded_value",
                    },
                ),
            ),
            identity,
            (preference,),
        )


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda identity, preferences, raw: raw["relevances"].append(
                {
                    "parameter_id": preferences[0].id,
                    "relevance": "0.1000",
                    "reason_code": "duplicate_parameter",
                }
            ),
            "duplicate parameter ids",
        ),
        (
            lambda identity, preferences, raw: raw["relevances"].append(
                {
                    "parameter_id": uuid4(),
                    "relevance": "0.1000",
                    "reason_code": "unknown_parameter",
                }
            ),
            "exactly once",
        ),
        (
            lambda identity, preferences, raw: raw["relevances"].pop(),
            "exactly once",
        ),
    ],
)
def test_rejects_duplicate_unknown_and_missing_parameter_coverage(
    mutator, message: str
) -> None:
    preferences = (
        ranking_preference(parameter_id=uuid4(), user_id=uuid4(), weight="0.70"),
        ranking_preference(
            parameter_id=uuid4(),
            user_id=uuid4(),
            semantic_key="regional_budget",
            name="Regional budget",
            weight="0.50",
        ),
    )
    identity = _identity(preferences)
    raw = _document(
        identity,
        (
            {
                "parameter_id": preferences[0].id,
                "relevance": "0.7500",
                "reason_code": "clear_match",
            },
            {
                "parameter_id": preferences[1].id,
                "relevance": "0.2500",
                "reason_code": "partial_match",
            },
        ),
    )

    mutator(identity, preferences, raw)

    with pytest.raises(EvaluationError, match=message):
        validate_evaluation_document(raw, identity, preferences)


@pytest.mark.parametrize(
    "field",
    ["article_id", "article_analysis_id", "profile_revision", "parameter_set_hash"],
)
def test_rejects_identity_mismatches(field: str) -> None:
    preference = ranking_preference(
        parameter_id=uuid4(), user_id=uuid4(), weight="0.60"
    )
    identity = _identity((preference,))
    raw = _document(
        identity,
        (
            {
                "parameter_id": preference.id,
                "relevance": "0.5000",
                "reason_code": "clear_match",
            },
        ),
    )
    if field == "parameter_set_hash":
        raw[field] = "f" * 64
    else:
        raw[field] = uuid4() if field != "profile_revision" else 99

    with pytest.raises(EvaluationError, match="identity"):
        validate_evaluation_document(raw, identity, (preference,))


@pytest.mark.parametrize("reason_code", ["No", "bad reason", "BadReason", "ok!"])
def test_rejects_invalid_reason_codes(reason_code: str) -> None:
    preference = ranking_preference(
        parameter_id=uuid4(), user_id=uuid4(), weight="0.60"
    )
    identity = _identity((preference,))

    with pytest.raises(ValidationError):
        validate_evaluation_document(
            _document(
                identity,
                (
                    {
                        "parameter_id": preference.id,
                        "relevance": "0.5000",
                        "reason_code": reason_code,
                    },
                ),
            ),
            identity,
            (preference,),
        )


def test_rejects_extra_fields() -> None:
    preference = ranking_preference(
        parameter_id=uuid4(), user_id=uuid4(), weight="0.60"
    )
    identity = _identity((preference,))
    raw = _document(
        identity,
        (
            {
                "parameter_id": preference.id,
                "relevance": "0.5000",
                "reason_code": "clear_match",
            },
        ),
    )

    top_level = deepcopy(raw)
    top_level["prompt"] = "leaked"
    with pytest.raises(ValidationError):
        validate_evaluation_document(top_level, identity, (preference,))

    nested = deepcopy(raw)
    nested["relevances"][0]["raw_response"] = {"oops": True}
    with pytest.raises(ValidationError):
        validate_evaluation_document(nested, identity, (preference,))
