from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from anxious_news_bot.news.domain import DecisionOutcome, NormalizedArticle
from anxious_news_bot.news.services.event_grouping import DeterministicEventGrouper

NOW = datetime(2026, 8, 12, 12, tzinfo=UTC)
CYCLE_ID = UUID("00000000-0000-0000-0000-000000000200")
GROUP_ID = UUID("00000000-0000-0000-0000-000000000300")


def article(
    identifier: int,
    *,
    source: int,
    title: str = "Identical title",
    text: str = "Identical content",
    language: str = "en",
    published_at: datetime | None = NOW,
    ingested_at: datetime = NOW,
    topics: tuple[str, ...] = (),
    geography: tuple[str, ...] = (),
    group_id: UUID | None = GROUP_ID,
) -> NormalizedArticle:
    return NormalizedArticle(
        UUID(int=identifier),
        title,
        None,
        f"https://example.com/{identifier}",
        "1.0",
        UUID(int=source),
        published_at,
        ingested_at,
        language,
        text,
        CYCLE_ID,
        geography,
        topics,
        group_id,
    )


def test_filters_same_source_language_and_more_than_48_hours() -> None:
    current = article(10, source=1, group_id=None)
    candidates = [
        article(1, source=1),
        article(2, source=2, language="es"),
        article(3, source=3, published_at=NOW - timedelta(hours=48, seconds=1)),
        article(4, source=4, published_at=NOW - timedelta(hours=48)),
    ]

    result = DeterministicEventGrouper().group_event(current, candidates)

    assert result.outcome is DecisionOutcome.SAME_EVENT
    assert result.evidence["matched_article_id"] == str(UUID(int=4))
    assert result.evidence["excluded"] == {
        "same_source": 1,
        "language": 1,
        "outside_window": 1,
    }


def test_missing_publication_time_falls_back_to_ingestion_time() -> None:
    current = article(10, source=1, published_at=None, group_id=None)
    match = article(
        2,
        source=2,
        published_at=None,
        ingested_at=NOW - timedelta(hours=47),
    )

    result = DeterministicEventGrouper().group_event(current, [match])

    assert result.outcome is DecisionOutcome.SAME_EVENT
    assert result.evidence["time_basis"] == {
        "article": "ingested_at",
        "candidate": "ingested_at",
    }


def test_weighted_score_and_shared_topic_anchor_are_recorded() -> None:
    current = article(
        10,
        source=1,
        title="ab",
        text="ab",
        topics=("Economy",),
        group_id=None,
    )
    match = article(
        2,
        source=2,
        title="ac",
        text="ac",
        topics=("economy",),
        geography=("Spain",),
    )

    result = DeterministicEventGrouper().group_event(current, [match])

    assert result.score == Decimal("0.50000")
    assert result.outcome is DecisionOutcome.DISTINCT
    assert result.evidence["signals"] == {
        "title_similarity": "0.50000",
        "content_similarity": "0.50000",
        "topic_overlap": "1.00000",
        "geography_overlap": "0.00000",
    }
    assert result.evidence["anchor"]["passed"] is True


def test_title_anchor_055_assignment_062_and_review_052_boundaries() -> None:
    assignment = DeterministicEventGrouper(
        title_weight=Decimal("1"),
        content_weight=Decimal("0"),
        topic_weight=Decimal("0"),
        geography_weight=Decimal("0"),
        anchor_threshold=Decimal("0.55"),
        assignment_threshold=Decimal("0.62"),
        review_threshold=Decimal("0.52"),
    )
    current = article(10, source=1, title="abcdefgh", group_id=None)

    assigned = assignment.group_event(
        current, [article(1, source=2, title="abcdeXYZ")]
    )
    review = assignment.group_event(
        current, [article(2, source=3, title="abcdWXYZ")]
    )

    assert assigned.score == Decimal("0.62500")
    assert assigned.outcome is DecisionOutcome.SAME_EVENT
    assert review.score == Decimal("0.50000")
    assert review.outcome is DecisionOutcome.DISTINCT

    review_policy = DeterministicEventGrouper(
        title_weight=Decimal("1"),
        content_weight=Decimal("0"),
        topic_weight=Decimal("0"),
        geography_weight=Decimal("0"),
        anchor_threshold=Decimal("0.50"),
        assignment_threshold=Decimal("0.62"),
        review_threshold=Decimal("0.50"),
    )
    assert (
        review_policy.group_event(
            current, [article(2, source=3, title="abcdWXYZ")]
        ).outcome
        is DecisionOutcome.REVIEW
    )


def test_exact_default_assignment_and_review_score_boundaries_are_inclusive() -> None:
    current = article(10, source=1, title="same", text="aaaa", group_id=None)
    match = article(1, source=2, title="same", text="bbbb")

    assignment = DeterministicEventGrouper(
        title_weight=Decimal("0.62"),
        content_weight=Decimal("0.38"),
        topic_weight=Decimal("0"),
        geography_weight=Decimal("0"),
    ).group_event(current, [match])
    review = DeterministicEventGrouper(
        title_weight=Decimal("0.52"),
        content_weight=Decimal("0.48"),
        topic_weight=Decimal("0"),
        geography_weight=Decimal("0"),
    ).group_event(current, [match])

    assert assignment.score == Decimal("0.62000")
    assert assignment.outcome is DecisionOutcome.SAME_EVENT
    assert review.score == Decimal("0.52000")
    assert review.outcome is DecisionOutcome.REVIEW


def test_exact_default_title_anchor_boundary_is_inclusive() -> None:
    current = article(
        10,
        source=1,
        title="abcdefghijkXXXXXXXXX",
        text="same",
        group_id=None,
    )
    match = article(
        1,
        source=2,
        title="abcdefghijkYYYYYYYYY",
        text="same",
    )
    result = DeterministicEventGrouper(
        title_weight=Decimal("0"),
        content_weight=Decimal("1"),
        topic_weight=Decimal("0"),
        geography_weight=Decimal("0"),
    ).group_event(current, [match])

    assert result.evidence["signals"]["title_similarity"] == "0.55000"
    assert result.evidence["anchor"]["passed"] is True
    assert result.outcome is DecisionOutcome.SAME_EVENT


def test_anchor_failure_prevents_assignment_even_with_high_weighted_score() -> None:
    grouper = DeterministicEventGrouper(
        title_weight=Decimal("0"),
        content_weight=Decimal("1"),
        topic_weight=Decimal("0"),
        geography_weight=Decimal("0"),
    )
    result = grouper.group_event(
        article(10, source=1, title="x", text="same", group_id=None),
        [article(1, source=2, title="y", text="same")],
    )

    assert result.score == Decimal("1.00000")
    assert result.outcome is DecisionOutcome.DISTINCT
    assert result.evidence["anchor"]["passed"] is False


def test_reassignment_and_source_urls_remain_auditable() -> None:
    old_group = UUID("00000000-0000-0000-0000-000000000999")
    current = article(10, source=1, group_id=old_group)
    match = article(2, source=2, group_id=GROUP_ID)

    result = DeterministicEventGrouper().group_event(current, [match])

    assert result.outcome is DecisionOutcome.SAME_EVENT
    assert result.event_group_id == GROUP_ID
    assert result.evidence["reassignment"] == {
        "from_event_group_id": str(old_group),
        "to_event_group_id": str(GROUP_ID),
    }
    assert result.evidence["source_urls"] == [
        "https://example.com/2",
        "https://example.com/10",
    ]
