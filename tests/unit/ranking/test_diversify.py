from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from anxious_news_bot.preferences.domain import PreferenceOrigin
from anxious_news_bot.ranking.domain import (
    ArticleEvaluation,
    ArticleEvaluationIdentity,
    ArticleParameterRelevance,
    EligibilityReason,
    EvaluationStatus,
    SelectionReason,
)
from anxious_news_bot.ranking.services.diversify import (
    DeterministicDiversitySelector,
    classify_explicit_signals,
)
from anxious_news_bot.ranking.services.score import (
    DeterministicRankingScorer,
    order_records,
    with_initial_positions,
)
from tests.fixtures.ranking import (
    article_snapshot,
    ranking_configuration,
    ranking_preference,
    ranking_record,
)

RANKING_AT = datetime(2026, 1, 1, tzinfo=UTC)


def _uuid(value: int) -> UUID:
    return UUID(f"00000000-0000-0000-0000-{value:012d}")


def _evaluation(
    article,
    preferences,
    relevances: dict[UUID, str],
) -> ArticleEvaluation:
    return ArticleEvaluation(
        run_id=uuid4(),
        identity=ArticleEvaluationIdentity(
            user_id=preferences[0].user_id if preferences else _uuid(999),
            article_id=article.article_id,
            article_analysis_id=article.article_analysis_id,
            profile_revision=3,
            parameter_set_hash="a" * 64,
            schema_version="1.0",
            evaluator_name="test-evaluator",
            evaluator_version="1.0",
            prompt_version="1.0",
        ),
        status=EvaluationStatus.COMPLETE,
        relevances=tuple(
            ArticleParameterRelevance(
                parameter_id=preference.id,
                relevance=Decimal(relevances[preference.id]),
                reason_code="clear_match",
            )
            for preference in preferences
        ),
    )


def _selected_ids(records) -> list[UUID]:
    return [
        record.article_id
        for record in sorted(
            (item for item in records if item.selection.selected),
            key=lambda item: item.selection.position or 0,
        )
    ]


def test_classify_explicit_signals_is_symmetric_and_uses_effective_authority() -> None:
    configuration = ranking_configuration()
    article = article_snapshot(
        article_id=_uuid(100),
        article_analysis_id=_uuid(200),
        source_id=_uuid(300),
        published_at=RANKING_AT,
    )
    positive = ranking_preference(
        parameter_id=_uuid(1),
        user_id=_uuid(10),
        weight="0.75",
        effective_authority=PreferenceOrigin.EXPLICIT,
    )
    negative = ranking_preference(
        parameter_id=_uuid(2),
        user_id=_uuid(10),
        weight="-0.80",
        effective_authority=PreferenceOrigin.EXPLICIT,
    )
    questionnaire = ranking_preference(
        parameter_id=_uuid(3),
        user_id=_uuid(10),
        weight="1.00",
        effective_authority=PreferenceOrigin.QUESTIONNAIRE,
    )
    preferences = (positive, negative, questionnaire)

    protected = classify_explicit_signals(
        configuration,
        preferences,
        _evaluation(
            article,
            preferences,
            {
                positive.id: "0.6000",
                negative.id: "-0.6000",
                questionnaire.id: "1.0000",
            },
        ),
        article_snapshot=article,
    )
    assert protected.protected is True
    assert protected.veto is False

    veto = classify_explicit_signals(
        configuration,
        preferences,
        _evaluation(
            article,
            preferences,
            {
                positive.id: "-0.6000",
                negative.id: "0.6000",
                questionnaire.id: "1.0000",
            },
        ),
        article_snapshot=article,
    )
    assert veto.protected is False
    assert veto.veto is True


def test_selector_gives_protected_records_first_access_and_preserves_input_order() -> (
    None
):
    selector = DeterministicDiversitySelector()
    configuration = replace(
        ranking_configuration(),
        event_cap=10,
        topic_cap=10,
        source_cap=1,
    )
    records = (
        ranking_record(
            article_id=_uuid(101),
            article_analysis_id=_uuid(201),
            source_id=_uuid(301),
            event_group_id=_uuid(401),
            topic_key="local",
            final_score="0.95000000",
            unrounded_score="0.9500000000000000",
            initial_position=1,
        ),
        ranking_record(
            article_id=_uuid(102),
            article_analysis_id=_uuid(202),
            source_id=_uuid(301),
            event_group_id=_uuid(402),
            topic_key="science",
            final_score="0.94000000",
            unrounded_score="0.9400000000000000",
            explicit_protected=True,
            initial_position=2,
        ),
        ranking_record(
            article_id=_uuid(103),
            article_analysis_id=_uuid(203),
            source_id=_uuid(302),
            event_group_id=_uuid(403),
            topic_key="finance",
            final_score="0.93000000",
            unrounded_score="0.9300000000000000",
            initial_position=3,
        ),
        ranking_record(
            article_id=_uuid(104),
            article_analysis_id=_uuid(204),
            source_id=_uuid(303),
            event_group_id=_uuid(404),
            topic_key="culture",
            final_score="0.92000000",
            unrounded_score="0.9200000000000000",
            initial_position=4,
        ),
    )

    selection = selector.select(
        records,
        requested_count=2,
        configuration=configuration,
    )

    assert [record.article_id for record in selection.records] == [
        _uuid(101),
        _uuid(102),
        _uuid(103),
        _uuid(104),
    ]
    assert _selected_ids(selection.records) == [_uuid(102), _uuid(103)]
    assert selection.records[0].selection.reason is SelectionReason.REJECTED_SOURCE_CAP
    assert selection.records[3].selection.reason is SelectionReason.NOT_EVALUATED
    assert selection.selected_cap_vector == (10, 10, 1)
    assert selection.unsatisfied_limits == ()
    assert len(selection.passes) == 1
    assert selection.passes[0].selected_count == 2
    assert selection.passes[0].reached_target is True
    assert (
        selection.passes[0].rejections[0].reason is SelectionReason.REJECTED_SOURCE_CAP
    )
    assert selection.passes[0].rejections[0].count == 1
    assert [
        record.selection.position
        for record in selection.records
        if record.selection.selected
    ] == [1, 2]


def test_selector_restarts_from_original_groups_for_relaxation_vectors() -> None:
    selector = DeterministicDiversitySelector()
    configuration = replace(
        ranking_configuration(),
        event_cap=1,
        topic_cap=1,
        source_cap=1,
        maximum_candidate_count=4,
    )
    records = (
        ranking_record(
            article_id=_uuid(201),
            article_analysis_id=_uuid(301),
            source_id=_uuid(401),
            event_group_id=_uuid(501),
            topic_key="local",
            final_score="0.95000000",
            unrounded_score="0.9500000000000000",
            initial_position=1,
        ),
        ranking_record(
            article_id=_uuid(202),
            article_analysis_id=_uuid(302),
            source_id=_uuid(402),
            event_group_id=_uuid(501),
            topic_key="finance",
            final_score="0.94000000",
            unrounded_score="0.9400000000000000",
            initial_position=2,
        ),
        ranking_record(
            article_id=_uuid(203),
            article_analysis_id=_uuid(303),
            source_id=_uuid(403),
            event_group_id=_uuid(503),
            topic_key="finance",
            final_score="0.93000000",
            unrounded_score="0.9300000000000000",
            initial_position=3,
        ),
        ranking_record(
            article_id=_uuid(204),
            article_analysis_id=_uuid(304),
            source_id=_uuid(401),
            event_group_id=_uuid(504),
            topic_key="science",
            final_score="0.92000000",
            unrounded_score="0.9200000000000000",
            explicit_protected=True,
            initial_position=4,
        ),
    )

    selection = selector.select(
        records,
        requested_count=3,
        configuration=configuration,
    )

    assert [summary.cap_vector for summary in selection.passes] == [
        (1, 1, 1),
        (1, 1, 4),
    ]
    assert [summary.selected_count for summary in selection.passes] == [2, 3]
    first_rejections = {
        rejection.reason: rejection.count
        for rejection in selection.passes[0].rejections
    }
    second_rejections = {
        rejection.reason: rejection.count
        for rejection in selection.passes[1].rejections
    }
    assert first_rejections == {
        SelectionReason.REJECTED_SOURCE_CAP: 1,
        SelectionReason.REJECTED_TOPIC_CAP: 1,
    }
    assert second_rejections == {
        SelectionReason.REJECTED_EVENT_CAP: 1,
    }
    assert _selected_ids(selection.records) == [_uuid(204), _uuid(201), _uuid(203)]
    assert selection.records[1].selection.reason is SelectionReason.REJECTED_EVENT_CAP
    assert selection.records[0].selection.position == 2
    assert selection.records[2].selection.position == 3
    assert selection.records[3].selection.position == 1
    assert selection.records[0].selection.diversity_pass == 2
    assert selection.records[2].selection.diversity_pass == 2
    assert selection.records[3].selection.diversity_pass == 2
    assert selection.selected_cap_vector == (1, 1, 4)
    assert selection.unsatisfied_limits == ("source",)


def test_selector_returns_shortage_when_pool_is_exhausted_without_bypassing_quality() -> (
    None
):
    configuration = ranking_configuration()
    preference = ranking_preference(
        parameter_id=_uuid(1),
        user_id=_uuid(11),
        weight="0.80",
        effective_authority=PreferenceOrigin.EXPLICIT,
    )
    scorer = DeterministicRankingScorer()
    low_quality_article = article_snapshot(
        article_id=_uuid(301),
        article_analysis_id=_uuid(401),
        source_id=_uuid(501),
        source_quality_score=Decimal("0.3000"),
        published_at=RANKING_AT,
    )
    eligible_article = article_snapshot(
        article_id=_uuid(302),
        article_analysis_id=_uuid(402),
        source_id=_uuid(502),
        source_quality_score=Decimal("0.9000"),
        published_at=RANKING_AT,
    )
    low_quality_record = scorer.score(
        low_quality_article,
        configuration,
        (preference,),
        _evaluation(low_quality_article, (preference,), {preference.id: "0.9000"}),
        ranking_at=RANKING_AT,
    )
    eligible_record = scorer.score(
        eligible_article,
        configuration,
        (preference,),
        _evaluation(eligible_article, (preference,), {preference.id: "0.2000"}),
        ranking_at=RANKING_AT,
    )

    ordered = with_initial_positions(
        order_records((low_quality_record, eligible_record))
    )
    selection = DeterministicDiversitySelector().select(
        ordered,
        requested_count=2,
        configuration=configuration,
    )

    assert len(selection.passes) == 1
    assert selection.passes[0].exhausted_pool is True
    assert selection.selected_cap_vector == (
        configuration.event_cap,
        configuration.topic_cap,
        configuration.source_cap,
    )
    assert selection.unsatisfied_limits == ()
    assert selection.records[0].eligible is False
    assert (
        selection.records[0].eligibility_reason
        is EligibilityReason.SOURCE_QUALITY_BELOW_MINIMUM
    )
    assert selection.records[0].explicit_protected is False
    assert selection.records[0].selection.reason is SelectionReason.INELIGIBLE
    assert _selected_ids(selection.records) == [_uuid(302)]
