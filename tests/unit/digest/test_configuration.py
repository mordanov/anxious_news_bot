"""Configuration service tests."""

import pytest

from anxious_news_bot.digest.services.configuration import DigestConfigurationService
from tests.fixtures.digest import FakeDigestConfigurationRepository, FixedClock


class TestDigestConfigurationService:
    @pytest.mark.asyncio
    async def test_valid_count(self):
        repo = FakeDigestConfigurationRepository()
        clock = FixedClock()
        service = DigestConfigurationService(repo, clock)
        result = await service.set_count(
            telegram_user_id=123, language_hint="en", count=10
        )
        assert result.digest_count == 10

    @pytest.mark.asyncio
    async def test_below_minimum_raises(self):
        repo = FakeDigestConfigurationRepository()
        clock = FixedClock()
        service = DigestConfigurationService(repo, clock)
        with pytest.raises(ValueError):
            await service.set_count(telegram_user_id=123, language_hint="en", count=4)

    @pytest.mark.asyncio
    async def test_above_maximum_raises(self):
        repo = FakeDigestConfigurationRepository()
        clock = FixedClock()
        service = DigestConfigurationService(repo, clock)
        with pytest.raises(ValueError):
            await service.set_count(telegram_user_id=123, language_hint="en", count=21)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("value", [5, 20])
    async def test_inclusive_boundaries_delegate_with_fixed_timestamp(self, value):
        repo = FakeDigestConfigurationRepository()
        clock = FixedClock()
        service = DigestConfigurationService(repo, clock)

        result = await service.set_count(
            telegram_user_id=123,
            language_hint="es",
            count=value,
        )

        assert result.digest_count == value

    @pytest.mark.asyncio
    async def test_boolean_is_rejected_before_repository_mutation(self):
        repo = FakeDigestConfigurationRepository()
        service = DigestConfigurationService(repo, FixedClock())

        with pytest.raises(ValueError):
            await service.set_count(
                telegram_user_id=123,
                language_hint="en",
                count=True,
            )
        assert repo.configurations == {}
