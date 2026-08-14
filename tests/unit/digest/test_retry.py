"""Retry policy tests."""

from datetime import UTC, datetime

import pytest

from anxious_news_bot.digest.domain import RetrySchedule


class TestRetrySchedule:
    def test_first_retry_uses_base(self):
        s = RetrySchedule(base_seconds=60, max_seconds=900, max_attempts=3)
        now = datetime(2026, 1, 1, tzinfo=UTC)
        result = s.next_retry_at(1, now)
        assert (result - now).total_seconds() == 60

    def test_exponential_growth(self):
        s = RetrySchedule(base_seconds=60, max_seconds=900, max_attempts=5)
        now = datetime(2026, 1, 1, tzinfo=UTC)
        delays = []
        for attempt in range(1, 4):
            r = s.next_retry_at(attempt, now)
            delays.append((r - now).total_seconds())
        assert delays == [60, 120, 240]

    def test_capped_at_max(self):
        s = RetrySchedule(base_seconds=60, max_seconds=120, max_attempts=5)
        now = datetime(2026, 1, 1, tzinfo=UTC)
        result = s.next_retry_at(10, now)
        assert (result - now).total_seconds() == 120

    def test_invalid_base_raises(self):
        with pytest.raises(ValueError):
            RetrySchedule(base_seconds=0, max_seconds=60, max_attempts=3)

    def test_max_below_base_raises(self):
        with pytest.raises(ValueError):
            RetrySchedule(base_seconds=120, max_seconds=60, max_attempts=3)
