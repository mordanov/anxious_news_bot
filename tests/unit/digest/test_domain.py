"""Domain and schema validation tests."""

from datetime import UTC, date, datetime, time
from decimal import Decimal
from uuid import uuid4

import pytest

from anxious_news_bot.digest.domain import (
    MaterialUpdateBasis,
    MaterialUpdateEvidence,
    MaterialUpdateOutcome,
    RetrySchedule,
    StructuredDigest,
    StructuredDigestItem,
    canonical_occurrence_key,
    compute_next_due,
    resolve_occurrence,
    validate_digest_count,
    validate_hex_digest,
    validate_iana_timezone,
    validate_local_time,
)


class TestDigestCount:
    def test_valid_minimum(self):
        assert validate_digest_count(5) == 5

    def test_valid_maximum(self):
        assert validate_digest_count(20) == 20

    def test_below_minimum_raises(self):
        with pytest.raises(ValueError, match="5"):
            validate_digest_count(4)

    def test_above_maximum_raises(self):
        with pytest.raises(ValueError, match="20"):
            validate_digest_count(21)

    def test_non_integer_raises(self):
        with pytest.raises((ValueError, TypeError)):
            validate_digest_count("10")  # type: ignore

    def test_boolean_is_not_an_integer_count(self):
        with pytest.raises(ValueError):
            validate_digest_count(True)


class TestTimezone:
    def test_valid_utc(self):
        tz = validate_iana_timezone("UTC")
        assert tz is not None

    def test_valid_named(self):
        tz = validate_iana_timezone("America/New_York")
        assert tz is not None

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="invalid"):
            validate_iana_timezone("Not/A/Zone")

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            validate_iana_timezone("")


class TestLocalTime:
    def test_valid(self):
        result = validate_local_time("09:00")
        assert result == time(9, 0)

    def test_invalid_format(self):
        with pytest.raises(ValueError):
            validate_local_time("9am")

    @pytest.mark.parametrize("value", ["9:00", "09:00:00", "09:0", " 09:00 "])
    def test_requires_canonical_minute_format(self, value):
        with pytest.raises(ValueError, match="HH:MM"):
            validate_local_time(value)


class TestOccurrenceKey:
    def test_canonical_format(self):
        key = canonical_occurrence_key(date(2026, 1, 15), time(9, 0), "UTC")
        assert key == "2026-01-15/09:00/UTC"


class TestNextDue:
    def test_future_same_day(self):
        from zoneinfo import ZoneInfo

        after = datetime(2026, 1, 15, 8, 0, tzinfo=UTC)
        result = compute_next_due(time(9, 0), ZoneInfo("UTC"), after)
        assert result == datetime(2026, 1, 15, 9, 0, tzinfo=UTC)

    def test_past_advances_to_next_day(self):
        from zoneinfo import ZoneInfo

        after = datetime(2026, 1, 15, 10, 0, tzinfo=UTC)
        result = compute_next_due(time(9, 0), ZoneInfo("UTC"), after)
        assert result == datetime(2026, 1, 16, 9, 0, tzinfo=UTC)

    def test_requires_aware_after(self):
        from zoneinfo import ZoneInfo

        with pytest.raises(ValueError, match="timezone-aware"):
            compute_next_due(
                time(9, 0),
                ZoneInfo("UTC"),
                datetime(2026, 1, 15, 8, 0),
            )

    def test_missing_local_time_advances_to_first_valid_instant(self):
        from zoneinfo import ZoneInfo

        result = resolve_occurrence(
            date(2026, 3, 8),
            time(2, 30),
            ZoneInfo("America/New_York"),
        )

        assert result == datetime(2026, 3, 8, 7, 0, tzinfo=UTC)

    def test_repeated_local_time_uses_earlier_fold(self):
        from zoneinfo import ZoneInfo

        result = resolve_occurrence(
            date(2026, 11, 1),
            time(1, 30),
            ZoneInfo("America/New_York"),
        )

        assert result == datetime(2026, 11, 1, 5, 30, tzinfo=UTC)


class TestStructuredDigestItem:
    def test_valid_item(self):
        item = StructuredDigestItem(
            position=1,
            article_id=uuid4(),
            article_analysis_id=uuid4(),
            event_group_id=None,
            ranking_run_id=uuid4(),
            title="Title",
            summary="Summary",
            source_name="Source",
            published_at=datetime.now(UTC),
            canonical_url="https://example.com",
            score=Decimal("0.85000000"),
        )
        assert item.position == 1

    def test_invalid_position(self):
        with pytest.raises(ValueError):
            StructuredDigestItem(
                position=0,
                article_id=uuid4(),
                article_analysis_id=uuid4(),
                event_group_id=None,
                ranking_run_id=uuid4(),
                title="T",
                summary="S",
                source_name="Src",
                published_at=datetime.now(UTC),
                canonical_url="https://x.com",
                score=Decimal("0.5"),
            )

    def test_empty_title_raises(self):
        with pytest.raises(ValueError):
            StructuredDigestItem(
                position=1,
                article_id=uuid4(),
                article_analysis_id=uuid4(),
                event_group_id=None,
                ranking_run_id=uuid4(),
                title="",
                summary="S",
                source_name="Src",
                published_at=datetime.now(UTC),
                canonical_url="https://x.com",
                score=Decimal("0.5"),
            )

    def test_naive_publication_time_raises(self):
        with pytest.raises(ValueError, match="timezone-aware"):
            StructuredDigestItem(
                position=1,
                article_id=uuid4(),
                article_analysis_id=uuid4(),
                event_group_id=None,
                ranking_run_id=uuid4(),
                title="T",
                summary="S",
                source_name="Src",
                published_at=datetime(2026, 1, 1),
                canonical_url="https://x.com",
                score=Decimal("0.5"),
            )


class TestStructuredDigest:
    def test_non_contiguous_positions_raises(self):
        items = (
            StructuredDigestItem(
                position=1,
                article_id=uuid4(),
                article_analysis_id=uuid4(),
                event_group_id=None,
                ranking_run_id=uuid4(),
                title="T",
                summary="S",
                source_name="Src",
                published_at=datetime.now(UTC),
                canonical_url="https://x.com",
                score=Decimal("0.5"),
            ),
            StructuredDigestItem(
                position=3,
                article_id=uuid4(),
                article_analysis_id=uuid4(),
                event_group_id=None,
                ranking_run_id=uuid4(),
                title="T",
                summary="S",
                source_name="Src",
                published_at=datetime.now(UTC),
                canonical_url="https://x.com",
                score=Decimal("0.5"),
            ),
        )
        with pytest.raises(ValueError, match="contiguous"):
            StructuredDigest(
                execution_id=uuid4(),
                user_id=uuid4(),
                language="en",
                items=items,
            )


class TestMaterialUpdateEvidence:
    def test_insufficient_evidence_requires_unchanged(self):
        with pytest.raises(ValueError):
            MaterialUpdateEvidence(
                delivery_history_id=uuid4(),
                candidate_article_id=uuid4(),
                candidate_analysis_id=uuid4(),
                event_group_id=uuid4(),
                policy_version="1.0",
                basis=MaterialUpdateBasis.INSUFFICIENT_EVIDENCE,
                outcome=MaterialUpdateOutcome.MATERIAL_UPDATE,
                prior_text_hash="a" * 64,
                candidate_text_hash="b" * 64,
            )

    def test_valid_content_delta(self):
        ev = MaterialUpdateEvidence(
            delivery_history_id=uuid4(),
            candidate_article_id=uuid4(),
            candidate_analysis_id=uuid4(),
            event_group_id=uuid4(),
            policy_version="1.0",
            basis=MaterialUpdateBasis.CONTENT_DELTA,
            outcome=MaterialUpdateOutcome.MATERIAL_UPDATE,
            prior_text_hash="a" * 64,
            candidate_text_hash="b" * 64,
            content_similarity=Decimal("0.45000"),
        )
        assert ev.outcome == MaterialUpdateOutcome.MATERIAL_UPDATE

    def test_content_delta_requires_similarity(self):
        with pytest.raises(ValueError, match="content_similarity"):
            MaterialUpdateEvidence(
                delivery_history_id=uuid4(),
                candidate_article_id=uuid4(),
                candidate_analysis_id=uuid4(),
                event_group_id=uuid4(),
                policy_version="1.0",
                basis=MaterialUpdateBasis.CONTENT_DELTA,
                outcome=MaterialUpdateOutcome.MATERIAL_UPDATE,
                prior_text_hash="a" * 64,
                candidate_text_hash="b" * 64,
            )

    def test_accepted_novelty_requires_novelty_score(self):
        with pytest.raises(ValueError, match="novelty_score"):
            MaterialUpdateEvidence(
                delivery_history_id=uuid4(),
                candidate_article_id=uuid4(),
                candidate_analysis_id=uuid4(),
                event_group_id=uuid4(),
                policy_version="1.0",
                basis=MaterialUpdateBasis.ACCEPTED_NOVELTY,
                outcome=MaterialUpdateOutcome.MATERIAL_UPDATE,
                prior_text_hash="a" * 64,
                candidate_text_hash="b" * 64,
            )


class TestRetrySchedule:
    def test_exponential_backoff(self):
        schedule = RetrySchedule(base_seconds=60, max_seconds=900, max_attempts=3)
        now = datetime(2026, 1, 1, tzinfo=UTC)
        first = schedule.next_retry_at(1, now)
        second = schedule.next_retry_at(2, now)
        assert (first - now).total_seconds() == 60
        assert (second - now).total_seconds() == 120

    def test_capped_at_max(self):
        schedule = RetrySchedule(base_seconds=60, max_seconds=120, max_attempts=5)
        now = datetime(2026, 1, 1, tzinfo=UTC)
        result = schedule.next_retry_at(10, now)
        assert (result - now).total_seconds() == 120

    def test_rejects_non_positive_attempt_count(self):
        schedule = RetrySchedule(base_seconds=60, max_seconds=120, max_attempts=5)

        with pytest.raises(ValueError, match="attempt_count"):
            schedule.next_retry_at(0, datetime(2026, 1, 1, tzinfo=UTC))


class TestHexDigest:
    def test_valid(self):
        assert validate_hex_digest("a" * 64) == "a" * 64

    def test_too_short(self):
        with pytest.raises(ValueError):
            validate_hex_digest("a" * 63)

    def test_uppercase_rejected(self):
        with pytest.raises(ValueError):
            validate_hex_digest("A" * 64)
