from __future__ import annotations

from decimal import Decimal

from anxious_news_bot.ranking.domain import ArticleEvaluationIdentity
from anxious_news_bot.ranking.services.evaluate import (
    parameter_set_hash,
    validate_evaluation_document,
)
from tests.fixtures.ranking_evaluation_cases import REVIEWED_EVALUATION_CASES


def _identity(case) -> ArticleEvaluationIdentity:
    preferences = tuple(item.preference for item in case.evaluations)
    return ArticleEvaluationIdentity(
        user_id=preferences[0].user_id,
        article_id=case.article_id,
        article_analysis_id=case.article_analysis_id,
        profile_revision=case.profile_revision,
        parameter_set_hash=parameter_set_hash(preferences),
        schema_version="1.0",
        evaluator_name="reviewed-fixtures",
        evaluator_version="1.0",
        prompt_version="prompt-v1",
    )


def _document(case, identity):
    return {
        "schema_version": identity.schema_version,
        "article_id": identity.article_id,
        "article_analysis_id": identity.article_analysis_id,
        "profile_revision": identity.profile_revision,
        "parameter_set_hash": identity.parameter_set_hash,
        "relevances": [
            {
                "parameter_id": item.preference.id,
                "relevance": item.relevance,
                "reason_code": item.reason_code,
            }
            for item in case.evaluations
        ],
    }


def _direction_metric(weight: Decimal, relevance: Decimal) -> Decimal:
    if weight == Decimal("0.00"):
        return Decimal("0.0000")
    sign = Decimal("-1") if weight < 0 else Decimal("1")
    return sign * relevance


def _direction_name(metric: Decimal) -> str:
    if metric > 0:
        return "aligned"
    if metric < 0:
        return "contradiction"
    return "neutral"


def test_reviewed_cases_cover_required_axes() -> None:
    slugs = {case.slug for case in REVIEWED_EVALUATION_CASES}

    assert {
        "matching-positive",
        "neutral-coverage",
        "contradiction-positive",
        "multilingual-russian",
        "broad-vs-specific",
        "negative-weight",
        "zero-weight",
    } <= slugs


def test_reviewed_direction_metrics_match_expected_alignment() -> None:
    for case in REVIEWED_EVALUATION_CASES:
        identity = _identity(case)
        result = validate_evaluation_document(
            _document(case, identity),
            identity,
            tuple(item.preference for item in case.evaluations),
        )
        expectations = {item.preference.id: item for item in case.evaluations}

        for relevance in result.relevances:
            expected = expectations[relevance.parameter_id]
            metric = _direction_metric(expected.preference.weight, relevance.relevance)
            assert f"{metric:.4f}" == expected.expected_metric
            assert _direction_name(metric) == expected.expected_direction


def test_specific_interest_scores_higher_than_broad_interest_when_both_match() -> None:
    case = next(
        item for item in REVIEWED_EVALUATION_CASES if item.slug == "broad-vs-specific"
    )
    identity = _identity(case)
    result = validate_evaluation_document(
        _document(case, identity),
        identity,
        tuple(item.preference for item in case.evaluations),
    )

    broad = next(
        item.relevance
        for item in result.relevances
        if item.parameter_id == case.evaluations[0].preference.id
    )
    specific = next(
        item.relevance
        for item in result.relevances
        if item.parameter_id == case.evaluations[1].preference.id
    )
    assert specific > broad


def test_zero_weight_case_stays_directionally_neutral_despite_nonzero_relevance() -> (
    None
):
    case = next(
        item for item in REVIEWED_EVALUATION_CASES if item.slug == "zero-weight"
    )
    identity = _identity(case)
    result = validate_evaluation_document(
        _document(case, identity),
        identity,
        tuple(item.preference for item in case.evaluations),
    )

    metric = _direction_metric(
        case.evaluations[0].preference.weight,
        result.relevances[0].relevance,
    )
    assert metric == Decimal("0.0000")


def test_multilingual_case_uses_non_ascii_article_text_and_positive_alignment() -> None:
    case = next(
        item
        for item in REVIEWED_EVALUATION_CASES
        if item.slug == "multilingual-russian"
    )
    identity = _identity(case)
    result = validate_evaluation_document(
        _document(case, identity),
        identity,
        tuple(item.preference for item in case.evaluations),
    )

    assert any(ord(character) > 127 for character in case.article_text)
    assert result.relevances[0].relevance > 0
