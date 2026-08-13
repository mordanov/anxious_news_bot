from __future__ import annotations

from datetime import UTC, datetime

from anxious_news_bot.preferences.domain import RetentionResult
from anxious_news_bot.preferences.services.retention import PreferenceRetentionService
from tests.fixtures.preferences import FixedClock


class Repository:
    def __init__(self):
        self.arguments = None

    async def compact_retention(self, **kwargs):
        self.arguments = kwargs
        return RetentionResult(full_history_rows_removed=2)


async def test_zero_history_retention_disables_history_cleanup() -> None:
    repository = Repository()
    service = PreferenceRetentionService(
        repository,
        FixedClock(),
        questionnaire_days=365,
        history_days=0,
        batch_size=50,
    )
    result = await service.run_once()
    assert result.full_history_rows_removed == 2
    assert repository.arguments["history_cutoff"] is None
    assert repository.arguments["questionnaire_cutoff"] == datetime(
        2025, 1, 1, tzinfo=UTC
    )
    assert repository.arguments["batch_size"] == 50
