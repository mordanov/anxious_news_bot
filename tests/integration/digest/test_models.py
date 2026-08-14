from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


def test_migration_backfills_disabled_safe_defaults(
    digest_pre_migration_database_url: str,
) -> None:
    user_id = uuid4()
    sync_url = digest_pre_migration_database_url.replace(
        "postgresql+psycopg://", "postgresql://", 1
    )
    with psycopg.connect(sync_url, autocommit=True) as connection:
        connection.execute(
            "INSERT INTO application_users "
            "(id, telegram_user_id, language_code) VALUES (%s, %s, %s)",
            (user_id, 99_001, "es"),
        )
        connection.execute(
            "INSERT INTO preference_profiles (user_id, revision) VALUES (%s, 0)",
            (user_id,),
        )

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", digest_pre_migration_database_url)
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = digest_pre_migration_database_url
    try:
        command.upgrade(config, "head")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous

    with psycopg.connect(sync_url) as connection:
        row = connection.execute(
            "SELECT enabled, digest_count, schedule_local_time, timezone_name, "
            "next_due_at, schedule_revision FROM digest_configurations "
            "WHERE user_id = %s",
            (user_id,),
        ).fetchone()
        assert row == (False, 10, datetime.min.time().replace(hour=9), "UTC", None, 0)
        revision = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()
        assert revision == ("005_scheduler_digest",)


async def test_digest_schema_has_expected_enums_indexes_and_constraints(
    digest_database,
) -> None:
    async with digest_database.session() as session:
        enum_names = set(
            await session.scalars(
                text(
                    "SELECT typname FROM pg_type WHERE typname LIKE 'digest_%' "
                    "AND typtype = 'e'"
                )
            )
        )
        index_names = set(
            await session.scalars(
                text("SELECT indexname FROM pg_indexes WHERE tablename LIKE 'digest_%'")
            )
        )
        constraint_names = set(
            await session.scalars(
                text(
                    "SELECT conname FROM pg_constraint "
                    "WHERE conrelid::regclass::text LIKE 'digest_%'"
                )
            )
        )

    assert {
        "digest_execution_status",
        "digest_attempt_phase",
        "digest_attempt_status",
        "digest_failure_class",
        "digest_delivery_part_status",
        "digest_history_outcome",
        "digest_material_update_basis",
        "digest_material_update_outcome",
    } <= enum_names
    assert {
        "ix_digest_configurations_due",
        "ix_digest_executions_status_retry",
        "ix_digest_delivery_history_user_article",
        "ix_digest_delivery_history_user_event",
    } <= index_names
    assert {
        "ck_digest_configurations_enabled_due",
        "ck_digest_executions_terminal",
        "ck_digest_delivery_parts_state",
        "ck_digest_material_update_evidence_consistency",
        "uq_digest_material_update_evidence_pair_policy",
    } <= constraint_names


async def test_enabled_configuration_requires_next_due(
    digest_database,
    provision_digest_user,
) -> None:
    user = await provision_digest_user()

    with pytest.raises(IntegrityError):
        async with digest_database.session() as session:
            await session.execute(
                text(
                    "UPDATE digest_configurations SET enabled = true "
                    "WHERE user_id = :user_id"
                ),
                {"user_id": user.application_user.id},
            )


async def test_terminal_execution_requires_completion_timestamp(
    digest_database,
    provision_digest_user,
) -> None:
    user = await provision_digest_user()
    execution_id = uuid4()

    with pytest.raises(IntegrityError):
        async with digest_database.session() as session:
            await session.execute(
                text(
                    "INSERT INTO digest_executions "
                    "(id, user_id, occurrence_key, scheduled_for, local_date, "
                    "local_time, timezone_name, schedule_revision, digest_count, "
                    "language_code, ranking_request_id, status, attempt_count, "
                    "failure_class) VALUES "
                    "(:id, :user_id, :occurrence_key, :scheduled_for, :local_date, "
                    ":local_time, 'UTC', 0, 10, 'en', :request_id, 'failed', 1, "
                    "'permanent')"
                ),
                {
                    "id": execution_id,
                    "user_id": user.application_user.id,
                    "occurrence_key": "2026-01-15/09:00/UTC",
                    "scheduled_for": datetime(2026, 1, 15, 9, tzinfo=UTC),
                    "local_date": datetime(2026, 1, 15).date(),
                    "local_time": datetime(2026, 1, 15, 9).time(),
                    "request_id": f"digest-execution:{execution_id}",
                },
            )
