"""Transactional application-user/profile/digest provisioning."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from anxious_news_bot.digest.domain import (
    validate_digest_count,
    validate_iana_timezone,
)
from anxious_news_bot.preferences.domain import normalize_language_code
from anxious_news_bot.preferences.infrastructure.models import (
    ApplicationUser,
    PreferenceProfile,
)


@dataclass(frozen=True, slots=True)
class DigestDefaults:
    count: int = 10
    local_time: time = time(9, 0)
    timezone_name: str = "UTC"

    def __post_init__(self) -> None:
        validate_digest_count(self.count)
        if self.local_time.second or self.local_time.microsecond:
            raise ValueError("digest default local time must use minute precision")
        validate_iana_timezone(self.timezone_name)


@dataclass(frozen=True, slots=True)
class ProvisionedUser:
    application_user: ApplicationUser
    preference_profile: PreferenceProfile
    digest_configuration: object


class ApplicationUserProvisioner:
    """Sole concurrency-safe creation/self-healing path for user-owned state."""

    def __init__(self, defaults: DigestDefaults | None = None) -> None:
        self._defaults = defaults or DigestDefaults()

    async def ensure(
        self,
        session: AsyncSession,
        *,
        telegram_user_id: int,
        language_hint: str | None,
    ) -> ProvisionedUser:
        if isinstance(telegram_user_id, bool) or telegram_user_id <= 0:
            raise ValueError("telegram_user_id must be positive")

        # Imported lazily to keep the shared identity module independent of
        # digest model import ordering during Alembic startup.
        from anxious_news_bot.digest.infrastructure.models import DigestConfiguration

        language = normalize_language_code(language_hint)
        inserted_user = (
            await session.execute(
                insert(ApplicationUser)
                .values(
                    telegram_user_id=telegram_user_id,
                    language_code=language.value,
                )
                .on_conflict_do_nothing(
                    index_elements=[ApplicationUser.telegram_user_id]
                )
                .returning(ApplicationUser)
            )
        ).scalar_one_or_none()
        user = inserted_user
        if user is None:
            user = await session.scalar(
                select(ApplicationUser).where(
                    ApplicationUser.telegram_user_id == telegram_user_id
                )
            )
        if user is None:
            raise RuntimeError("application user claim failed")

        await session.execute(
            insert(PreferenceProfile)
            .values(user_id=user.id, revision=0)
            .on_conflict_do_nothing(index_elements=[PreferenceProfile.user_id])
        )
        await session.execute(
            insert(DigestConfiguration)
            .values(
                user_id=user.id,
                enabled=False,
                digest_count=self._defaults.count,
                schedule_local_time=self._defaults.local_time,
                timezone_name=self._defaults.timezone_name,
                next_due_at=None,
                schedule_revision=0,
            )
            .on_conflict_do_nothing(index_elements=[DigestConfiguration.user_id])
        )
        await session.flush()

        profile = await session.get(PreferenceProfile, user.id)
        digest_configuration = await session.get(DigestConfiguration, user.id)
        if profile is None or digest_configuration is None:
            raise RuntimeError("application user state provisioning failed")
        return ProvisionedUser(user, profile, digest_configuration)


_DEFAULT_PROVISIONER = ApplicationUserProvisioner()


async def ensure_application_user(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    language_hint: str | None,
    digest_defaults: DigestDefaults | None = None,
) -> ProvisionedUser:
    """Compatibility function delegating to the sole provisioner."""
    provisioner = (
        _DEFAULT_PROVISIONER
        if digest_defaults is None
        else ApplicationUserProvisioner(digest_defaults)
    )
    return await provisioner.ensure(
        session,
        telegram_user_id=telegram_user_id,
        language_hint=language_hint,
    )
