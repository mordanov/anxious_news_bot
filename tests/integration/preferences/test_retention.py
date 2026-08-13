from datetime import timedelta

import pytest
from sqlalchemy import delete, func, select, text, update

from anxious_news_bot.preferences.domain import QuestionnaireStatus
from anxious_news_bot.preferences.infrastructure.models import (
    PreferenceChangeAudit,
    PreferenceChangeHistory,
    PreferenceParameter,
    PreferenceUpdateBatch,
    Questionnaire,
    QuestionnaireQuestion,
)
from anxious_news_bot.preferences.services.retention import PreferenceRetentionService
from tests.fixtures.preferences import FixedClock
from tests.integration.preferences.helpers import completed_answers, create_proposal


async def test_cleanup_removes_verbose_data_but_preserves_per_change_audit(
    preference_repository, preference_database
) -> None:
    _, state, _ = await completed_answers(preference_repository)
    await preference_repository.load_interpretation_input(state.questionnaire_id)
    old = FixedClock.value - timedelta(days=500)
    await preference_repository.apply_changes(
        state.questionnaire_id,
        create_proposal(state.questionnaire_id),
        old,
    )
    async with preference_database.session() as session:
        await session.execute(
            update(Questionnaire)
            .where(Questionnaire.id == state.questionnaire_id)
            .values(completed_at=old)
        )
    service = PreferenceRetentionService(
        preference_repository,
        FixedClock(),
        questionnaire_days=365,
        history_days=365,
        batch_size=500,
    )
    result = await service.run_once()
    assert result.questionnaire_details_removed == 10
    assert result.full_history_rows_removed == 1
    assert result.compact_audit_rows_preserved == 1
    async with preference_database.session() as session:
        counts = {
            "questions": await session.scalar(
                select(func.count(QuestionnaireQuestion.id))
            ),
            "history": await session.scalar(
                select(func.count(PreferenceChangeHistory.id))
            ),
            "audit": await session.scalar(select(func.count(PreferenceChangeAudit.id))),
            "parameters": await session.scalar(
                select(func.count(PreferenceParameter.id))
            ),
        }
        batch = await session.scalar(select(PreferenceUpdateBatch))
    assert counts == {
        "questions": 0,
        "history": 0,
        "audit": 1,
        "parameters": 1,
    }
    assert batch.history_digest
    repeated = await service.run_once()
    assert repeated.questionnaire_details_removed == 0
    assert repeated.full_history_rows_removed == 0


async def test_cleanup_refuses_history_deletion_when_compact_audit_is_missing(
    preference_repository, preference_database
) -> None:
    _, state, _ = await completed_answers(preference_repository)
    await preference_repository.load_interpretation_input(state.questionnaire_id)
    old = FixedClock.value - timedelta(days=500)
    await preference_repository.apply_changes(
        state.questionnaire_id,
        create_proposal(state.questionnaire_id),
        old,
    )
    async with preference_database.session() as session:
        await session.execute(
            text(
                "ALTER TABLE preference_change_audit "
                "DISABLE TRIGGER preference_change_audit_immutable"
            )
        )
        await session.execute(delete(PreferenceChangeAudit))
        await session.execute(
            text(
                "ALTER TABLE preference_change_audit "
                "ENABLE TRIGGER preference_change_audit_immutable"
            )
        )
    with pytest.raises(RuntimeError, match="without per-change audit"):
        await preference_repository.compact_retention(
            questionnaire_cutoff=FixedClock.value - timedelta(days=365),
            history_cutoff=FixedClock.value - timedelta(days=365),
            batch_size=500,
        )
    async with preference_database.session() as session:
        assert await session.scalar(select(func.count(PreferenceChangeHistory.id))) == 1


async def test_cleanup_removes_expired_failures_and_excludes_active_sessions(
    preference_repository, preference_database
) -> None:
    _, active = await preference_repository.start_or_resume(700, "en")
    _, failed = await preference_repository.start_or_resume(701, "en")
    old = FixedClock.value - timedelta(days=500)
    await preference_repository.fail(failed.questionnaire_id, "provider_error", old)
    result = await preference_repository.compact_retention(
        questionnaire_cutoff=FixedClock.value - timedelta(days=365),
        history_cutoff=None,
        batch_size=1,
    )
    assert result.failed_questionnaires_removed == 1
    async with preference_database.session() as session:
        remaining = tuple(await session.scalars(select(Questionnaire)))
    assert len(remaining) == 1
    assert remaining[0].id == active.questionnaire_id
    assert remaining[0].status is QuestionnaireStatus.GENERATING
