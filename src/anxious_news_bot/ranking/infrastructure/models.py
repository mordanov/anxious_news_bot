from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from anxious_news_bot.infrastructure.database import Base, TimestampMixin
from anxious_news_bot.preferences.domain import PreferenceOrigin
from anxious_news_bot.ranking.domain import (
    EvaluationAttemptStatus,
    EvaluationStatus,
    PersonalState,
    RankingStatus,
)


def _enum(enum_class: type, name: str) -> Enum:
    return Enum(
        enum_class,
        name=name,
        values_callable=lambda members: [member.value for member in members],
        validate_strings=True,
    )


class ArticlePreferenceEvaluationRun(TimestampMixin, Base):
    __tablename__ = "article_preference_evaluation_runs"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "article_id",
            "article_analysis_id",
            "profile_revision",
            "parameter_set_hash",
            "schema_version",
            "evaluator_name",
            "evaluator_version",
            "prompt_version",
            name="uq_article_preference_evaluation_runs_version",
        ),
        CheckConstraint(
            "profile_revision >= 0",
            name="ck_article_preference_evaluation_runs_profile_revision",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_article_preference_evaluation_runs_attempt_count",
        ),
        CheckConstraint(
            "length(parameter_set_hash) = 64",
            name="ck_article_preference_evaluation_runs_parameter_set_hash",
        ),
        Index(
            "ix_article_preference_evaluation_runs_user_article_status",
            "user_id",
            "article_id",
            "status",
        ),
        Index(
            "ix_article_preference_evaluation_runs_status_updated",
            "status",
            "updated_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("preference_profiles.user_id", ondelete="CASCADE"), nullable=False
    )
    article_id: Mapped[UUID] = mapped_column(
        ForeignKey("normalized_articles.id", ondelete="CASCADE"), nullable=False
    )
    article_analysis_id: Mapped[UUID] = mapped_column(
        ForeignKey("article_analyses.id", ondelete="RESTRICT"), nullable=False
    )
    profile_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    parameter_set_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False)
    evaluator_name: Mapped[str] = mapped_column(String(100), nullable=False)
    evaluator_version: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[EvaluationStatus] = mapped_column(
        _enum(EvaluationStatus, "article_preference_evaluation_status"),
        nullable=False,
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=sql_text("0")
    )
    accepted_attempt_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "article_preference_evaluation_attempts.id",
            name="fk_article_preference_evaluation_runs_accepted_attempt",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        unique=True,
    )
    error_code: Mapped[str | None] = mapped_column(String(100))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    attempts: Mapped[list[ArticlePreferenceEvaluationAttempt]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        foreign_keys="ArticlePreferenceEvaluationAttempt.run_id",
    )
    accepted_attempt: Mapped[ArticlePreferenceEvaluationAttempt | None] = relationship(
        foreign_keys=[accepted_attempt_id],
        post_update=True,
    )
    relevances: Mapped[list[ArticleParameterRelevance]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ArticlePreferenceEvaluationAttempt(Base):
    __tablename__ = "article_preference_evaluation_attempts"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "ordinal",
            name="uq_article_preference_evaluation_attempts_run_ordinal",
        ),
        CheckConstraint(
            "ordinal > 0",
            name="ck_article_preference_evaluation_attempts_ordinal",
        ),
        CheckConstraint(
            "response_hash IS NULL OR length(response_hash) = 64",
            name="ck_article_preference_evaluation_attempts_response_hash",
        ),
        Index(
            "ix_article_preference_evaluation_attempts_status_completed",
            "status",
            "completed_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("article_preference_evaluation_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    response_hash: Mapped[str | None] = mapped_column(String(64))
    raw_response: Mapped[dict[str, Any] | list[Any] | str | None] = mapped_column(JSONB)
    status: Mapped[EvaluationAttemptStatus] = mapped_column(
        _enum(
            EvaluationAttemptStatus,
            "article_preference_evaluation_attempt_status",
        ),
        nullable=False,
    )
    error_code: Mapped[str | None] = mapped_column(String(100))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    run: Mapped[ArticlePreferenceEvaluationRun] = relationship(
        back_populates="attempts",
        foreign_keys=[run_id],
    )


class ArticleParameterRelevance(Base):
    __tablename__ = "article_parameter_relevances"
    __table_args__ = (
        UniqueConstraint(
            "evaluation_run_id",
            "parameter_id",
            name="uq_article_parameter_relevances_run_parameter",
        ),
        CheckConstraint(
            "length(parameter_snapshot_hash) = 64",
            name="ck_article_parameter_relevances_snapshot_hash",
        ),
        CheckConstraint(
            "relevance >= -1.0000 AND relevance <= 1.0000",
            name="ck_article_parameter_relevances_relevance",
        ),
        CheckConstraint(
            "length(btrim(reason_code)) > 0",
            name="ck_article_parameter_relevances_reason_code",
        ),
        Index(
            "ix_article_parameter_relevances_run",
            "evaluation_run_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    evaluation_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("article_preference_evaluation_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    parameter_id: Mapped[UUID] = mapped_column(
        ForeignKey("preference_parameters.id", ondelete="RESTRICT"), nullable=False
    )
    parameter_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    relevance: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sql_text("now()")
    )

    run: Mapped[ArticlePreferenceEvaluationRun] = relationship(
        back_populates="relevances"
    )


class RankingConfigurationSnapshot(Base):
    __tablename__ = "ranking_configuration_snapshots"
    __table_args__ = (
        CheckConstraint(
            "length(configuration_hash) = 64",
            name="ck_ranking_configuration_snapshots_hash",
        ),
        CheckConstraint(
            "personal_coefficient >= 0 AND personal_coefficient <= 1 AND "
            "importance_coefficient >= 0 AND importance_coefficient <= 1 AND "
            "freshness_coefficient >= 0 AND freshness_coefficient <= 1 AND "
            "quality_coefficient >= 0 AND quality_coefficient <= 1 AND "
            "novelty_coefficient >= 0 AND novelty_coefficient <= 1",
            name="ck_ranking_configuration_snapshots_coefficients",
        ),
        CheckConstraint(
            "personal_coefficient + importance_coefficient + freshness_coefficient + quality_coefficient + novelty_coefficient = 1.00000",
            name="ck_ranking_configuration_snapshots_coefficient_sum",
        ),
        CheckConstraint(
            "personal_coefficient >= 0.40000",
            name="ck_ranking_configuration_snapshots_personal_floor",
        ),
        CheckConstraint(
            "freshness_horizon_seconds > 0",
            name="ck_ranking_configuration_snapshots_freshness_horizon",
        ),
        CheckConstraint(
            "future_tolerance_seconds >= 0",
            name="ck_ranking_configuration_snapshots_future_tolerance",
        ),
        CheckConstraint(
            "minimum_source_quality >= 0 AND minimum_source_quality <= 1",
            name="ck_ranking_configuration_snapshots_minimum_source_quality",
        ),
        CheckConstraint(
            "maximum_candidate_count > 0 AND maximum_candidate_count <= 500",
            name="ck_ranking_configuration_snapshots_candidate_count",
        ),
        CheckConstraint(
            "event_cap > 0 AND topic_cap > 0 AND source_cap > 0",
            name="ck_ranking_configuration_snapshots_caps",
        ),
        CheckConstraint(
            "explicit_weight_threshold >= 0 AND explicit_weight_threshold <= 1",
            name="ck_ranking_configuration_snapshots_weight_threshold",
        ),
        CheckConstraint(
            "explicit_relevance_threshold >= 0 AND explicit_relevance_threshold <= 1",
            name="ck_ranking_configuration_snapshots_relevance_threshold",
        ),
        CheckConstraint(
            "explanation_contribution_limit > 0 AND explanation_contribution_limit <= 10",
            name="ck_ranking_configuration_snapshots_explanation_limit",
        ),
        UniqueConstraint(
            "configuration_hash",
            name="uq_ranking_configuration_snapshots_hash",
        ),
    )

    version: Mapped[str] = mapped_column(String(100), primary_key=True)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    personal_coefficient: Mapped[Decimal] = mapped_column(Numeric(6, 5), nullable=False)
    importance_coefficient: Mapped[Decimal] = mapped_column(
        Numeric(6, 5), nullable=False
    )
    freshness_coefficient: Mapped[Decimal] = mapped_column(
        Numeric(6, 5), nullable=False
    )
    quality_coefficient: Mapped[Decimal] = mapped_column(Numeric(6, 5), nullable=False)
    novelty_coefficient: Mapped[Decimal] = mapped_column(Numeric(6, 5), nullable=False)
    freshness_horizon_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    future_tolerance_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    minimum_source_quality: Mapped[Decimal] = mapped_column(
        Numeric(6, 5), nullable=False
    )
    maximum_candidate_count: Mapped[int] = mapped_column(Integer, nullable=False)
    event_cap: Mapped[int] = mapped_column(Integer, nullable=False)
    topic_cap: Mapped[int] = mapped_column(Integer, nullable=False)
    source_cap: Mapped[int] = mapped_column(Integer, nullable=False)
    explicit_weight_threshold: Mapped[Decimal] = mapped_column(
        Numeric(3, 2), nullable=False
    )
    explicit_relevance_threshold: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), nullable=False
    )
    explanation_contribution_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    tie_policy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    retention_policy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sql_text("now()")
    )

    runs: Mapped[list[RankingRun]] = relationship(back_populates="configuration")


class RankingRun(TimestampMixin, Base):
    __tablename__ = "ranking_runs"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "request_id",
            name="uq_ranking_runs_user_request",
        ),
        UniqueConstraint(
            "user_id",
            "profile_revision",
            "candidate_set_hash",
            "configuration_version",
            "ranking_at",
            "requested_count",
            name="uq_ranking_runs_snapshot",
        ),
        CheckConstraint(
            "profile_revision >= 0",
            name="ck_ranking_runs_profile_revision",
        ),
        CheckConstraint(
            "length(candidate_set_hash) = 64",
            name="ck_ranking_runs_candidate_set_hash",
        ),
        CheckConstraint(
            "requested_count > 0",
            name="ck_ranking_runs_requested_count",
        ),
        CheckConstraint(
            "selected_count >= 0 AND excluded_count >= 0",
            name="ck_ranking_runs_counts",
        ),
        CheckConstraint(
            "selected_count <= requested_count",
            name="ck_ranking_runs_selected_count",
        ),
        Index(
            "ix_ranking_runs_user_status_created",
            "user_id",
            "status",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    request_id: Mapped[str] = mapped_column(String(200), nullable=False)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("preference_profiles.user_id", ondelete="CASCADE"), nullable=False
    )
    profile_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    candidate_set_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    configuration_version: Mapped[str] = mapped_column(
        ForeignKey("ranking_configuration_snapshots.version", ondelete="RESTRICT"),
        nullable=False,
    )
    ranking_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    requested_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[RankingStatus] = mapped_column(
        _enum(RankingStatus, "ranking_run_status"), nullable=False
    )
    selected_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=sql_text("0")
    )
    excluded_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=sql_text("0")
    )
    selected_cap_vector: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    unsatisfied_limits: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=sql_text("'[]'::jsonb"),
    )
    error_code: Mapped[str | None] = mapped_column(String(100))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    configuration: Mapped[RankingConfigurationSnapshot] = relationship(
        back_populates="runs"
    )
    records: Mapped[list[ArticleRankingRecord]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ArticleRankingRecord(Base):
    __tablename__ = "article_ranking_records"
    __table_args__ = (
        UniqueConstraint(
            "ranking_run_id",
            "article_id",
            name="uq_article_ranking_records_run_article",
        ),
        CheckConstraint(
            "personal_denominator >= 0",
            name="ck_article_ranking_records_personal_denominator",
        ),
        CheckConstraint(
            "personal_signed >= -1.00000000 AND personal_signed <= 1.00000000",
            name="ck_article_ranking_records_personal_signed",
        ),
        CheckConstraint(
            "personal_factor >= 0 AND personal_factor <= 1",
            name="ck_article_ranking_records_personal_factor",
        ),
        CheckConstraint(
            "importance >= 0 AND importance <= 1 AND freshness >= 0 AND freshness <= 1 AND quality >= 0 AND quality <= 1 AND novelty >= 0 AND novelty <= 1",
            name="ck_article_ranking_records_factors",
        ),
        CheckConstraint(
            "unrounded_score >= 0 AND unrounded_score <= 1 AND final_score >= 0 AND final_score <= 1",
            name="ck_article_ranking_records_scores",
        ),
        CheckConstraint(
            "initial_position IS NULL OR initial_position > 0",
            name="ck_article_ranking_records_initial_position",
        ),
        CheckConstraint(
            "final_position IS NULL OR final_position > 0",
            name="ck_article_ranking_records_final_position",
        ),
        CheckConstraint(
            "final_position IS NULL OR eligible",
            name="ck_article_ranking_records_final_position_requires_eligibility",
        ),
        CheckConstraint(
            "(personal_state = 'complete' AND "
            "(evaluation_run_id IS NOT NULL OR NOT eligible)) OR "
            "personal_state IN ('no_active_parameters', 'all_weights_zero')",
            name="ck_article_ranking_records_personal_state_evaluation",
        ),
        Index(
            "ix_article_ranking_records_run_score",
            "ranking_run_id",
            "eligible",
            "final_score",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    ranking_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("ranking_runs.id", ondelete="CASCADE"), nullable=False
    )
    article_id: Mapped[UUID] = mapped_column(
        ForeignKey("normalized_articles.id", ondelete="RESTRICT"), nullable=False
    )
    article_analysis_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("article_analyses.id", ondelete="RESTRICT")
    )
    evaluation_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("article_preference_evaluation_runs.id", ondelete="RESTRICT")
    )
    event_group_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("event_groups.id", ondelete="RESTRICT")
    )
    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("news_sources.id", ondelete="RESTRICT"), nullable=False
    )
    topic_key: Mapped[str | None] = mapped_column(String(160))
    personal_numerator: Mapped[Decimal] = mapped_column(Numeric(28, 8), nullable=False)
    personal_denominator: Mapped[Decimal] = mapped_column(
        Numeric(28, 8), nullable=False
    )
    personal_state: Mapped[PersonalState] = mapped_column(
        _enum(PersonalState, "ranking_personal_state"), nullable=False
    )
    personal_signed: Mapped[Decimal] = mapped_column(Numeric(10, 8), nullable=False)
    personal_factor: Mapped[Decimal] = mapped_column(Numeric(10, 8), nullable=False)
    importance: Mapped[Decimal] = mapped_column(Numeric(10, 8), nullable=False)
    freshness: Mapped[Decimal] = mapped_column(Numeric(10, 8), nullable=False)
    quality: Mapped[Decimal] = mapped_column(Numeric(10, 8), nullable=False)
    novelty: Mapped[Decimal] = mapped_column(Numeric(10, 8), nullable=False)
    unrounded_score: Mapped[Decimal] = mapped_column(Numeric(28, 16), nullable=False)
    final_score: Mapped[Decimal] = mapped_column(Numeric(10, 8), nullable=False)
    eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    eligibility_reason: Mapped[str] = mapped_column(String(100), nullable=False)
    explicit_protected: Mapped[bool] = mapped_column(Boolean, nullable=False)
    explicit_veto: Mapped[bool] = mapped_column(Boolean, nullable=False)
    initial_position: Mapped[int | None] = mapped_column(Integer)
    final_position: Mapped[int | None] = mapped_column(Integer)
    selection_reason: Mapped[str] = mapped_column(String(100), nullable=False)
    diversity_pass: Mapped[int | None] = mapped_column(Integer)

    run: Mapped[RankingRun] = relationship(back_populates="records")
    contributions: Mapped[list[RankingParameterContribution]] = relationship(
        back_populates="article_ranking",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class RankingParameterContribution(Base):
    __tablename__ = "ranking_parameter_contributions"
    __table_args__ = (
        UniqueConstraint(
            "article_ranking_id",
            "parameter_id",
            name="uq_ranking_parameter_contributions_article_parameter",
        ),
        CheckConstraint(
            "length(parameter_snapshot_hash) = 64",
            name="ck_ranking_parameter_contributions_snapshot_hash",
        ),
        CheckConstraint(
            "length(btrim(parameter_name)) > 0",
            name="ck_ranking_parameter_contributions_parameter_name",
        ),
        CheckConstraint(
            "weight >= -1.00 AND weight <= 1.00",
            name="ck_ranking_parameter_contributions_weight",
        ),
        CheckConstraint(
            "relevance >= -1.0000 AND relevance <= 1.0000",
            name="ck_ranking_parameter_contributions_relevance",
        ),
        CheckConstraint(
            "contribution >= -1.00000000 AND contribution <= 1.00000000",
            name="ck_ranking_parameter_contributions_contribution",
        ),
        CheckConstraint(
            "explanation_ordinal IS NULL OR explanation_ordinal > 0",
            name="ck_ranking_parameter_contributions_explanation_ordinal",
        ),
        Index(
            "ix_ranking_parameter_contributions_explanation",
            "article_ranking_id",
            "explanation_ordinal",
            unique=True,
            postgresql_where=sql_text("explanation_ordinal IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    article_ranking_id: Mapped[UUID] = mapped_column(
        ForeignKey("article_ranking_records.id", ondelete="CASCADE"), nullable=False
    )
    parameter_id: Mapped[UUID] = mapped_column(
        ForeignKey("preference_parameters.id", ondelete="RESTRICT"), nullable=False
    )
    parameter_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    parameter_name: Mapped[str] = mapped_column(String(160), nullable=False)
    parameter_origin: Mapped[PreferenceOrigin] = mapped_column(
        _enum(PreferenceOrigin, "preference_origin"), nullable=False
    )
    effective_authority: Mapped[PreferenceOrigin] = mapped_column(
        _enum(PreferenceOrigin, "preference_origin"), nullable=False
    )
    weight: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False)
    relevance: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    contribution: Mapped[Decimal] = mapped_column(Numeric(10, 8), nullable=False)
    explanation_ordinal: Mapped[int | None] = mapped_column(Integer)

    article_ranking: Mapped[ArticleRankingRecord] = relationship(
        back_populates="contributions"
    )


class RankingAudit(Base):
    __tablename__ = "ranking_audit"
    __table_args__ = (
        CheckConstraint(
            "profile_revision >= 0", name="ck_ranking_audit_profile_revision"
        ),
        CheckConstraint("length(input_hash) = 64", name="ck_ranking_audit_input_hash"),
        CheckConstraint(
            "length(factor_hash) = 64", name="ck_ranking_audit_factor_hash"
        ),
        CheckConstraint(
            "length(contribution_hash) = 64",
            name="ck_ranking_audit_contribution_hash",
        ),
        CheckConstraint("length(score_hash) = 64", name="ck_ranking_audit_score_hash"),
        CheckConstraint(
            "length(selection_hash) = 64",
            name="ck_ranking_audit_selection_hash",
        ),
        CheckConstraint(
            "final_score >= 0 AND final_score <= 1",
            name="ck_ranking_audit_final_score",
        ),
        CheckConstraint(
            "final_position IS NULL OR final_position > 0",
            name="ck_ranking_audit_final_position",
        ),
        Index("ix_ranking_audit_user_ranked", "user_id", "ranked_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    ranking_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("ranking_runs.id", ondelete="RESTRICT"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("preference_profiles.user_id", ondelete="RESTRICT"), nullable=False
    )
    article_id: Mapped[UUID] = mapped_column(
        ForeignKey("normalized_articles.id", ondelete="RESTRICT"), nullable=False
    )
    profile_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    configuration_version: Mapped[str] = mapped_column(
        ForeignKey("ranking_configuration_snapshots.version", ondelete="RESTRICT"),
        nullable=False,
    )
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    factor_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    contribution_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    score_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    selection_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    final_score: Mapped[Decimal] = mapped_column(Numeric(10, 8), nullable=False)
    final_position: Mapped[int | None] = mapped_column(Integer)
    ranked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
