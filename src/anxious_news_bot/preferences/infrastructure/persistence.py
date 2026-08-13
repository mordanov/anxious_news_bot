from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from anxious_news_bot.infrastructure.database import Database
from anxious_news_bot.preferences.domain import (
    ExplicitRequestClaim,
    ExplicitRequestStatus,
    PreferenceOrigin,
    PreferenceParameter,
    PriorAnswer,
    ProfileSnapshot,
    QuestionnaireContext,
    QuestionnaireStatus,
    RetentionResult,
    SpecifyState,
    SpecifyStateKind,
    TuneOption,
    TuneState,
    TuneStateKind,
    UpdateBatchStatus,
)
from anxious_news_bot.preferences.errors import (
    AnswerRejected,
    PersistenceConflict,
    PreferenceProposalInvalid,
    StaleProfileRevision,
)
from anxious_news_bot.preferences.infrastructure.llm import (
    EXPLICIT_INTERPRETATION_VERSION,
)
from anxious_news_bot.preferences.infrastructure.models import (
    ApplicationUser,
    ExplicitPreferenceRequest,
    PreferenceChangeAudit,
    PreferenceChangeHistory,
    PreferenceEvidence,
    PreferenceProfile,
    PreferenceUpdateBatch,
    Questionnaire,
    QuestionnaireAnswer,
    QuestionnaireQuestion,
    QuestionOption,
)
from anxious_news_bot.preferences.infrastructure.models import (
    PreferenceParameter as PreferenceParameterModel,
)
from anxious_news_bot.preferences.schemas import (
    AdjustChangeSchema,
    CreateChangeSchema,
    DeactivateChangeSchema,
    ExplicitPreferenceChangesSchema,
    PreferenceChangesSchema,
    QuestionnaireGenerationSchema,
    ReactivateChangeSchema,
    RefineChangeSchema,
)
from anxious_news_bot.preferences.services.apply_changes import (
    DeterministicPreferenceChangeValidator,
    proposal_hash,
)
from anxious_news_bot.preferences.services.duplicates import normalize_semantic_key

ACTIVE_STATUSES = (
    QuestionnaireStatus.GENERATING,
    QuestionnaireStatus.ANSWERING,
    QuestionnaireStatus.ANSWERS_COMPLETE,
    QuestionnaireStatus.INTERPRETING,
    QuestionnaireStatus.APPLYING,
)
ACTIVE_EXPLICIT_STATUSES = (
    ExplicitRequestStatus.RECEIVED,
    ExplicitRequestStatus.INTERPRETING,
    ExplicitRequestStatus.VALIDATED,
    ExplicitRequestStatus.APPLYING,
)


class SQLAlchemyPreferenceRepository:
    def __init__(
        self,
        database: Database,
        *,
        history_context_limit: int = 20,
        duplicate_threshold: float = 0.72,
        explicit_history_limit: int | None = None,
    ) -> None:
        self._database = database
        self._history_context_limit = history_context_limit
        self._duplicate_threshold = duplicate_threshold
        self._explicit_history_limit = (
            history_context_limit
            if explicit_history_limit is None
            else explicit_history_limit
        )
        self._change_validator = DeterministicPreferenceChangeValidator()

    async def start_or_resume(
        self, telegram_user_id: int, language_code: str | None
    ) -> tuple[QuestionnaireContext, TuneState]:
        async with self._database.session() as session:
            user, _ = await self._ensure_user_profile(
                session,
                telegram_user_id=telegram_user_id,
                language_code=language_code,
            )
            questionnaire = await session.scalar(
                select(Questionnaire)
                .where(
                    Questionnaire.user_id == user.id,
                    Questionnaire.status.in_(ACTIVE_STATUSES),
                )
                .order_by(Questionnaire.created_at.desc())
            )
            profile = await self._snapshot(session, user.id)
            context = QuestionnaireContext(
                profile=profile,
                language_code=user.language_code,
                prior_answers=await self._prior_answers(session, user.id),
            )
            if questionnaire is not None:
                return context, await self._state(session, questionnaire)

            questionnaire = (
                await session.execute(
                    insert(Questionnaire)
                    .values(
                        user_id=user.id,
                        status=QuestionnaireStatus.GENERATING,
                        profile_revision=profile.revision,
                        generation_context_hash=self._context_hash(context),
                    )
                    .on_conflict_do_nothing()
                    .returning(Questionnaire)
                )
            ).scalar_one_or_none()
            if questionnaire is None:
                questionnaire = await session.scalar(
                    select(Questionnaire)
                    .where(
                        Questionnaire.user_id == user.id,
                        Questionnaire.status.in_(ACTIVE_STATUSES),
                    )
                    .order_by(Questionnaire.created_at.desc())
                )
            if questionnaire is None:
                raise RuntimeError("active questionnaire claim failed")
            await session.flush()
            return context, TuneState(
                kind=TuneStateKind.GENERATING,
                questionnaire_id=questionnaire.id,
            )

    async def store_generated(
        self,
        questionnaire_id: UUID,
        questionnaire: QuestionnaireGenerationSchema,
        token_hashes: Sequence[Sequence[str]],
    ) -> TuneState:
        async with self._database.session() as session:
            entity = await session.get(Questionnaire, questionnaire_id)
            if entity is None or entity.status is not QuestionnaireStatus.GENERATING:
                raise AnswerRejected("questionnaire is no longer generating")
            for ordinal, (question, hashes) in enumerate(
                zip(questionnaire.questions, token_hashes, strict=True), start=1
            ):
                if len(hashes) != 4:
                    raise ValueError("exactly four callback tokens are required")
                question_entity = QuestionnaireQuestion(
                    questionnaire_id=entity.id,
                    ordinal=ordinal,
                    dimension_key=question.dimension_key,
                    text=question.text,
                )
                for option_ordinal, (option, token_hash) in enumerate(
                    zip(question.options, hashes, strict=True), start=1
                ):
                    question_entity.options.append(
                        QuestionOption(
                            ordinal=option_ordinal,
                            label=option.label,
                            normalized_label=self._normalize(option.label),
                            callback_token_hash=token_hash,
                        )
                    )
                session.add(question_entity)
            entity.status = QuestionnaireStatus.ANSWERING
            await session.flush()
            return await self._state(session, entity)

    async def record_answer(
        self,
        telegram_user_id: int,
        callback_token: str,
        answered_at: datetime,
    ) -> TuneState:
        async with self._database.session() as session:
            option = await session.scalar(
                select(QuestionOption)
                .join(QuestionnaireQuestion)
                .join(Questionnaire)
                .join(ApplicationUser)
                .where(
                    ApplicationUser.telegram_user_id == telegram_user_id,
                    QuestionOption.callback_token_hash == callback_token,
                )
                .options(
                    selectinload(QuestionOption.question).selectinload(
                        QuestionnaireQuestion.questionnaire
                    )
                )
            )
            if option is None:
                raise AnswerRejected("unknown callback token")
            questionnaire = option.question.questionnaire
            if questionnaire.status is QuestionnaireStatus.APPLIED:
                return TuneState(
                    TuneStateKind.COMPLETED,
                    questionnaire_id=questionnaire.id,
                )
            if questionnaire.status not in (
                QuestionnaireStatus.ANSWERING,
                QuestionnaireStatus.ANSWERS_COMPLETE,
                QuestionnaireStatus.INTERPRETING,
                QuestionnaireStatus.APPLYING,
            ):
                raise AnswerRejected("questionnaire is not accepting answers")

            existing = await session.scalar(
                select(QuestionnaireAnswer).where(
                    QuestionnaireAnswer.question_id == option.question_id
                )
            )
            if existing is not None:
                if existing.option_id != option.id:
                    raise AnswerRejected("question was already answered")
                return await self._state(session, questionnaire)

            next_question = await session.scalar(
                select(QuestionnaireQuestion)
                .outerjoin(QuestionnaireAnswer)
                .where(
                    QuestionnaireQuestion.questionnaire_id == questionnaire.id,
                    QuestionnaireAnswer.id.is_(None),
                )
                .order_by(QuestionnaireQuestion.ordinal)
                .limit(1)
            )
            if next_question is None or next_question.id != option.question_id:
                raise AnswerRejected("answer is out of order")
            session.add(
                QuestionnaireAnswer(
                    question_id=option.question_id,
                    option_id=option.id,
                    answered_at=answered_at,
                )
            )
            await session.flush()
            remaining = await session.scalar(
                select(func.count(QuestionnaireQuestion.id))
                .outerjoin(QuestionnaireAnswer)
                .where(
                    QuestionnaireQuestion.questionnaire_id == questionnaire.id,
                    QuestionnaireAnswer.id.is_(None),
                )
            )
            if remaining == 0:
                questionnaire.status = QuestionnaireStatus.ANSWERS_COMPLETE
            await session.flush()
            return await self._state(session, questionnaire)

    async def load_interpretation_input(
        self, questionnaire_id: UUID
    ) -> tuple[ProfileSnapshot, Sequence[tuple[str, str]]]:
        async with self._database.session() as session:
            questionnaire = await session.get(Questionnaire, questionnaire_id)
            if questionnaire is None or questionnaire.status not in (
                QuestionnaireStatus.ANSWERS_COMPLETE,
                QuestionnaireStatus.INTERPRETING,
            ):
                raise AnswerRejected("questionnaire answers are not complete")
            questionnaire.status = QuestionnaireStatus.INTERPRETING
            rows = (
                await session.execute(
                    select(QuestionnaireQuestion.text, QuestionOption.label)
                    .join(
                        QuestionnaireAnswer,
                        QuestionnaireAnswer.question_id == QuestionnaireQuestion.id,
                    )
                    .join(
                        QuestionOption,
                        QuestionOption.id == QuestionnaireAnswer.option_id,
                    )
                    .where(QuestionnaireQuestion.questionnaire_id == questionnaire.id)
                    .order_by(QuestionnaireQuestion.ordinal)
                )
            ).all()
            if len(rows) != 10:
                raise AnswerRejected("questionnaire requires exactly ten answers")
            return await self._snapshot(session, questionnaire.user_id), tuple(rows)

    async def apply_changes(
        self,
        questionnaire_id: UUID,
        proposal: PreferenceChangesSchema,
        applied_at: datetime,
    ) -> TuneState:
        async with self._database.session() as session:
            questionnaire = await session.scalar(
                select(Questionnaire)
                .where(Questionnaire.id == questionnaire_id)
                .with_for_update()
            )
            if questionnaire is None:
                raise PreferenceProposalInvalid("unknown questionnaire")
            existing_batch = await session.scalar(
                select(PreferenceUpdateBatch).where(
                    PreferenceUpdateBatch.questionnaire_id == questionnaire_id
                )
            )
            if existing_batch is not None:
                if existing_batch.status is UpdateBatchStatus.APPLIED:
                    return TuneState(
                        kind=TuneStateKind.COMPLETED,
                        questionnaire_id=questionnaire_id,
                    )
                raise PreferenceProposalInvalid("update batch already exists")
            profile = await session.scalar(
                select(PreferenceProfile)
                .where(PreferenceProfile.user_id == questionnaire.user_id)
                .with_for_update()
            )
            if profile is None or profile.revision != proposal.base_profile_revision:
                raise StaleProfileRevision("profile changed while tuning")

            parameters = {
                item.id: item
                for item in (
                    await session.scalars(
                        select(PreferenceParameterModel).where(
                            PreferenceParameterModel.user_id == questionnaire.user_id
                        )
                    )
                )
            }
            semantic_keys = {item.semantic_key for item in parameters.values()}
            self._prevalidate(proposal, parameters, semantic_keys)

            batch = PreferenceUpdateBatch(
                questionnaire_id=questionnaire.id,
                user_id=questionnaire.user_id,
                schema_version=proposal.schema_version,
                base_profile_revision=proposal.base_profile_revision,
                proposal_hash=proposal_hash(proposal),
                change_count=len(proposal.changes),
                status=UpdateBatchStatus.VALIDATED,
            )
            session.add(batch)
            await session.flush()
            questionnaire.status = QuestionnaireStatus.APPLYING

            audits: list[str] = []
            for change in proposal.changes:
                parameter, previous = await self._apply_change(
                    session,
                    questionnaire.user_id,
                    change,
                    parameters,
                    source=PreferenceOrigin.QUESTIONNAIRE,
                )
                current = self._parameter_state(parameter)
                history_id = uuid4()
                history = PreferenceChangeHistory(
                    id=history_id,
                    batch_id=batch.id,
                    parameter_id=parameter.id,
                    action=change.action,
                    source=PreferenceOrigin.QUESTIONNAIRE,
                    questionnaire_id=questionnaire.id,
                    previous_state=previous,
                    new_state=current,
                    reason=change.reason,
                    changed_at=applied_at,
                )
                audit = PreferenceChangeAudit(
                    id=history_id,
                    batch_id=batch.id,
                    parameter_id=parameter.id,
                    action=change.action,
                    source=PreferenceOrigin.QUESTIONNAIRE,
                    questionnaire_id=questionnaire.id,
                    previous_state_hash=self._state_hash(previous)
                    if previous
                    else None,
                    new_state_hash=self._state_hash(current),
                    reason_hash=self._hash(change.reason),
                    changed_at=applied_at,
                )
                session.add_all((history, audit))
                audits.append(
                    f"{history_id}:{audit.parameter_id}:{change.action}:"
                    f"{audit.previous_state_hash}:{audit.new_state_hash}:"
                    f"{audit.reason_hash}"
                )

            profile.revision += 1
            batch.resulting_profile_revision = profile.revision
            batch.history_digest = self._hash("\n".join(audits))
            batch.status = UpdateBatchStatus.APPLIED
            batch.applied_at = applied_at
            questionnaire.status = QuestionnaireStatus.APPLIED
            questionnaire.completed_at = applied_at
            await session.flush()
            return TuneState(
                kind=TuneStateKind.COMPLETED,
                questionnaire_id=questionnaire.id,
            )

    async def fail(
        self, questionnaire_id: UUID, error_code: str, failed_at: datetime
    ) -> TuneState:
        async with self._database.session() as session:
            questionnaire = await session.get(Questionnaire, questionnaire_id)
            if questionnaire is not None and questionnaire.status not in (
                QuestionnaireStatus.APPLIED,
                QuestionnaireStatus.FAILED,
            ):
                questionnaire.status = QuestionnaireStatus.FAILED
                questionnaire.error_code = error_code[:100]
                questionnaire.completed_at = failed_at
            return TuneState(
                kind=TuneStateKind.FAILED,
                questionnaire_id=questionnaire_id,
                message="Preference tuning failed. Start /tune to try again.",
            )

    async def claim_explicit_request(
        self,
        telegram_user_id: int,
        telegram_update_id: int,
        statement: str,
        language_code: str | None,
        claimed_at: datetime,
    ) -> ExplicitRequestClaim:
        normalized_hash = self._hash(self._normalize(statement))
        async with self._database.session() as session:
            user, profile = await self._ensure_user_profile(
                session,
                telegram_user_id=telegram_user_id,
                language_code=language_code,
            )
            existing = await session.scalar(
                select(ExplicitPreferenceRequest)
                .where(
                    ExplicitPreferenceRequest.user_id == user.id,
                    ExplicitPreferenceRequest.telegram_update_id == telegram_update_id,
                )
                .with_for_update()
            )
            if existing is not None:
                if existing.normalized_text_hash != normalized_hash:
                    raise PersistenceConflict(
                        "same telegram update cannot be reused for different text"
                    )
                return ExplicitRequestClaim(
                    existing.id,
                    await self._explicit_state(session, existing),
                )

            request = ExplicitPreferenceRequest(
                user_id=user.id,
                telegram_update_id=telegram_update_id,
                normalized_text_hash=normalized_hash,
                raw_text=statement,
                language_code=user.language_code,
                status=ExplicitRequestStatus.RECEIVED,
                schema_version="1.0",
                base_profile_revision=profile.revision,
                updated_at=claimed_at,
            )
            session.add(request)
            await session.flush()
            return ExplicitRequestClaim(request.id)

    async def load_explicit_context(
        self,
        request_id: UUID,
    ) -> tuple[ProfileSnapshot, Sequence[Mapping[str, Any]]]:
        async with self._database.session() as session:
            request = await session.scalar(
                select(ExplicitPreferenceRequest)
                .where(ExplicitPreferenceRequest.id == request_id)
                .with_for_update()
            )
            if request is None:
                raise PreferenceProposalInvalid("unknown explicit request")
            if request.status in (
                ExplicitRequestStatus.APPLIED,
                ExplicitRequestStatus.FAILED,
            ):
                raise PreferenceProposalInvalid("explicit request is already terminal")
            request.status = ExplicitRequestStatus.INTERPRETING
            request.interpretation_version = EXPLICIT_INTERPRETATION_VERSION
            request.error_code = None
            request.updated_at = datetime.now(UTC)
            profile = await self._snapshot(session, request.user_id)
            history = await self._explicit_history(session, request.user_id)
            return profile, history

    async def apply_explicit_changes(
        self,
        request_id: UUID,
        proposal: ExplicitPreferenceChangesSchema,
        applied_at: datetime,
    ) -> SpecifyState:
        stale_conflict = False
        async with self._database.session() as session:
            request = await session.scalar(
                select(ExplicitPreferenceRequest)
                .where(ExplicitPreferenceRequest.id == request_id)
                .with_for_update()
            )
            if request is None:
                raise PreferenceProposalInvalid("unknown explicit request")
            if request.status in (
                ExplicitRequestStatus.APPLIED,
                ExplicitRequestStatus.FAILED,
            ):
                return await self._explicit_state(session, request)

            existing_batch = await session.scalar(
                select(PreferenceUpdateBatch).where(
                    PreferenceUpdateBatch.explicit_request_id == request_id
                )
            )
            if (
                existing_batch is not None
                and existing_batch.status is UpdateBatchStatus.APPLIED
            ):
                request.status = ExplicitRequestStatus.APPLIED
                return await self._explicit_state(session, request)
            if existing_batch is not None:
                raise PreferenceProposalInvalid("update batch already exists")

            profile = await session.scalar(
                select(PreferenceProfile)
                .where(PreferenceProfile.user_id == request.user_id)
                .with_for_update()
            )
            if profile is None:
                raise RuntimeError("preference profile is missing")
            if profile.revision != proposal.base_profile_revision:
                request.status = ExplicitRequestStatus.STALE
                request.error_code = "stale_profile_revision"
                request.updated_at = applied_at
                stale_conflict = True
            if stale_conflict:
                await session.flush()
            else:
                parameters = {
                    item.id: item
                    for item in (
                        await session.scalars(
                            select(PreferenceParameterModel).where(
                                PreferenceParameterModel.user_id == request.user_id
                            )
                        )
                    )
                }
                profile_snapshot = ProfileSnapshot(
                    user_id=request.user_id,
                    revision=profile.revision,
                    parameters=tuple(
                        self._domain_parameter(item)
                        for item in sorted(
                            parameters.values(),
                            key=lambda parameter: parameter.created_at,
                        )
                    ),
                )
                validated = self._change_validator.validate(
                    proposal,
                    profile_snapshot,
                    request_id,
                    statement=request.raw_text or "",
                    duplicate_matches=self._local_duplicate_matches(
                        proposal,
                        profile_snapshot,
                    ),
                )
                request.status = ExplicitRequestStatus.VALIDATED
                request.proposal_hash = proposal_hash(validated)

                batch = PreferenceUpdateBatch(
                    explicit_request_id=request.id,
                    user_id=request.user_id,
                    schema_version=validated.schema_version,
                    base_profile_revision=validated.base_profile_revision,
                    proposal_hash=request.proposal_hash,
                    change_count=len(validated.changes),
                    status=UpdateBatchStatus.VALIDATED,
                )
                session.add(batch)
                await session.flush()
                request.status = ExplicitRequestStatus.APPLYING

                audits: list[str] = []
                for change in validated.changes:
                    parameter, previous = await self._apply_change(
                        session,
                        request.user_id,
                        change,
                        parameters,
                        source=PreferenceOrigin.EXPLICIT,
                    )
                    current = self._parameter_state(parameter)
                    history_id = uuid4()
                    history = PreferenceChangeHistory(
                        id=history_id,
                        batch_id=batch.id,
                        parameter_id=parameter.id,
                        action=change.action,
                        source=PreferenceOrigin.EXPLICIT,
                        explicit_request_id=request.id,
                        previous_state=previous,
                        new_state=current,
                        reason=change.reason,
                        changed_at=applied_at,
                    )
                    audit = PreferenceChangeAudit(
                        id=history_id,
                        batch_id=batch.id,
                        parameter_id=parameter.id,
                        action=change.action,
                        source=PreferenceOrigin.EXPLICIT,
                        explicit_request_id=request.id,
                        previous_state_hash=self._state_hash(previous)
                        if previous
                        else None,
                        new_state_hash=self._state_hash(current),
                        reason_hash=self._hash(change.reason),
                        changed_at=applied_at,
                    )
                    evidence = PreferenceEvidence(
                        id=history_id,
                        parameter_id=parameter.id,
                        user_id=request.user_id,
                        source=PreferenceOrigin.EXPLICIT,
                        explicit_request_id=request.id,
                        action=change.action,
                        requested_weight=(
                            change.weight if hasattr(change, "weight") else None
                        ),
                        active=parameter.active,
                        reason_hash=self._hash(change.reason),
                        created_at=applied_at,
                    )
                    session.add_all((history, audit, evidence))
                    audits.append(
                        f"{history_id}:{audit.parameter_id}:{change.action}:"
                        f"{audit.previous_state_hash}:{audit.new_state_hash}:"
                        f"{audit.reason_hash}"
                    )

                profile.revision += 1
                batch.resulting_profile_revision = profile.revision
                batch.history_digest = self._hash("\n".join(audits))
                batch.status = UpdateBatchStatus.APPLIED
                batch.applied_at = applied_at
                request.status = ExplicitRequestStatus.APPLIED
                request.error_code = None
                request.completed_at = applied_at
                request.updated_at = applied_at
                await session.flush()
                state = await self._explicit_state(session, request)
        if stale_conflict:
            raise StaleProfileRevision(
                "profile changed while applying explicit request"
            )
        return state

    async def complete_no_change(
        self,
        request_id: UUID,
        proposal_hash_value: str,
        completed_at: datetime,
    ) -> SpecifyState:
        async with self._database.session() as session:
            request = await session.scalar(
                select(ExplicitPreferenceRequest)
                .where(ExplicitPreferenceRequest.id == request_id)
                .with_for_update()
            )
            if request is None:
                raise PreferenceProposalInvalid("unknown explicit request")
            if request.status in (
                ExplicitRequestStatus.APPLIED,
                ExplicitRequestStatus.FAILED,
            ):
                return await self._explicit_state(session, request)
            request.status = ExplicitRequestStatus.APPLIED
            request.proposal_hash = proposal_hash_value
            request.error_code = "no_change"
            request.completed_at = completed_at
            request.updated_at = completed_at
            await session.flush()
            return await self._explicit_state(session, request)

    async def fail_explicit_request(
        self,
        request_id: UUID,
        error_code: str,
        failed_at: datetime,
    ) -> SpecifyState:
        async with self._database.session() as session:
            request = await session.get(ExplicitPreferenceRequest, request_id)
            if request is None:
                return SpecifyState(
                    SpecifyStateKind.FAILED,
                    request_id=request_id,
                    message="Preference update failed. Please try again soon.",
                )
            if request.status not in (
                ExplicitRequestStatus.APPLIED,
                ExplicitRequestStatus.FAILED,
            ):
                request.status = ExplicitRequestStatus.FAILED
                request.error_code = error_code[:100]
                request.completed_at = failed_at
                request.updated_at = failed_at
            return await self._explicit_state(session, request)

    async def duplicate_candidates(
        self,
        user_id: UUID,
        semantic_key: str,
        name: str,
        *,
        limit: int = 20,
    ) -> ProfileSnapshot:
        normalized_name = self._normalize(name)
        async with self._database.session() as session:
            profile = await session.get(PreferenceProfile, user_id)
            if profile is None:
                raise RuntimeError("preference profile is missing")
            similarity = func.similarity(
                func.lower(PreferenceParameterModel.name), normalized_name
            )
            rows = tuple(
                await session.scalars(
                    select(PreferenceParameterModel)
                    .where(
                        PreferenceParameterModel.user_id == user_id,
                        (PreferenceParameterModel.semantic_key == semantic_key)
                        | (similarity >= self._duplicate_threshold),
                    )
                    .order_by(similarity.desc(), PreferenceParameterModel.created_at)
                    .limit(limit)
                )
            )
            return ProfileSnapshot(
                user_id=user_id,
                revision=profile.revision,
                parameters=tuple(self._domain_parameter(item) for item in rows),
            )

    async def compact_retention(
        self,
        *,
        questionnaire_cutoff: datetime,
        history_cutoff: datetime | None,
        batch_size: int,
    ) -> RetentionResult:
        async with self._database.session() as session:
            questionnaire_ids = tuple(
                await session.scalars(
                    select(Questionnaire.id)
                    .where(
                        Questionnaire.completed_at < questionnaire_cutoff,
                        Questionnaire.status == QuestionnaireStatus.APPLIED,
                    )
                    .order_by(Questionnaire.completed_at)
                    .limit(batch_size)
                    .with_for_update(skip_locked=True)
                )
            )
            detail_count = 0
            if questionnaire_ids:
                question_ids = tuple(
                    await session.scalars(
                        select(QuestionnaireQuestion.id).where(
                            QuestionnaireQuestion.questionnaire_id.in_(
                                questionnaire_ids
                            )
                        )
                    )
                )
                detail_count = len(question_ids)
                if question_ids:
                    await session.execute(
                        delete(QuestionnaireQuestion).where(
                            QuestionnaireQuestion.id.in_(question_ids)
                        )
                    )

            remaining = max(0, batch_size - detail_count)
            failed_ids = tuple(
                await session.scalars(
                    select(Questionnaire.id)
                    .where(
                        Questionnaire.completed_at < questionnaire_cutoff,
                        Questionnaire.status == QuestionnaireStatus.FAILED,
                    )
                    .order_by(Questionnaire.completed_at)
                    .limit(remaining)
                    .with_for_update(skip_locked=True)
                )
            )
            if failed_ids:
                await session.execute(
                    delete(Questionnaire).where(Questionnaire.id.in_(failed_ids))
                )

            history_removed = 0
            audit_preserved = 0
            if history_cutoff is not None:
                history_rows = tuple(
                    await session.scalars(
                        select(PreferenceChangeHistory)
                        .where(PreferenceChangeHistory.changed_at < history_cutoff)
                        .order_by(PreferenceChangeHistory.changed_at)
                        .limit(batch_size)
                        .with_for_update(skip_locked=True)
                    )
                )
                if history_rows:
                    history_ids = tuple(row.id for row in history_rows)
                    audit_ids = set(
                        await session.scalars(
                            select(PreferenceChangeAudit.id).where(
                                PreferenceChangeAudit.id.in_(history_ids)
                            )
                        )
                    )
                    if audit_ids != set(history_ids):
                        raise RuntimeError(
                            "refusing history compaction without per-change audit"
                        )
                    await session.execute(
                        delete(PreferenceChangeHistory).where(
                            PreferenceChangeHistory.id.in_(history_ids)
                        )
                    )
                    history_removed = len(history_ids)
                    audit_preserved = len(audit_ids)

            return RetentionResult(
                questionnaire_details_removed=detail_count,
                failed_questionnaires_removed=len(failed_ids),
                full_history_rows_removed=history_removed,
                compact_audit_rows_preserved=audit_preserved,
            )

    async def _state(
        self,
        session: AsyncSession,
        questionnaire: Questionnaire,
    ) -> TuneState:
        if questionnaire.status is QuestionnaireStatus.GENERATING:
            return TuneState(
                TuneStateKind.GENERATING,
                questionnaire_id=questionnaire.id,
            )
        if questionnaire.status is QuestionnaireStatus.APPLIED:
            return TuneState(TuneStateKind.COMPLETED, questionnaire_id=questionnaire.id)
        if questionnaire.status is QuestionnaireStatus.FAILED:
            return TuneState(TuneStateKind.FAILED, questionnaire_id=questionnaire.id)
        question = await session.scalar(
            select(QuestionnaireQuestion)
            .outerjoin(QuestionnaireAnswer)
            .where(
                QuestionnaireQuestion.questionnaire_id == questionnaire.id,
                QuestionnaireAnswer.id.is_(None),
            )
            .order_by(QuestionnaireQuestion.ordinal)
            .limit(1)
            .options(selectinload(QuestionnaireQuestion.options))
        )
        if question is None:
            return TuneState(
                TuneStateKind.PROCESSING,
                questionnaire_id=questionnaire.id,
            )
        return TuneState(
            kind=TuneStateKind.QUESTION,
            questionnaire_id=questionnaire.id,
            ordinal=question.ordinal,
            question=question.text,
            options=tuple(
                TuneOption(
                    label=option.label,
                    callback_token=option.callback_token_hash,
                )
                for option in sorted(question.options, key=lambda item: item.ordinal)
            ),
        )

    async def _explicit_state(
        self,
        session: AsyncSession,
        request: ExplicitPreferenceRequest,
    ) -> SpecifyState:
        if request.status in ACTIVE_EXPLICIT_STATUSES:
            return SpecifyState(
                SpecifyStateKind.PROCESSING,
                request_id=request.id,
                message="Interpreting your explicit preference...",
            )
        if request.status is ExplicitRequestStatus.STALE:
            return SpecifyState(
                SpecifyStateKind.STALE_RETRY,
                request_id=request.id,
                message="Your profile changed while I was working, so I'm retrying once.",
            )
        if request.status is ExplicitRequestStatus.FAILED:
            if request.error_code in {"proposal_invalid", "statement_invalid"}:
                return SpecifyState(
                    SpecifyStateKind.INVALID,
                    request_id=request.id,
                    message="I couldn't convert that into a safe preference change.",
                )
            return SpecifyState(
                SpecifyStateKind.FAILED,
                request_id=request.id,
                message="Preference update failed. Please try again soon.",
            )
        if request.error_code == "no_change":
            return SpecifyState(
                SpecifyStateKind.NO_CHANGE,
                request_id=request.id,
                message="Your current preferences already cover this request.",
            )
        batch = await session.scalar(
            select(PreferenceUpdateBatch).where(
                PreferenceUpdateBatch.explicit_request_id == request.id
            )
        )
        if batch is not None:
            history = await session.scalar(
                select(PreferenceChangeHistory)
                .where(PreferenceChangeHistory.batch_id == batch.id)
                .order_by(PreferenceChangeHistory.changed_at.desc())
                .limit(1)
            )
            if history is not None:
                name = (history.new_state or {}).get("name") or (
                    history.previous_state or {}
                ).get("name")
                return SpecifyState(
                    SpecifyStateKind.APPLIED,
                    request_id=request.id,
                    action=history.action,
                    parameter_name=name,
                    message=(
                        f"Saved your explicit preference for {name}."
                        if name
                        else "Saved your explicit preference."
                    ),
                )
        return SpecifyState(
            SpecifyStateKind.APPLIED,
            request_id=request.id,
            message="Saved your explicit preference.",
        )

    async def _snapshot(self, session: AsyncSession, user_id: UUID) -> ProfileSnapshot:
        profile = await session.get(PreferenceProfile, user_id)
        if profile is None:
            raise RuntimeError("preference profile is missing")
        parameters = tuple(
            self._domain_parameter(item)
            for item in (
                await session.scalars(
                    select(PreferenceParameterModel)
                    .where(PreferenceParameterModel.user_id == user_id)
                    .order_by(PreferenceParameterModel.created_at)
                )
            )
        )
        return ProfileSnapshot(
            user_id=user_id,
            revision=profile.revision,
            parameters=parameters,
        )

    async def _prior_answers(
        self,
        session: AsyncSession,
        user_id: UUID,
    ) -> tuple[PriorAnswer, ...]:
        if self._history_context_limit == 0:
            return ()
        rows = (
            await session.execute(
                select(
                    QuestionnaireQuestion.text,
                    QuestionOption.label,
                    QuestionnaireQuestion.dimension_key,
                )
                .join(Questionnaire)
                .join(
                    QuestionnaireAnswer,
                    QuestionnaireAnswer.question_id == QuestionnaireQuestion.id,
                )
                .join(
                    QuestionOption,
                    QuestionOption.id == QuestionnaireAnswer.option_id,
                )
                .where(
                    Questionnaire.user_id == user_id,
                    Questionnaire.status == QuestionnaireStatus.APPLIED,
                )
                .order_by(QuestionnaireAnswer.answered_at.desc())
                .limit(self._history_context_limit)
            )
        ).all()
        return tuple(PriorAnswer(*row) for row in rows)

    async def _explicit_history(
        self,
        session: AsyncSession,
        user_id: UUID,
    ) -> tuple[dict[str, Any], ...]:
        if self._explicit_history_limit == 0:
            return ()
        rows = tuple(
            await session.scalars(
                select(PreferenceChangeHistory)
                .join(
                    PreferenceUpdateBatch,
                    PreferenceUpdateBatch.id == PreferenceChangeHistory.batch_id,
                )
                .where(PreferenceUpdateBatch.user_id == user_id)
                .order_by(PreferenceChangeHistory.changed_at.desc())
                .limit(self._explicit_history_limit)
            )
        )
        return tuple(
            {
                "action": row.action.value,
                "source": row.source.value,
                "parameter_id": str(row.parameter_id),
                "parameter_name": (
                    (row.new_state or {}).get("name")
                    or (row.previous_state or {}).get("name")
                ),
                "semantic_key": (
                    (row.new_state or {}).get("semantic_key")
                    or (row.previous_state or {}).get("semantic_key")
                ),
                "active": (row.new_state or {}).get("active"),
                "weight": (row.new_state or {}).get("weight"),
                "changed_at": row.changed_at.isoformat(),
            }
            for row in rows
        )

    async def _ensure_user_profile(
        self,
        session: AsyncSession,
        *,
        telegram_user_id: int,
        language_code: str | None,
    ) -> tuple[ApplicationUser, PreferenceProfile]:
        user_insert = insert(ApplicationUser).values(
            telegram_user_id=telegram_user_id,
            language_code=language_code,
        )
        user = (
            await session.execute(
                user_insert.on_conflict_do_update(
                    index_elements=[ApplicationUser.telegram_user_id],
                    set_={
                        "language_code": func.coalesce(
                            user_insert.excluded.language_code,
                            ApplicationUser.language_code,
                        )
                    },
                ).returning(ApplicationUser)
            )
        ).scalar_one()
        await session.execute(
            insert(PreferenceProfile)
            .values(user_id=user.id, revision=0)
            .on_conflict_do_nothing(index_elements=[PreferenceProfile.user_id])
        )
        await session.flush()
        profile = await session.get(PreferenceProfile, user.id)
        if profile is None:
            raise RuntimeError("preference profile claim failed")
        return user, profile

    @staticmethod
    def _prevalidate(
        proposal: PreferenceChangesSchema,
        parameters: dict[UUID, PreferenceParameterModel],
        semantic_keys: set[str],
    ) -> None:
        seen_targets: set[UUID] = set()
        for change in proposal.changes:
            if isinstance(change, CreateChangeSchema):
                if change.semantic_key in semantic_keys:
                    raise PreferenceProposalInvalid(
                        "equivalent preference parameter already exists"
                    )
                semantic_keys.add(change.semantic_key)
                continue
            if change.parameter_id in seen_targets:
                raise PreferenceProposalInvalid(
                    "one batch cannot mutate a parameter more than once"
                )
            seen_targets.add(change.parameter_id)
            parameter = parameters.get(change.parameter_id)
            if parameter is None:
                raise PreferenceProposalInvalid("unknown preference parameter")
            if parameter.origin is not PreferenceOrigin.QUESTIONNAIRE:
                raise PreferenceProposalInvalid(
                    "questionnaire cannot mutate a protected preference"
                )

    @staticmethod
    def _local_duplicate_matches(
        proposal: ExplicitPreferenceChangesSchema,
        profile: ProfileSnapshot,
    ) -> dict[int, UUID]:
        matches: dict[int, UUID] = {}
        for index, change in enumerate(proposal.changes):
            if not isinstance(change, CreateChangeSchema):
                continue
            normalized_key = normalize_semantic_key(change.semantic_key)
            normalized_name = SQLAlchemyPreferenceRepository._normalize(change.name)
            for parameter in profile.parameters:
                if (
                    normalize_semantic_key(parameter.semantic_key) == normalized_key
                    or SQLAlchemyPreferenceRepository._normalize(parameter.name)
                    == normalized_name
                ):
                    matches[index] = parameter.id
                    break
        return matches

    @staticmethod
    async def _apply_change(
        session: AsyncSession,
        user_id: UUID,
        change,
        parameters: dict[UUID, PreferenceParameterModel],
        *,
        source: PreferenceOrigin,
    ) -> tuple[PreferenceParameterModel, dict[str, Any] | None]:
        if isinstance(change, CreateChangeSchema):
            parameter = PreferenceParameterModel(
                user_id=user_id,
                semantic_key=change.semantic_key,
                name=change.name,
                description=change.description,
                evaluation_instructions=change.evaluation_instructions,
                weight=change.weight,
                origin=source,
                active=True,
            )
            session.add(parameter)
            await session.flush()
            parameters[parameter.id] = parameter
            return parameter, None

        parameter = parameters[change.parameter_id]
        previous = SQLAlchemyPreferenceRepository._parameter_state(parameter)
        if isinstance(change, AdjustChangeSchema):
            parameter.weight = change.weight
        elif isinstance(change, RefineChangeSchema):
            if change.name is not None:
                parameter.name = change.name
            if change.description is not None:
                parameter.description = change.description
            if change.evaluation_instructions is not None:
                parameter.evaluation_instructions = change.evaluation_instructions
        elif isinstance(change, DeactivateChangeSchema):
            parameter.active = False
        elif isinstance(change, ReactivateChangeSchema):
            parameter.active = True
        else:
            raise PreferenceProposalInvalid("unsupported change action")
        return parameter, previous

    @staticmethod
    def _domain_parameter(item: PreferenceParameterModel) -> PreferenceParameter:
        return PreferenceParameter(
            id=item.id,
            user_id=item.user_id,
            semantic_key=item.semantic_key,
            name=item.name,
            description=item.description,
            evaluation_instructions=item.evaluation_instructions,
            weight=Decimal(item.weight),
            origin=item.origin,
            active=item.active,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )

    @staticmethod
    def _parameter_state(item: PreferenceParameterModel) -> dict[str, Any]:
        return {
            "semantic_key": item.semantic_key,
            "name": item.name,
            "description": item.description,
            "evaluation_instructions": item.evaluation_instructions,
            "weight": f"{item.weight:.2f}",
            "origin": item.origin.value,
            "active": item.active,
        }

    @staticmethod
    def _context_hash(context: QuestionnaireContext) -> str:
        payload = {
            "revision": context.profile.revision,
            "parameter_ids": [str(item.id) for item in context.profile.parameters],
            "prior_answers": [
                (item.question, item.selected_option, item.dimension_key)
                for item in context.prior_answers
            ],
        }
        return SQLAlchemyPreferenceRepository._state_hash(payload)

    @staticmethod
    def _state_hash(value: Mapping[str, Any] | None) -> str:
        if value is None:
            return ""
        return hashlib.sha256(
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode()
        ).hexdigest()

    @staticmethod
    def _hash(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    @staticmethod
    def _normalize(value: str) -> str:
        return " ".join(value.casefold().split())


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)
