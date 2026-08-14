"""Retention service tests."""

import pytest

from anxious_news_bot.digest.services.retention import DigestRetentionService
from tests.fixtures.digest import FixedClock


class FakeRetentionRepo:
    def __init__(self):
        self.deleted_count = 0
        self.detail_count = 0
        self.cutoffs = []

    async def delete_expired_history(self, before, batch_size):
        self.cutoffs.append(before)
        self.deleted_count += batch_size
        return batch_size

    async def delete_expired_details(self, before, batch_size):
        self.cutoffs.append(before)
        self.detail_count += 2
        return 2


class TestRetentionService:
    @pytest.mark.asyncio
    async def test_cleanup_deletes(self):
        repo = FakeRetentionRepo()
        clock = FixedClock()
        service = DigestRetentionService(
            repo, clock, history_retention_days=30, batch_size=100
        )
        result = await service.run_cleanup()
        assert result == 102
        assert repo.cutoffs[0] == repo.cutoffs[1]

    def test_rejects_invalid_retention_configuration(self):
        with pytest.raises(ValueError):
            DigestRetentionService(
                FakeRetentionRepo(),
                FixedClock(),
                history_retention_days=0,
            )
