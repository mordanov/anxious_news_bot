from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import func, select, update

from anxious_news_bot.infrastructure.database import Database
from anxious_news_bot.preferences.domain import (
    ExplicitRequestStatus,
    PreferenceOrigin,
    SpecifyStateKind,
    UpdateBatchStatus,
)
from anxious_news_bot.preferences.errors import (
    PersistenceConflict,
    PreferenceProposalInvalid,
    StaleProfileRevision,
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
)
from anxious_news_bot.preferences.infrastructure.persistence import (
    SQLAlchemyPreferenceRepository,
)
from anxious_news_bot.preferences.schemas import ExplicitPreferenceChangesSchema


@pytest_asyncio.fixture
async def explicit_preference_database(postgres_database_url):
    database = Database(postgres_database_url)
    try:
        yield database
    finally:
        async with database.session() as session:
            await session.execute(select(1))
            await session.execute(
                __import__("sqlalchemy").text(
                    "TRUNCATE preference_change_audit, preference_change_history, "
                    "preference_evidence, preference_update_batches, "
                    "explicit_preference_requests, preference_answers, "
                    "preference_question_options, preference_questions, "
                    "preference_questionnaires, preference_parameters, "
                    "preference_profiles, application_users CASCADE"
                )
            )
        await database.close()


@pytest_asyncio.fixture
async def explicit_repository(explicit_preference_database):
    return SQLAlchemyPreferenceRepository(
        explicit_preference_database,
        history_context_limit=20,
        explicit_history_limit=20,
    )


def _proposal(
    request_id: UUID,
    revision: int,
    change: dict[str, object],
) -> ExplicitPreferenceChangesSchema:
    return ExplicitPreferenceChangesSchema.model_validate(
        {
            "schema_version": "1.0",
            "request_id": request_id,
            "base_profile_revision": revision,
            "changes": [change],
        },
        strict=True,
    )


async def _claim_request(repository, telegram_user_id: int, update_id: int, text: str):
    claim = await repository.claim_explicit_request(
        telegram_user_id,
        update_id,
        text,
        "en",
        datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert claim.replay_state is None
    return claim.request_id


async def _seed_parameter(
    database: Database,
    *,
    telegram_user_id: int,
    semantic_key: str = "kirov_city_news",
    name: str = "Kirov city news",
    weight: str = "0.40",
    origin: PreferenceOrigin = PreferenceOrigin.QUESTIONNAIRE,
    active: bool = True,
) -> tuple[UUID, UUID]:
    async with database.session() as session:
        user = await session.scalar(
            select(ApplicationUser).where(
                ApplicationUser.telegram_user_id == telegram_user_id
            )
        )
        if user is None:
            user = ApplicationUser(
                telegram_user_id=telegram_user_id, language_code="en"
            )
            session.add(user)
            await session.flush()
            session.add(PreferenceProfile(user_id=user.id, revision=0))
            await session.flush()
        parameter = PreferenceParameter(
            user_id=user.id,
            semantic_key=semantic_key,
            name=name,
            description=f"Specific reporting about {name.lower()}.",
            evaluation_instructions=f"Prefer relevant {name.lower()} reporting.",
            weight=Decimal(weight),
            origin=origin,
            active=active,
        )
        session.add(parameter)
        await session.flush()
        return user.id, parameter.id


async def test_request_idempotency_and_same_key_different_text_rejection(
    explicit_repository,
) -> None:
    request_id = await _claim_request(
        explicit_repository, 321, 9001, "More Kirov city news"
    )
    await explicit_repository.load_explicit_context(request_id)
    proposal = _proposal(
        request_id,
        0,
        {
            "action": "create",
            "semantic_key": "kirov_city_news",
            "name": "Kirov city news",
            "description": "Specific city reporting about Kirov.",
            "evaluation_instructions": "Prefer relevant Kirov city reporting.",
            "target_weight": "0.80",
            "reason": "User explicitly asked for more Kirov city news.",
        },
    )
    await explicit_repository.apply_explicit_changes(
        request_id,
        proposal,
        datetime(2026, 1, 1, tzinfo=UTC),
    )

    replay = await explicit_repository.claim_explicit_request(
        321,
        9001,
        "More Kirov city news",
        "en",
        datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert replay.request_id == request_id
    assert replay.replay_state is not None
    assert replay.replay_state.kind is SpecifyStateKind.APPLIED

    with pytest.raises(PersistenceConflict):
        await explicit_repository.claim_explicit_request(
            321,
            9001,
            "Different text for the same Telegram update",
            "en",
            datetime(2026, 1, 1, tzinfo=UTC),
        )


async def test_profile_compare_and_swap_marks_request_stale_without_changes(
    explicit_repository,
    explicit_preference_database,
) -> None:
    request_id = await _claim_request(
        explicit_repository, 322, 9002, "More Kirov city news"
    )
    profile, _ = await explicit_repository.load_explicit_context(request_id)
    async with explicit_preference_database.session() as session:
        await session.execute(
            update(PreferenceProfile)
            .where(PreferenceProfile.user_id == profile.user_id)
            .values(revision=1)
        )

    proposal = _proposal(
        request_id,
        0,
        {
            "action": "create",
            "semantic_key": "kirov_city_news",
            "name": "Kirov city news",
            "description": "Specific city reporting about Kirov.",
            "evaluation_instructions": "Prefer relevant Kirov city reporting.",
            "target_weight": "0.80",
            "reason": "User explicitly asked for more Kirov city news.",
        },
    )

    with pytest.raises(StaleProfileRevision):
        await explicit_repository.apply_explicit_changes(
            request_id,
            proposal,
            datetime(2026, 1, 1, tzinfo=UTC),
        )

    async with explicit_preference_database.session() as session:
        request = await session.get(ExplicitPreferenceRequest, request_id)
        assert request.status is ExplicitRequestStatus.STALE
        assert await session.scalar(select(func.count(PreferenceUpdateBatch.id))) == 0
        assert await session.scalar(select(func.count(PreferenceEvidence.id))) == 0


async def test_concurrent_replay_applies_once_and_preserves_origin_history_audit_and_evidence(
    explicit_preference_database,
) -> None:
    repository_a = SQLAlchemyPreferenceRepository(
        explicit_preference_database,
        history_context_limit=20,
        explicit_history_limit=20,
    )
    repository_b = SQLAlchemyPreferenceRepository(
        explicit_preference_database,
        history_context_limit=20,
        explicit_history_limit=20,
    )
    user_id, parameter_id = await _seed_parameter(
        explicit_preference_database,
        telegram_user_id=323,
        origin=PreferenceOrigin.QUESTIONNAIRE,
    )
    claim = await repository_a.claim_explicit_request(
        323,
        9003,
        "More Kirov city news",
        "en",
        datetime(2026, 1, 1, tzinfo=UTC),
    )
    request_id = claim.request_id
    await repository_a.load_explicit_context(request_id)
    proposal = _proposal(
        request_id,
        0,
        {
            "action": "adjust",
            "parameter_id": parameter_id,
            "target_weight": "0.80",
            "reason": "User explicitly asked for more Kirov city news.",
        },
    )

    first, second = await asyncio.gather(
        repository_a.apply_explicit_changes(
            request_id,
            proposal,
            datetime(2026, 1, 1, tzinfo=UTC),
        ),
        repository_b.apply_explicit_changes(
            request_id,
            proposal,
            datetime(2026, 1, 1, tzinfo=UTC),
        ),
    )

    assert {first.kind, second.kind} == {SpecifyStateKind.APPLIED}
    async with explicit_preference_database.session() as session:
        parameter = await session.get(PreferenceParameter, parameter_id)
        request = await session.get(ExplicitPreferenceRequest, request_id)
        batch = await session.scalar(select(PreferenceUpdateBatch))
        history = await session.scalar(select(PreferenceChangeHistory))
        audit = await session.scalar(select(PreferenceChangeAudit))
        evidence = await session.scalar(select(PreferenceEvidence))
        profile = await session.get(PreferenceProfile, user_id)

    assert request.status is ExplicitRequestStatus.APPLIED
    assert batch.status is UpdateBatchStatus.APPLIED
    assert profile.revision == 1
    assert parameter.weight == Decimal("0.80")
    assert parameter.origin is PreferenceOrigin.QUESTIONNAIRE
    assert history.source is PreferenceOrigin.EXPLICIT
    assert history.explicit_request_id == request_id
    assert audit.explicit_request_id == request_id
    assert evidence.source is PreferenceOrigin.EXPLICIT
    assert evidence.explicit_request_id == request_id
    assert evidence.requested_weight == Decimal("0.80")
    assert evidence.active is True


async def test_invalid_batch_rolls_back_batch_history_audit_and_evidence(
    explicit_repository,
    explicit_preference_database,
) -> None:
    _, parameter_id = await _seed_parameter(
        explicit_preference_database,
        telegram_user_id=324,
        semantic_key="moscow_politics",
        name="Moscow politics",
        origin=PreferenceOrigin.EXPLICIT,
    )
    request_id = await _claim_request(
        explicit_repository, 324, 9004, "More Kirov city news"
    )
    await explicit_repository.load_explicit_context(request_id)
    proposal = _proposal(
        request_id,
        0,
        {
            "action": "adjust",
            "parameter_id": parameter_id,
            "target_weight": "0.80",
            "reason": "User explicitly asked for more Kirov city news.",
        },
    )

    with pytest.raises(PreferenceProposalInvalid):
        await explicit_repository.apply_explicit_changes(
            request_id,
            proposal,
            datetime(2026, 1, 1, tzinfo=UTC),
        )

    async with explicit_preference_database.session() as session:
        counts = {
            "batches": await session.scalar(
                select(func.count(PreferenceUpdateBatch.id))
            ),
            "history": await session.scalar(
                select(func.count(PreferenceChangeHistory.id))
            ),
            "audit": await session.scalar(select(func.count(PreferenceChangeAudit.id))),
            "evidence": await session.scalar(select(func.count(PreferenceEvidence.id))),
        }
    assert counts == {"batches": 0, "history": 0, "audit": 0, "evidence": 0}


async def test_failed_user_request_does_not_block_another_users_success(
    explicit_repository,
    explicit_preference_database,
) -> None:
    first_request_id = await _claim_request(
        explicit_repository,
        325,
        9005,
        "More Kirov city news",
    )
    failed = await explicit_repository.fail_explicit_request(
        first_request_id,
        "interpretation_failed",
        datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert failed.kind is SpecifyStateKind.FAILED

    second_request_id = await _claim_request(
        explicit_repository,
        326,
        9006,
        "More Kirov city news",
    )
    await explicit_repository.load_explicit_context(second_request_id)
    proposal = _proposal(
        second_request_id,
        0,
        {
            "action": "create",
            "semantic_key": "kirov_city_news",
            "name": "Kirov city news",
            "description": "Specific city reporting about Kirov.",
            "evaluation_instructions": "Prefer relevant Kirov city reporting.",
            "target_weight": "0.80",
            "reason": "User explicitly asked for more Kirov city news.",
        },
    )
    succeeded = await explicit_repository.apply_explicit_changes(
        second_request_id,
        proposal,
        datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert succeeded.kind is SpecifyStateKind.APPLIED

    async with explicit_preference_database.session() as session:
        failed_request = await session.get(ExplicitPreferenceRequest, first_request_id)
        succeeded_request = await session.get(
            ExplicitPreferenceRequest, second_request_id
        )
        first_user = await session.scalar(
            select(ApplicationUser).where(ApplicationUser.telegram_user_id == 325)
        )
        second_user = await session.scalar(
            select(ApplicationUser).where(ApplicationUser.telegram_user_id == 326)
        )
        first_profile = await session.get(PreferenceProfile, first_user.id)
        second_profile = await session.get(PreferenceProfile, second_user.id)

    assert failed_request.status is ExplicitRequestStatus.FAILED
    assert succeeded_request.status is ExplicitRequestStatus.APPLIED
    assert first_profile.revision == 0
    assert second_profile.revision == 1
