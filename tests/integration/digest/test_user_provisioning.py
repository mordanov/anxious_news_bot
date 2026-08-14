from __future__ import annotations

import asyncio
from datetime import time

from sqlalchemy import func, select, text

from anxious_news_bot.digest.infrastructure.models import DigestConfiguration
from anxious_news_bot.infrastructure.users import (
    ApplicationUserProvisioner,
    DigestDefaults,
)
from anxious_news_bot.preferences.infrastructure.models import (
    ApplicationUser,
    PreferenceProfile,
)
from anxious_news_bot.preferences.infrastructure.persistence import (
    SQLAlchemyPreferenceRepository,
)


async def test_provisioner_atomically_creates_all_user_state(
    digest_database,
) -> None:
    provisioner = ApplicationUserProvisioner(
        DigestDefaults(count=12, local_time=time(7, 45), timezone_name="Europe/Madrid")
    )
    async with digest_database.session() as session:
        result = await provisioner.ensure(
            session,
            telegram_user_id=22_001,
            language_hint="es-ES",
        )

    assert result.application_user.language_code == "es"
    assert result.preference_profile.revision == 0
    assert result.digest_configuration.enabled is False
    assert result.digest_configuration.digest_count == 12
    assert result.digest_configuration.schedule_local_time == time(7, 45)
    assert result.digest_configuration.timezone_name == "Europe/Madrid"
    assert result.digest_configuration.next_due_at is None


async def test_provisioner_self_heals_missing_profile_and_configuration(
    digest_database,
) -> None:
    provisioner = ApplicationUserProvisioner()
    async with digest_database.session() as session:
        first = await provisioner.ensure(
            session,
            telegram_user_id=22_002,
            language_hint="ru",
        )
        user_id = first.application_user.id
    async with digest_database.session() as session:
        await session.execute(
            text("DELETE FROM digest_configurations WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
        await session.execute(
            text("DELETE FROM preference_profiles WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
    async with digest_database.session() as session:
        healed = await provisioner.ensure(
            session,
            telegram_user_id=22_002,
            language_hint="ru",
        )

    assert healed.application_user.id == user_id
    assert healed.preference_profile.user_id == user_id
    assert healed.digest_configuration.user_id == user_id


async def test_concurrent_provisioning_creates_exactly_one_of_each_row(
    digest_database,
) -> None:
    provisioner = ApplicationUserProvisioner()

    async def ensure_once():
        async with digest_database.session() as session:
            return await provisioner.ensure(
                session,
                telegram_user_id=22_003,
                language_hint="en",
            )

    results = await asyncio.gather(*(ensure_once() for _ in range(8)))
    assert len({result.application_user.id for result in results}) == 1

    async with digest_database.session() as session:
        user_count = await session.scalar(
            select(func.count())
            .select_from(ApplicationUser)
            .where(ApplicationUser.telegram_user_id == 22_003)
        )
        profile_count = await session.scalar(
            select(func.count())
            .select_from(PreferenceProfile)
            .join(ApplicationUser, ApplicationUser.id == PreferenceProfile.user_id)
            .where(ApplicationUser.telegram_user_id == 22_003)
        )
        config_count = await session.scalar(
            select(func.count())
            .select_from(DigestConfiguration)
            .join(ApplicationUser, ApplicationUser.id == DigestConfiguration.user_id)
            .where(ApplicationUser.telegram_user_id == 22_003)
        )
    assert (user_count, profile_count, config_count) == (1, 1, 1)


async def test_preference_entry_point_uses_shared_provisioner(
    digest_database,
) -> None:
    repository = SQLAlchemyPreferenceRepository(digest_database)

    language = await repository.get_or_create_language(22_004, "es")

    assert language.value == "es"
    async with digest_database.session() as session:
        row = (
            await session.execute(
                select(ApplicationUser, PreferenceProfile, DigestConfiguration)
                .join(
                    PreferenceProfile,
                    PreferenceProfile.user_id == ApplicationUser.id,
                )
                .join(
                    DigestConfiguration,
                    DigestConfiguration.user_id == ApplicationUser.id,
                )
                .where(ApplicationUser.telegram_user_id == 22_004)
            )
        ).one()
    assert row.DigestConfiguration.enabled is False
    assert row.DigestConfiguration.digest_count == 10
