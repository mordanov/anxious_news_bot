from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from anxious_news_bot.digest.infrastructure.models import (
    DigestConfiguration,
    DigestExecution,
)
from anxious_news_bot.digest.services.configuration import DigestConfigurationService
from anxious_news_bot.preferences.infrastructure.models import ApplicationUser
from tests.fixtures.digest import FixedClock


async def test_first_count_command_atomically_provisions_disabled_user_state(
    digest_database,
    digest_repository,
) -> None:
    service = DigestConfigurationService(digest_repository, FixedClock())

    result = await service.set_count(
        telegram_user_id=41_001,
        language_hint="es",
        count=5,
    )

    assert result.digest_count == 5
    assert result.enabled is False
    async with digest_database.session() as session:
        row = (
            await session.execute(
                select(ApplicationUser, DigestConfiguration)
                .join(
                    DigestConfiguration,
                    DigestConfiguration.user_id == ApplicationUser.id,
                )
                .where(ApplicationUser.telegram_user_id == 41_001)
            )
        ).one()
    assert row.ApplicationUser.language_code == "es"
    assert row.DigestConfiguration.next_due_at is None


async def test_concurrent_count_updates_keep_one_configuration_per_user(
    digest_database,
    digest_repository,
) -> None:
    service = DigestConfigurationService(digest_repository, FixedClock())

    await asyncio.gather(
        *(
            service.set_count(
                telegram_user_id=41_002,
                language_hint="en",
                count=count,
            )
            for count in (5, 8, 12, 20)
        )
    )

    async with digest_database.session() as session:
        rows = (
            (
                await session.execute(
                    select(DigestConfiguration)
                    .join(
                        ApplicationUser,
                        ApplicationUser.id == DigestConfiguration.user_id,
                    )
                    .where(ApplicationUser.telegram_user_id == 41_002)
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1
    assert rows[0].digest_count in {5, 8, 12, 20}


async def test_count_updates_are_isolated_between_users(
    digest_database,
    digest_repository,
) -> None:
    service = DigestConfigurationService(digest_repository, FixedClock())
    await service.set_count(
        telegram_user_id=41_003,
        language_hint="en",
        count=5,
    )
    await service.set_count(
        telegram_user_id=41_004,
        language_hint="ru",
        count=20,
    )

    async with digest_database.session() as session:
        rows = dict(
            (
                await session.execute(
                    select(
                        ApplicationUser.telegram_user_id,
                        DigestConfiguration.digest_count,
                    )
                    .join(
                        DigestConfiguration,
                        DigestConfiguration.user_id == ApplicationUser.id,
                    )
                    .where(ApplicationUser.telegram_user_id.in_([41_003, 41_004]))
                )
            ).all()
        )
    assert rows == {41_003: 5, 41_004: 20}


async def test_invalid_count_does_not_create_or_mutate_state(
    digest_database,
    digest_repository,
) -> None:
    service = DigestConfigurationService(digest_repository, FixedClock())

    with pytest.raises(ValueError):
        await service.set_count(
            telegram_user_id=41_005,
            language_hint="en",
            count=4,
        )

    async with digest_database.session() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(ApplicationUser)
            .where(ApplicationUser.telegram_user_id == 41_005)
        )
    assert count == 0


async def test_claimed_execution_keeps_count_snapshot_after_configuration_change(
    digest_database,
    digest_repository,
    provision_digest_user,
    enable_digest_user,
) -> None:
    user = await provision_digest_user(telegram_user_id=41_006)
    await digest_repository.set_count(41_006, "en", 5, datetime.now(UTC))
    due_at = datetime(2026, 1, 15, 9, tzinfo=UTC)
    await enable_digest_user(
        user.application_user.id,
        due_at=due_at,
        digest_count=5,
    )
    occurrence = (await digest_repository.claim_due(due_at + timedelta(minutes=1), 1))[
        0
    ]

    await digest_repository.set_count(
        41_006,
        "en",
        20,
        due_at + timedelta(minutes=2),
    )

    assert occurrence.digest_count == 5
    async with digest_database.session() as session:
        execution = await session.get(DigestExecution, occurrence.execution_id)
        configuration = await session.get(
            DigestConfiguration,
            user.application_user.id,
        )
    assert execution.digest_count == 5
    assert configuration.digest_count == 20
