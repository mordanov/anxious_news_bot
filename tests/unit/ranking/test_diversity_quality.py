from __future__ import annotations

from collections import Counter
from decimal import Decimal
from uuid import UUID

from anxious_news_bot.ranking.services.diversify import DeterministicDiversitySelector
from tests.fixtures.ranking_diversity_cases import REVIEWED_DIVERSITY_CASES


def _selected_ids(records) -> tuple[UUID, ...]:
    return tuple(
        record.article_id
        for record in sorted(
            (item for item in records if item.selection.selected),
            key=lambda item: item.selection.position or 0,
        )
    )


def _counts(records):
    selected = [record for record in records if record.selection.selected]
    return (
        Counter(
            record.event_group_id
            for record in selected
            if record.event_group_id is not None
        ),
        Counter(
            record.topic_key for record in selected if record.topic_key is not None
        ),
        Counter(record.source_id for record in selected),
    )


def test_reviewed_diversity_cases_cover_required_axes() -> None:
    slugs = {case.slug for case in REVIEWED_DIVERSITY_CASES}

    assert {"balanced-repeats", "protected-source-relaxation"} <= slugs


def test_reviewed_cases_meet_cap_satisfaction_metric() -> None:
    selector = DeterministicDiversitySelector()
    satisfied = 0
    measured = 0

    for case in REVIEWED_DIVERSITY_CASES:
        if not case.sufficient_alternatives:
            continue
        measured += 1
        selection = selector.select(
            case.records,
            requested_count=case.requested_count,
            configuration=case.configuration,
        )
        event_counts, topic_counts, source_counts = _counts(selection.records)
        if (
            selection.unsatisfied_limits == case.expected_unsatisfied_limits == ()
            and max(event_counts.values(), default=0) <= case.configuration.event_cap
            and max(topic_counts.values(), default=0) <= case.configuration.topic_cap
            and max(source_counts.values(), default=0) <= case.configuration.source_cap
        ):
            satisfied += 1

    assert measured > 0
    rate = Decimal(satisfied) / Decimal(measured)
    assert rate == Decimal("1")


def test_reviewed_cases_meet_explicit_protection_metric_and_expected_selection() -> (
    None
):
    selector = DeterministicDiversitySelector()
    protected_total = 0
    protected_selected = 0

    for case in REVIEWED_DIVERSITY_CASES:
        selection = selector.select(
            case.records,
            requested_count=case.requested_count,
            configuration=case.configuration,
        )

        assert _selected_ids(selection.records) == case.expected_selected_ids
        assert selection.selected_cap_vector == case.expected_selected_cap_vector
        assert selection.unsatisfied_limits == case.expected_unsatisfied_limits

        selected_ids = set(_selected_ids(selection.records))
        protected_total += len(case.protected_article_ids)
        protected_selected += sum(
            1 for article_id in case.protected_article_ids if article_id in selected_ids
        )

    assert protected_total > 0
    protection_rate = Decimal(protected_selected) / Decimal(protected_total)
    assert protection_rate == Decimal("1")
