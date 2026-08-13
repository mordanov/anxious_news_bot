from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
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
    PreferenceOrigin,
    PreferenceParameter,
    PriorAnswer,
    ProfileSnapshot,
    QuestionnaireContext,
    QuestionnaireStatus,
    RetentionResult,
    TuneOption,
    TuneState,
    TuneStateKind,
    UpdateBatchStatus,
)
from anxious_news_bot.preferences.errors import (
    AnswerRejected,
    PreferenceProposalInvalid,
    StaleProfileRevision,
)
from anxious_news_bot.preferences.infrastructure.models import (
    ApplicationUser,
    PreferenceChangeAudit,
    PreferenceChangeHistory,
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
    PreferenceChangesSchema,
    QuestionnaireGenerationSchema,
    ReactivateChangeSchema,
    RefineChangeSchema,
)
from anxious_news_bot.preferences.services.apply_changes import proposal_hash

ACTIVE_STATUSES = (
    QuestionnaireStatus.GENERATING,
    QuestionnaireStatus.ANSWERING,
    QuestionnaireStatus.ANSWERS_COMPLETE,
    QuestionnaireStatus.INTERPRETING,
    QuestionnaireStatus.APPLYING,
)


class SQLAlchemyPreferenceRepository:
    def __init__(
        self,
        database: Database,
        *,
        history_context_limit: int = 20,
        duplicate_threshold: float = 0.72,
    ) -> None:
        self._database = database
        self._history_context_limit = history_context_limit
        self._duplicate_threshold = duplicate_threshold

    async def start_or_resume(
        self, telegram_user_id: int, language_code: str | None
    ) -> tuple[QuestionnaireContext, TuneState]:
        async with self._database.session() as session:
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
                    session, questionnaire.user_id, change, parameters
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
        self, session: AsyncSession, questionnaire: Questionnaire
    ) -> TuneState:
        if questionnaire.status is QuestionnaireStatus.GENERATING:
            return TuneState(
                TuneStateKind.GENERATING, questionnaire_id=questionnaire.id
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
                TuneStateKind.PROCESSING, questionnaire_id=questionnaire.id
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
        self, session: AsyncSession, user_id: UUID
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
                    QuestionOption, QuestionOption.id == QuestionnaireAnswer.option_id
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
    async def _apply_change(
        session: AsyncSession,
        user_id: UUID,
        change,
        parameters: dict[UUID, PreferenceParameterModel],
    ) -> tuple[PreferenceParameterModel, dict[str, Any] | None]:
        if isinstance(change, CreateChangeSchema):
            parameter = PreferenceParameterModel(
                user_id=user_id,
                semantic_key=change.semantic_key,
                name=change.name,
                description=change.description,
                evaluation_instructions=change.evaluation_instructions,
                weight=change.weight,
                origin=PreferenceOrigin.QUESTIONNAIRE,
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
    def _state_hash(value: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(
                value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
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
