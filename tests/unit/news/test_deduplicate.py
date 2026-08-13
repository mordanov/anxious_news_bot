from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from anxious_news_bot.news.domain import (
    DecisionOutcome,
    NormalizedArticle,
    NormalizedArticleCandidate,
)
from anxious_news_bot.news.services.deduplicate import DeterministicArticleDeduplicator

NOW = datetime(2026, 8, 12, 12, tzinfo=UTC)
SOURCE_ID = UUID("00000000-0000-0000-0000-000000000100")
CYCLE_ID = UUID("00000000-0000-0000-0000-000000000200")


def candidate(*, title: str, text: str, url: str = "https://new.example/story"):
    return NormalizedArticleCandidate(
        SOURCE_ID,
        title,
        None,
        url,
        url,
        NOW,
        NOW,
        "en",
        text,
    )


def article(identifier: int, *, title: str, text: str, url: str | None = None):
    return NormalizedArticle(
        UUID(int=identifier),
        title,
        None,
        url or f"https://old.example/{identifier}",
        "1.0",
        SOURCE_ID,
        NOW,
        NOW,
        "en",
        text,
        CYCLE_ID,
    )


def test_exact_canonical_identity_precedes_text_comparison() -> None:
    existing = article(
        2,
        title="Completely unrelated",
        text="Nothing alike",
        url="https://new.example/story",
    )
    result = DeterministicArticleDeduplicator().classify(
        candidate(title="New title", text="New text"), [existing]
    )

    assert result.outcome is DecisionOutcome.DUPLICATE
    assert result.matched_article_id == existing.id
    assert result.evidence["reason"] == "exact_canonical_url"


def test_candidate_order_does_not_change_tie_breaking() -> None:
    first = article(1, title="Same headline", text="Same body")
    second = article(2, title="Same headline", text="Same body")
    deduplicator = DeterministicArticleDeduplicator()
    new = candidate(title="Same headline", text="Same body")

    forward = deduplicator.classify(new, [second, first])
    reverse = deduplicator.classify(new, [first, second])

    assert forward == reverse
    assert forward.matched_article_id == first.id


def test_duplicate_threshold_is_inclusive() -> None:
    deduplicator = DeterministicArticleDeduplicator(
        title_threshold=Decimal("0.50"),
        content_threshold=Decimal("1.00"),
        review_threshold=Decimal("0.40"),
    )
    result = deduplicator.classify(
        candidate(title="ab", text="unrelated"),
        [article(1, title="ac", text="different")],
    )

    assert result.title_similarity == Decimal("0.50000")
    assert result.outcome is DecisionOutcome.DUPLICATE


def test_review_band_is_inclusive_and_preserves_threshold_evidence() -> None:
    deduplicator = DeterministicArticleDeduplicator(
        title_threshold=Decimal("0.80"),
        content_threshold=Decimal("1.00"),
        review_threshold=Decimal("0.50"),
    )
    result = deduplicator.classify(
        candidate(title="ab", text="unrelated"),
        [article(3, title="ac", text="different")],
    )

    assert result.outcome is DecisionOutcome.REVIEW
    assert result.thresholds == {
        "title": "0.80000",
        "content": "1.00000",
        "review": "0.50000",
    }
    assert result.evidence["candidate_order"] == [str(UUID(int=3))]


def test_unrelated_pair_is_distinct() -> None:
    result = DeterministicArticleDeduplicator().classify(
        candidate(title="Markets rally", text="Stocks gained worldwide"),
        [article(5, title="Volcano erupts", text="Residents leave island")],
    )

    assert result.outcome is DecisionOutcome.DISTINCT
    assert result.matched_article_id is None
