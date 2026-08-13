from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect as database_inspect
from sqlalchemy import inspect as orm_inspect
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError

from anxious_news_bot.preferences.domain import (
    ExplicitRequestStatus,
    PreferenceAction,
    PreferenceOrigin,
    QuestionnaireStatus,
    UpdateBatchStatus,
)
from anxious_news_bot.preferences.infrastructure.models import (
    ApplicationUser,
    ExplicitPreferenceRequest,
    PreferenceChangeAudit,
    PreferenceChangeHistory,
    PreferenceEvidence,
    PreferenceParameter,
    PreferenceProfile,
    PreferenceUpdateBatch,
    Questionnaire,
)
from anxious_news_bot.ranking.infrastructure.models import (
    ArticlePreferenceEvaluationRun,
    ArticleRankingRecord,
    RankingRun,
)


def _admin_url() -> str:
    return os.getenv(
        "TEST_POSTGRES_ADMIN_URL",
        "postgresql://postgres:postgres@localhost:5432/postgres",
    )


def _psycopg_url(value: str) -> str:
    url = make_url(value)
    if not url.drivername.startswith("postgresql"):
        raise ValueError("TEST_POSTGRES_ADMIN_URL must use PostgreSQL")
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


async def test_migration_creates_ranking_tables_constraints_and_indexes(
    postgres_engine,
) -> None:
    async with postgres_engine.connect() as connection:
        tables = await connection.run_sync(
            lambda sync: set(database_inspect(sync).get_table_names())
        )
        batch_checks = await connection.run_sync(
            lambda sync: {
                item["name"]
                for item in database_inspect(sync).get_check_constraints(
                    "preference_update_batches"
                )
            }
        )
        history_checks = await connection.run_sync(
            lambda sync: {
                item["name"]
                for item in database_inspect(sync).get_check_constraints(
                    "preference_change_history"
                )
            }
        )
        ranking_indexes = await connection.run_sync(
            lambda sync: database_inspect(sync).get_indexes("ranking_runs")
        )
    assert {
        "explicit_preference_requests",
        "preference_evidence",
        "article_preference_evaluation_runs",
        "article_preference_evaluation_attempts",
        "article_parameter_relevances",
        "ranking_configuration_snapshots",
        "ranking_runs",
        "article_ranking_records",
        "ranking_parameter_contributions",
        "ranking_audit",
    } <= tables
    assert "ck_update_batches_single_source" in batch_checks
    assert "ck_preference_change_history_source_reference" in history_checks
    assert any(
        index["name"] == "ix_ranking_runs_user_status_created"
        for index in ranking_indexes
    )


def test_ranking_mappings_define_expected_relationships() -> None:
    assert (
        not orm_inspect(ExplicitPreferenceRequest).relationships["update_batch"].uselist
    )
    assert {"attempts", "relevances", "accepted_attempt"} <= set(
        orm_inspect(ArticlePreferenceEvaluationRun).relationships.keys()
    )
    assert {"records", "configuration"} <= set(
        orm_inspect(RankingRun).relationships.keys()
    )
    assert {"contributions"} <= set(
        orm_inspect(ArticleRankingRecord).relationships.keys()
    )


async def test_source_link_xor_and_unique_idempotency_constraints(
    database_session,
) -> None:
    user = ApplicationUser(
        telegram_user_id=123,
        language_code="en",
    )
    database_session.add(user)
    await database_session.flush()
    database_session.add(PreferenceProfile(user_id=user.id, revision=0))
    questionnaire = Questionnaire(
        user_id=user.id,
        status=QuestionnaireStatus.GENERATING,
        schema_version="1.0",
        profile_revision=0,
        generation_context_hash="a" * 64,
    )
    explicit_request = ExplicitPreferenceRequest(
        user_id=user.id,
        telegram_update_id=77,
        normalized_text_hash="b" * 64,
        raw_text="More Kirov news",
        language_code="en",
        status=ExplicitRequestStatus.RECEIVED,
        schema_version="1.0",
        base_profile_revision=0,
    )
    database_session.add_all((questionnaire, explicit_request))
    await database_session.flush()

    with pytest.raises(IntegrityError):
        async with database_session.begin_nested():
            database_session.add(
                ExplicitPreferenceRequest(
                    user_id=user.id,
                    telegram_update_id=77,
                    normalized_text_hash="c" * 64,
                    raw_text="Different text",
                    language_code="en",
                    status=ExplicitRequestStatus.RECEIVED,
                    schema_version="1.0",
                    base_profile_revision=0,
                )
            )
            await database_session.flush()

    with pytest.raises(IntegrityError):
        async with database_session.begin_nested():
            database_session.add(
                PreferenceUpdateBatch(
                    questionnaire_id=questionnaire.id,
                    explicit_request_id=explicit_request.id,
                    user_id=user.id,
                    schema_version="1.0",
                    base_profile_revision=0,
                    proposal_hash="d" * 64,
                    change_count=0,
                    status=UpdateBatchStatus.VALIDATED,
                )
            )
            await database_session.flush()


async def test_append_only_triggers_and_source_reference_constraints(
    database_session,
) -> None:
    now = datetime.now(UTC)
    user = ApplicationUser(telegram_user_id=456, language_code="en")
    database_session.add(user)
    await database_session.flush()
    database_session.add(PreferenceProfile(user_id=user.id, revision=0))
    questionnaire = Questionnaire(
        user_id=user.id,
        status=QuestionnaireStatus.APPLIED,
        schema_version="1.0",
        profile_revision=0,
        generation_context_hash="e" * 64,
        completed_at=now,
    )
    explicit_request = ExplicitPreferenceRequest(
        user_id=user.id,
        telegram_update_id=88,
        normalized_text_hash="f" * 64,
        raw_text="More local reporting",
        language_code="en",
        status=ExplicitRequestStatus.APPLIED,
        schema_version="1.0",
        base_profile_revision=0,
        completed_at=now,
    )
    parameter = PreferenceParameter(
        user_id=user.id,
        semantic_key="local_news",
        name="Local news",
        description="Specific local reporting",
        evaluation_instructions="Prefer local reporting",
        weight="0.50",
        origin=PreferenceOrigin.QUESTIONNAIRE,
        active=True,
    )
    database_session.add_all((questionnaire, explicit_request, parameter))
    await database_session.flush()

    batch = PreferenceUpdateBatch(
        questionnaire_id=questionnaire.id,
        user_id=user.id,
        schema_version="1.0",
        base_profile_revision=0,
        proposal_hash="1" * 64,
        change_count=1,
        status=UpdateBatchStatus.APPLIED,
        applied_at=now,
        resulting_profile_revision=1,
    )
    database_session.add(batch)
    await database_session.flush()

    history_id = uuid4()
    database_session.add(
        PreferenceChangeAudit(
            id=history_id,
            batch_id=batch.id,
            parameter_id=parameter.id,
            action=PreferenceAction.CREATE,
            source=PreferenceOrigin.QUESTIONNAIRE,
            questionnaire_id=questionnaire.id,
            previous_state_hash=None,
            new_state_hash="2" * 64,
            reason_hash="3" * 64,
            changed_at=now,
        )
    )
    database_session.add(
        PreferenceEvidence(
            id=uuid4(),
            parameter_id=parameter.id,
            user_id=user.id,
            source=PreferenceOrigin.EXPLICIT,
            explicit_request_id=explicit_request.id,
            action=PreferenceAction.ADJUST,
            requested_weight="0.70",
            active=True,
            reason_hash="4" * 64,
            created_at=now,
        )
    )
    await database_session.flush()

    with pytest.raises(DBAPIError):
        async with database_session.begin_nested():
            await database_session.execute(
                text(
                    "UPDATE preference_evidence SET active = false WHERE explicit_request_id = :request_id"
                ),
                {"request_id": explicit_request.id},
            )

    with pytest.raises(IntegrityError):
        async with database_session.begin_nested():
            database_session.add(
                PreferenceChangeHistory(
                    id=uuid4(),
                    batch_id=batch.id,
                    parameter_id=parameter.id,
                    action=PreferenceAction.ADJUST,
                    source=PreferenceOrigin.EXPLICIT,
                    questionnaire_id=questionnaire.id,
                    previous_state=None,
                    new_state={"weight": "0.70", "active": True},
                    reason="broken source link",
                    changed_at=now,
                )
            )
            await database_session.flush()


def test_migration_backfills_preference_evidence_from_history() -> None:
    database_name = f"anxious_news_backfill_{uuid4().hex}"
    admin_url = _psycopg_url(_admin_url())
    previous_database_url = os.environ.get("DATABASE_URL")
    try:
        with psycopg.connect(admin_url, autocommit=True) as connection:
            connection.execute(f'CREATE DATABASE "{database_name}"')

        database_url = (
            make_url(_admin_url())
            .set(
                drivername="postgresql+psycopg",
                database=database_name,
            )
            .render_as_string(hide_password=False)
        )
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", database_url)
        os.environ["DATABASE_URL"] = database_url
        command.upgrade(config, "002_create_user_preferences")

        with psycopg.connect(_psycopg_url(database_url), autocommit=True) as connection:
            user_id = uuid4()
            questionnaire_id = uuid4()
            batch_id = uuid4()
            parameter_id = uuid4()
            history_id = uuid4()
            changed_at = datetime.now(UTC)
            connection.execute(
                "INSERT INTO application_users (id, telegram_user_id, language_code) VALUES (%s, %s, %s)",
                (user_id, 999, "en"),
            )
            connection.execute(
                "INSERT INTO preference_profiles (user_id, revision) VALUES (%s, %s)",
                (user_id, 1),
            )
            connection.execute(
                "INSERT INTO preference_parameters (id, user_id, semantic_key, name, description, evaluation_instructions, weight, origin, active) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    parameter_id,
                    user_id,
                    "local_news",
                    "Local news",
                    "Specific local reporting",
                    "Prefer local reporting",
                    Decimal("0.50"),
                    "questionnaire",
                    True,
                ),
            )
            connection.execute(
                "INSERT INTO preference_questionnaires (id, user_id, status, schema_version, profile_revision, generation_context_hash, completed_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    questionnaire_id,
                    user_id,
                    "applied",
                    "1.0",
                    0,
                    "a" * 64,
                    changed_at,
                ),
            )
            connection.execute(
                "INSERT INTO preference_update_batches (id, questionnaire_id, user_id, schema_version, base_profile_revision, resulting_profile_revision, proposal_hash, change_count, history_digest, status, applied_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    batch_id,
                    questionnaire_id,
                    user_id,
                    "1.0",
                    0,
                    1,
                    "b" * 64,
                    1,
                    "c" * 64,
                    "applied",
                    changed_at,
                ),
            )
            connection.execute(
                "INSERT INTO preference_change_history (id, batch_id, parameter_id, action, source, questionnaire_id, previous_state, new_state, reason, changed_at) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s)",
                (
                    history_id,
                    batch_id,
                    parameter_id,
                    "adjust",
                    "questionnaire",
                    questionnaire_id,
                    '{"weight":"0.40","active":true}',
                    '{"weight":"0.50","active":true}',
                    "Updated by questionnaire",
                    changed_at,
                ),
            )
            connection.execute(
                "INSERT INTO preference_change_audit (id, batch_id, parameter_id, action, source, questionnaire_id, previous_state_hash, new_state_hash, reason_hash, changed_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    history_id,
                    batch_id,
                    parameter_id,
                    "adjust",
                    "questionnaire",
                    questionnaire_id,
                    "d" * 64,
                    "e" * 64,
                    "f" * 64,
                    changed_at,
                ),
            )

        command.upgrade(config, "head")

        with psycopg.connect(_psycopg_url(database_url), autocommit=True) as connection:
            row = connection.execute(
                "SELECT parameter_id, user_id, source, questionnaire_id, requested_weight, active, reason_hash FROM preference_evidence"
            ).fetchone()
        assert row is not None
        assert row[0] == parameter_id
        assert row[1] == user_id
        assert row[2] == "questionnaire"
        assert row[3] == questionnaire_id
        assert row[4] == Decimal("0.50")
        assert row[5] is True
        assert row[6] == "f" * 64
    finally:
        if previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database_url
        with psycopg.connect(admin_url, autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
                (database_name,),
            )
            connection.execute(f'DROP DATABASE IF EXISTS "{database_name}"')
