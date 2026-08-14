"""Schedule service tests - occurrence resolution and DST."""

from datetime import UTC, date, datetime, time, timezone
from zoneinfo import ZoneInfo

import pytest

from anxious_news_bot.digest.domain import (
    canonical_occurrence_key,
    compute_next_due,
    resolve_occurrence,
)
from anxious_news_bot.digest.services.schedule import DigestScheduleService
from tests.fixtures.digest import FixedClock, make_test_occurrence


class TestOccurrenceResolution:
    def test_utc_resolution(self):
        result = resolve_occurrence(date(2026, 6, 15), time(9, 0), ZoneInfo("UTC"))
        assert result == datetime(2026, 6, 15, 9, 0, tzinfo=timezone.utc)

    def test_timezone_offset(self):
        result = resolve_occurrence(
            date(2026, 6, 15), time(9, 0), ZoneInfo("America/New_York")
        )
        # EDT = UTC-4
        assert result.tzinfo == timezone.utc
        assert result.hour == 13  # 9 AM EDT = 13:00 UTC

    def test_occurrence_key_includes_timezone(self):
        key = canonical_occurrence_key(date(2026, 1, 15), time(9, 0), "Europe/Moscow")
        assert "Europe/Moscow" in key


class TestDSTBehavior:
    def test_spring_forward_gap(self):
        # In US Eastern, 2:00 AM -> 3:00 AM on March 8 2026
        tz = ZoneInfo("America/New_York")
        # 2:30 AM doesn't exist - should advance to valid time
        result = resolve_occurrence(date(2026, 3, 8), time(2, 30), tz)
        # Should produce a valid UTC time
        assert result.tzinfo == timezone.utc

    def test_fall_back_fold(self):
        # In US Eastern, 2:00 AM repeats on Nov 1 2026
        tz = ZoneInfo("America/New_York")
        result = resolve_occurrence(date(2026, 11, 1), time(1, 30), tz)
        # Should choose the earlier (fold=0) instant
        assert result.tzinfo == timezone.utc


class TestNextDue:
    def test_advances_past_current(self):
        tz = ZoneInfo("UTC")
        after = datetime(2026, 1, 15, 10, 0, tzinfo=UTC)
        result = compute_next_due(time(9, 0), tz, after)
        assert result.date() == date(2026, 1, 16)

    def test_same_day_future(self):
        tz = ZoneInfo("UTC")
        after = datetime(2026, 1, 15, 8, 0, tzinfo=UTC)
        result = compute_next_due(time(9, 0), tz, after)
        assert result.date() == date(2026, 1, 15)


class _DueRepository:
    def __init__(self, occurrences):
        self.occurrences = list(occurrences)
        self.batch_sizes = []

    async def claim_due(self, now, batch_size):
        del now
        self.batch_sizes.append(batch_size)
        result = self.occurrences[:batch_size]
        self.occurrences = self.occurrences[batch_size:]
        return tuple(result)


async def test_due_drain_uses_multiple_batches_without_exceeding_tick_maximum():
    repository = _DueRepository([make_test_occurrence() for _ in range(250)])
    service = DigestScheduleService(
        repository,
        FixedClock(),
        claim_batch_size=100,
        max_claims_per_tick=150,
        claim_time_budget_seconds=30,
    )

    claimed = await service.claim_due_batch(datetime.now(UTC))

    assert len(claimed) == 150
    assert repository.batch_sizes == [100, 50]


def test_schedule_service_validates_claim_limits():
    repository = _DueRepository([])
    with pytest.raises(ValueError):
        DigestScheduleService(repository, FixedClock(), claim_batch_size=0)
    with pytest.raises(ValueError):
        DigestScheduleService(
            repository,
            FixedClock(),
            claim_batch_size=100,
            max_claims_per_tick=99,
        )
