from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    text as sql_text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from anxious_news_bot.infrastructure.database import Base, TimestampMixin
from anxious_news_bot.preferences.domain import (
    PreferenceAction,
    PreferenceOrigin,
    QuestionnaireStatus,
    UpdateBatchStatus,
)


def _enum(enum_class: type, name: str) -> Enum:
    return Enum(
        enum_class,
        name=name,
        values_callable=lambda members: [member.value for member in members],
        validate_strings=True,
    )


class ApplicationUser(TimestampMixin, Base):
    __tablename__ = "application_users"

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    telegram_user_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, unique=True
    )
    language_code: Mapped[str | None] = mapped_column(String(35))

    profile: Mapped[PreferenceProfile | None] = relationship(back_populates="user")
    questionnaires: Mapped[list[Questionnaire]] = relationship(back_populates="user")


class PreferenceProfile(TimestampMixin, Base):
    __tablename__ = "preference_profiles"
    __table_args__ = (
        CheckConstraint("revision >= 0", name="ck_preference_profiles_revision"),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("application_users.id", ondelete="CASCADE"), primary_key=True
    )
    revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=sql_text("0")
    )

    user: Mapped[ApplicationUser] = relationship(back_populates="profile")
    parameters: Mapped[list[PreferenceParameter]] = relationship(
        back_populates="profile"
    )


class PreferenceParameter(TimestampMixin, Base):
    __tablename__ = "preference_parameters"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "semantic_key", name="uq_preference_parameters_user_semantic"
        ),
        CheckConstraint(
            "weight >= -1.00 AND weight <= 1.00",
            name="ck_preference_parameters_weight",
        ),
        CheckConstraint(
            "length(btrim(name)) > 0 "
            "AND length(btrim(description)) > 0 "
            "AND length(btrim(evaluation_instructions)) > 0",
            name="ck_preference_parameters_text",
        ),
        Index("ix_preference_parameters_user_active", "user_id", "active"),
        Index(
            "ix_preference_parameters_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("preference_profiles.user_id", ondelete="CASCADE"), nullable=False
    )
    semantic_key: Mapped[str] = mapped_column(String(160), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    evaluation_instructions: Mapped[str] = mapped_column(Text, nullable=False)
    weight: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False)
    origin: Mapped[PreferenceOrigin] = mapped_column(
        _enum(PreferenceOrigin, "preference_origin"), nullable=False
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=sql_text("true")
    )

    profile: Mapped[PreferenceProfile] = relationship(back_populates="parameters")


class Questionnaire(TimestampMixin, Base):
    __tablename__ = "preference_questionnaires"
    __table_args__ = (
        CheckConstraint(
            "profile_revision >= 0", name="ck_questionnaires_profile_revision"
        ),
        Index(
            "uq_questionnaires_user_active",
            "user_id",
            unique=True,
            postgresql_where=sql_text(
                "status IN ('generating', 'answering', 'answers_complete', "
                "'interpreting', 'applying')"
            ),
        ),
        Index("ix_questionnaires_status_updated", "status", "updated_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("application_users.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[QuestionnaireStatus] = mapped_column(
        _enum(QuestionnaireStatus, "questionnaire_status"), nullable=False
    )
    schema_version: Mapped[str] = mapped_column(
        String(20), nullable=False, default="1.0", server_default=sql_text("'1.0'")
    )
    profile_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    generation_context_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(100))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[ApplicationUser] = relationship(back_populates="questionnaires")
    questions: Mapped[list[QuestionnaireQuestion]] = relationship(
        back_populates="questionnaire",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    update_batch: Mapped[PreferenceUpdateBatch | None] = relationship(
        back_populates="questionnaire"
    )


class QuestionnaireQuestion(Base):
    __tablename__ = "preference_questions"
    __table_args__ = (
        UniqueConstraint(
            "questionnaire_id", "ordinal", name="uq_questions_questionnaire_ordinal"
        ),
        CheckConstraint("ordinal BETWEEN 1 AND 10", name="ck_questions_ordinal"),
        CheckConstraint("length(btrim(text)) > 0", name="ck_questions_text"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    questionnaire_id: Mapped[UUID] = mapped_column(
        ForeignKey("preference_questionnaires.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    dimension_key: Mapped[str] = mapped_column(String(100), nullable=False)
    text: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sql_text("now()")
    )

    questionnaire: Mapped[Questionnaire] = relationship(back_populates="questions")
    options: Mapped[list[QuestionOption]] = relationship(
        back_populates="question",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    answer: Mapped[QuestionnaireAnswer | None] = relationship(
        back_populates="question",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class QuestionOption(Base):
    __tablename__ = "preference_question_options"
    __table_args__ = (
        UniqueConstraint("id", "question_id", name="uq_options_id_question"),
        UniqueConstraint("question_id", "ordinal", name="uq_options_question_ordinal"),
        UniqueConstraint(
            "question_id", "normalized_label", name="uq_options_question_label"
        ),
        CheckConstraint("ordinal BETWEEN 1 AND 4", name="ck_options_ordinal"),
        CheckConstraint("length(btrim(label)) > 0", name="ck_options_label"),
        Index("ix_options_callback_token_hash", "callback_token_hash", unique=True),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    question_id: Mapped[UUID] = mapped_column(
        ForeignKey("preference_questions.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    normalized_label: Mapped[str] = mapped_column(String(80), nullable=False)
    callback_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sql_text("now()")
    )

    question: Mapped[QuestionnaireQuestion] = relationship(back_populates="options")


class QuestionnaireAnswer(Base):
    __tablename__ = "preference_answers"
    __table_args__ = (
        ForeignKeyConstraint(
            ["option_id", "question_id"],
            [
                "preference_question_options.id",
                "preference_question_options.question_id",
            ],
            ondelete="CASCADE",
            name="fk_answers_option_question",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    question_id: Mapped[UUID] = mapped_column(
        ForeignKey("preference_questions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    option_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    answered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    question: Mapped[QuestionnaireQuestion] = relationship(back_populates="answer")


class PreferenceUpdateBatch(Base):
    __tablename__ = "preference_update_batches"
    __table_args__ = (
        CheckConstraint(
            "base_profile_revision >= 0", name="ck_update_batches_base_revision"
        ),
        CheckConstraint(
            "resulting_profile_revision IS NULL OR "
            "resulting_profile_revision = base_profile_revision + 1",
            name="ck_update_batches_result_revision",
        ),
        CheckConstraint("change_count >= 0", name="ck_update_batches_change_count"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    questionnaire_id: Mapped[UUID] = mapped_column(
        ForeignKey("preference_questionnaires.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("preference_profiles.user_id", ondelete="CASCADE"), nullable=False
    )
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False)
    base_profile_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    resulting_profile_revision: Mapped[int | None] = mapped_column(Integer)
    proposal_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    change_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=sql_text("0")
    )
    history_digest: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[UpdateBatchStatus] = mapped_column(
        _enum(UpdateBatchStatus, "preference_update_batch_status"), nullable=False
    )
    error_code: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sql_text("now()")
    )
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    questionnaire: Mapped[Questionnaire] = relationship(back_populates="update_batch")
    history: Mapped[list[PreferenceChangeHistory]] = relationship(
        back_populates="batch"
    )
    audit: Mapped[list[PreferenceChangeAudit]] = relationship(back_populates="batch")


class PreferenceChangeHistory(Base):
    __tablename__ = "preference_change_history"
    __table_args__ = (
        UniqueConstraint(
            "batch_id",
            "parameter_id",
            "action",
            name="uq_preference_history_batch_parameter_action",
        ),
        CheckConstraint("length(btrim(reason)) > 0", name="ck_history_reason"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    batch_id: Mapped[UUID] = mapped_column(
        ForeignKey("preference_update_batches.id", ondelete="CASCADE"), nullable=False
    )
    parameter_id: Mapped[UUID] = mapped_column(
        ForeignKey("preference_parameters.id", ondelete="RESTRICT"), nullable=False
    )
    action: Mapped[PreferenceAction] = mapped_column(
        _enum(PreferenceAction, "preference_action"), nullable=False
    )
    source: Mapped[PreferenceOrigin] = mapped_column(
        _enum(PreferenceOrigin, "preference_history_source"), nullable=False
    )
    questionnaire_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("preference_questionnaires.id", ondelete="RESTRICT")
    )
    previous_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    new_state: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    batch: Mapped[PreferenceUpdateBatch] = relationship(back_populates="history")


class PreferenceChangeAudit(Base):
    __tablename__ = "preference_change_audit"
    __table_args__ = (
        UniqueConstraint(
            "batch_id",
            "parameter_id",
            "action",
            name="uq_preference_audit_batch_parameter_action",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    batch_id: Mapped[UUID] = mapped_column(
        ForeignKey("preference_update_batches.id", ondelete="RESTRICT"), nullable=False
    )
    parameter_id: Mapped[UUID] = mapped_column(
        ForeignKey("preference_parameters.id", ondelete="RESTRICT"), nullable=False
    )
    action: Mapped[PreferenceAction] = mapped_column(
        _enum(PreferenceAction, "preference_audit_action"), nullable=False
    )
    source: Mapped[PreferenceOrigin] = mapped_column(
        _enum(PreferenceOrigin, "preference_audit_source"), nullable=False
    )
    questionnaire_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("preference_questionnaires.id", ondelete="RESTRICT")
    )
    previous_state_hash: Mapped[str | None] = mapped_column(String(64))
    new_state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    batch: Mapped[PreferenceUpdateBatch] = relationship(back_populates="audit")
