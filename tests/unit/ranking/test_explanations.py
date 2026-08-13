from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from anxious_news_bot.preferences.domain import PreferenceOrigin
from anxious_news_bot.ranking.domain import (
    ContributionSnapshot,
    EligibilityReason,
    FactorSnapshot,
    PersonalState,
    RankingRecord,
    SelectionOutcome,
    SelectionReason,
)
from anxious_news_bot.ranking.services.explain import DeterministicRankingExplainer


def _uuid(value: int) -> UUID:
    return UUID(f"00000000-0000-0000-0000-{value:012d}")


def _record(*contributions: ContributionSnapshot) -> RankingRecord:
    return RankingRecord(
        article_id=_uuid(100),
        article_analysis_id=_uuid(200),
        source_id=_uuid(300),
        event_group_id=None,
        topic_key="local",
        published_at=datetime(2026, 1, 1, tzinfo=UTC),
        evaluation_run_id=uuid4(),
        personal_state=PersonalState.COMPLETE,
        personal_numerator=Decimal("0.60000000"),
        personal_denominator=Decimal("0.80000000"),
        personal_signed=Decimal("0.75000000"),
        personal_factor=Decimal("0.87500000"),
        factors=FactorSnapshot(
            importance=Decimal("0.80000000"),
            freshness=Decimal("0.75000000"),
            quality=Decimal("0.90000000"),
            novelty=Decimal("0.40000000"),
        ),
        unrounded_score=Decimal("0.8123456789012345"),
        final_score=Decimal("0.81234568"),
        eligible=True,
        eligibility_reason=EligibilityReason.ELIGIBLE,
        explicit_protected=True,
        explicit_veto=False,
        selection=SelectionOutcome(
            selected=True,
            reason=SelectionReason.SELECTED,
            position=1,
            explicit_protected=True,
            diversity_pass=1,
        ),
        contributions=contributions,
        initial_position=1,
    )


def _contribution(
    value: int,
    *,
    name: str,
    origin: PreferenceOrigin,
    authority: PreferenceOrigin,
    weight: str,
    relevance: str,
    contribution: str,
) -> ContributionSnapshot:
    return ContributionSnapshot(
        parameter_id=_uuid(value),
        parameter_name=name,
        origin=origin,
        effective_authority=authority,
        weight=Decimal(weight),
        relevance=Decimal(relevance),
        contribution=Decimal(contribution),
    )


def test_explainer_returns_schema_factors_selection_and_top_absolute_contributions() -> (
    None
):
    explainer = DeterministicRankingExplainer()
    explanation = explainer.explain(
        uuid4(),
        _record(
            _contribution(
                1,
                name="Negative signal",
                origin=PreferenceOrigin.EXPLICIT,
                authority=PreferenceOrigin.EXPLICIT,
                weight="-0.80",
                relevance="0.7500",
                contribution="-0.60000000",
            ),
            _contribution(
                2,
                name="Strong positive signal",
                origin=PreferenceOrigin.QUESTIONNAIRE,
                authority=PreferenceOrigin.EXPLICIT,
                weight="0.80",
                relevance="1.0000",
                contribution="0.80000000",
            ),
            _contribution(
                3,
                name="Smaller signal",
                origin=PreferenceOrigin.SYSTEM,
                authority=PreferenceOrigin.SYSTEM,
                weight="0.50",
                relevance="0.8000",
                contribution="0.40000000",
            ),
        ),
        configuration_version="1.0",
        contribution_limit=2,
    )

    assert explanation.factors.importance == "0.80000000"
    assert explanation.final_score == "0.81234568"
    assert explanation.selection.selected is True
    assert explanation.selection.reason == "selected"
    assert [item.parameter_id for item in explanation.top_contributions] == [
        _uuid(2),
        _uuid(1),
    ]


def test_explainer_breaks_contribution_ties_by_parameter_id_and_preserves_authority() -> (
    None
):
    explainer = DeterministicRankingExplainer()
    explanation = explainer.explain(
        uuid4(),
        _record(
            _contribution(
                20,
                name="Questionnaire preference",
                origin=PreferenceOrigin.QUESTIONNAIRE,
                authority=PreferenceOrigin.EXPLICIT,
                weight="0.50",
                relevance="1.0000",
                contribution="0.50000000",
            ),
            _contribution(
                10,
                name="System preference",
                origin=PreferenceOrigin.SYSTEM,
                authority=PreferenceOrigin.SYSTEM,
                weight="-0.50",
                relevance="1.0000",
                contribution="-0.50000000",
            ),
        ),
        configuration_version="1.0",
        contribution_limit=2,
    )

    assert [item.parameter_id for item in explanation.top_contributions] == [
        _uuid(10),
        _uuid(20),
    ]
    assert explanation.top_contributions[1].origin == PreferenceOrigin.QUESTIONNAIRE
    assert (
        explanation.top_contributions[1].effective_authority
        == PreferenceOrigin.EXPLICIT
    )


def test_explainer_keeps_bounded_names_and_excludes_prompt_or_chain_of_thought_fields() -> (
    None
):
    explainer = DeterministicRankingExplainer()
    explanation = explainer.explain(
        uuid4(),
        _record(
            _contribution(
                30,
                name="x" * 160,
                origin=PreferenceOrigin.EXPLICIT,
                authority=PreferenceOrigin.EXPLICIT,
                weight="0.75",
                relevance="0.9000",
                contribution="0.67500000",
            ),
        ),
        configuration_version="1.0",
        contribution_limit=1,
    )

    payload = explanation.model_dump(mode="json")
    assert payload["top_contributions"][0]["parameter_name"] == "x" * 160
    assert "prompt" not in payload
    assert "chain_of_thought" not in payload
    assert "reasoning" not in payload
