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
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from anxious_news_bot.news.domain import (
    AnalysisStatus,
    CycleStatus,
    DecisionOutcome,
    DecisionType,
    EventGroupStatus,
    ProvenanceStatus,
    SourceRunStatus,
    SourceType,
)


def _enum(enum_class: type, name: str) -> Enum:
    return Enum(
        enum_class,
        name=name,
        values_callable=lambda members: [member.value for member in members],
        validate_strings=True,
    )


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=lambda: datetime.now().astimezone(),
    )


class NewsSource(TimestampMixin, Base):
    __tablename__ = "news_sources"
    __table_args__ = (
        CheckConstraint("length(btrim(name)) > 0", name="ck_news_sources_name"),
        CheckConstraint("endpoint_url ~ '^https?://'", name="ck_news_sources_endpoint"),
        CheckConstraint(
            "quality_score IS NULL OR (quality_score >= 0 AND quality_score <= 1)",
            name="ck_news_sources_quality",
        ),
        CheckConstraint(
            "polling_interval_seconds > 0", name="ck_news_sources_polling_interval"
        ),
        CheckConstraint(
            "country_code IS NULL OR country_code ~ '^[A-Z]{2}$'",
            name="ck_news_sources_country_code",
        ),
        Index("ix_news_sources_enabled_next_poll", "enabled", "next_poll_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_type: Mapped[SourceType] = mapped_column(
        _enum(SourceType, "news_source_type"), nullable=False
    )
    endpoint_url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    region: Mapped[str] = mapped_column(String(100), nullable=False)
    country_code: Mapped[str | None] = mapped_column(String(2))
    language_code: Mapped[str] = mapped_column(String(35), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    quality_score: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    polling_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    etag: Mapped[str | None] = mapped_column(Text)
    last_modified: Mapped[str | None] = mapped_column(Text)
    credential_ref: Mapped[str | None] = mapped_column(String(200))

    source_runs: Mapped[list[SourceRun]] = relationship(back_populates="source")
    articles: Mapped[list[NormalizedArticle]] = relationship(
        back_populates="primary_source"
    )
    records: Mapped[list[SourceArticleRecord]] = relationship(back_populates="source")


class CollectionCycle(Base):
    __tablename__ = "collection_cycles"
    __table_args__ = (
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name="ck_collection_cycles_completion",
        ),
        CheckConstraint(
            "new_article_count >= 0 AND source_success_count >= 0 "
            "AND source_failure_count >= 0",
            name="ck_collection_cycles_counts",
        ),
        Index("ix_collection_cycles_started_at", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    status: Mapped[CycleStatus] = mapped_column(
        _enum(CycleStatus, "collection_cycle_status"),
        nullable=False,
        default=CycleStatus.RUNNING,
        server_default=text("'running'"),
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    new_article_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    source_success_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    source_failure_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    configuration_version: Mapped[str] = mapped_column(String(100), nullable=False)

    source_runs: Mapped[list[SourceRun]] = relationship(back_populates="cycle")
    articles: Mapped[list[NormalizedArticle]] = relationship(
        back_populates="created_in_cycle"
    )


class SourceRun(Base):
    __tablename__ = "source_runs"
    __table_args__ = (
        UniqueConstraint("cycle_id", "source_id", name="uq_source_runs_cycle_source"),
        CheckConstraint(
            "fetched_count >= 0 AND accepted_count >= 0 AND rejected_count >= 0",
            name="ck_source_runs_counts",
        ),
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name="ck_source_runs_completion",
        ),
        Index("ix_source_runs_cycle_status", "cycle_id", "status"),
        Index("ix_source_runs_source_started", "source_id", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    cycle_id: Mapped[UUID] = mapped_column(
        ForeignKey("collection_cycles.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("news_sources.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[SourceRunStatus] = mapped_column(
        _enum(SourceRunStatus, "source_run_status"),
        nullable=False,
        default=SourceRunStatus.PENDING,
        server_default=text("'pending'"),
    )
    fetched_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    accepted_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    rejected_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_context: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    cycle: Mapped[CollectionCycle] = relationship(back_populates="source_runs")
    source: Mapped[NewsSource] = relationship(back_populates="source_runs")
    records: Mapped[list[SourceArticleRecord]] = relationship(
        back_populates="source_run"
    )


class EventGroup(TimestampMixin, Base):
    __tablename__ = "event_groups"
    __table_args__ = (
        CheckConstraint(
            "label IS NULL OR length(btrim(label)) > 0",
            name="ck_event_groups_label",
        ),
        Index("ix_event_groups_status_updated", "status", "updated_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    label: Mapped[str | None] = mapped_column(String(300))
    event_type: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[EventGroupStatus] = mapped_column(
        _enum(EventGroupStatus, "event_group_status"),
        nullable=False,
        default=EventGroupStatus.PROPOSED,
        server_default=text("'proposed'"),
    )
    representative_article_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "normalized_articles.id",
            name="fk_event_groups_representative_article",
            ondelete="SET NULL",
            use_alter=True,
        )
    )

    articles: Mapped[list[NormalizedArticle]] = relationship(
        back_populates="event_group",
        foreign_keys="NormalizedArticle.event_group_id",
    )


class NormalizedArticle(Base):
    __tablename__ = "normalized_articles"
    __table_args__ = (
        CheckConstraint("length(btrim(title)) > 0", name="ck_articles_title"),
        CheckConstraint(
            "length(btrim(normalized_text)) > 0", name="ck_articles_normalized_text"
        ),
        CheckConstraint(
            "canonical_url ~ '^https?://'", name="ck_articles_canonical_url"
        ),
        Index("ix_articles_published_at", "published_at"),
        Index("ix_articles_language_published", "language_code", "published_at"),
        Index("ix_articles_event_group", "event_group_id"),
        Index(
            "ix_articles_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
        Index(
            "ix_articles_normalized_text_trgm",
            "normalized_text",
            postgresql_using="gin",
            postgresql_ops={"normalized_text": "gin_trgm_ops"},
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    canonicalization_version: Mapped[str] = mapped_column(String(50), nullable=False)
    primary_source_id: Mapped[UUID] = mapped_column(
        ForeignKey("news_sources.id", ondelete="RESTRICT"), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    language_code: Mapped[str] = mapped_column(String(35), nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    geographic_relevance: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    topic_metadata: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    event_group_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("event_groups.id", ondelete="SET NULL")
    )
    created_in_cycle_id: Mapped[UUID] = mapped_column(
        ForeignKey("collection_cycles.id", ondelete="RESTRICT"), nullable=False
    )
    post_processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    primary_source: Mapped[NewsSource] = relationship(back_populates="articles")
    created_in_cycle: Mapped[CollectionCycle] = relationship(back_populates="articles")
    event_group: Mapped[EventGroup | None] = relationship(
        back_populates="articles", foreign_keys=[event_group_id]
    )
    source_records: Mapped[list[SourceArticleRecord]] = relationship(
        back_populates="article"
    )
    analyses: Mapped[list[ArticleAnalysis]] = relationship(back_populates="article")


class SourceArticleRecord(Base):
    __tablename__ = "source_article_records"
    __table_args__ = (
        UniqueConstraint(
            "source_run_id",
            "source_id",
            "payload_hash",
            name="uq_source_records_run_source_payload",
        ),
        CheckConstraint(
            "(status <> 'rejected') OR rejection_code IS NOT NULL",
            name="ck_source_records_rejection_code",
        ),
        Index(
            "uq_source_records_source_external",
            "source_run_id",
            "source_id",
            "external_id",
            unique=True,
            postgresql_where=text("external_id IS NOT NULL"),
        ),
        Index("ix_source_records_article", "article_id"),
        Index("ix_source_records_observed_at", "observed_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    source_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_runs.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("news_sources.id", ondelete="RESTRICT"), nullable=False
    )
    external_id: Mapped[str | None] = mapped_column(Text)
    original_url: Mapped[str] = mapped_column(Text, nullable=False)
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    status: Mapped[ProvenanceStatus] = mapped_column(
        _enum(ProvenanceStatus, "provenance_status"), nullable=False
    )
    rejection_code: Mapped[str | None] = mapped_column(String(100))
    article_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("normalized_articles.id", ondelete="SET NULL")
    )

    source_run: Mapped[SourceRun] = relationship(back_populates="records")
    source: Mapped[NewsSource] = relationship(back_populates="records")
    article: Mapped[NormalizedArticle | None] = relationship(
        back_populates="source_records"
    )


class DeduplicationDecision(Base):
    __tablename__ = "deduplication_decisions"
    __table_args__ = (
        UniqueConstraint(
            "left_article_id",
            "right_article_id",
            "decision_type",
            "normalization_version",
            name="uq_decisions_pair_type_version",
        ),
        CheckConstraint(
            "left_article_id < right_article_id", name="ck_decisions_pair_order"
        ),
        CheckConstraint(
            "title_similarity IS NULL OR "
            "(title_similarity >= 0 AND title_similarity <= 1)",
            name="ck_decisions_title_similarity",
        ),
        CheckConstraint(
            "content_similarity IS NULL OR "
            "(content_similarity >= 0 AND content_similarity <= 1)",
            name="ck_decisions_content_similarity",
        ),
        Index("ix_decisions_left_type", "left_article_id", "decision_type"),
        Index("ix_decisions_right_type", "right_article_id", "decision_type"),
        Index("ix_decisions_decided_at", "decided_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    left_article_id: Mapped[UUID] = mapped_column(
        ForeignKey("normalized_articles.id", ondelete="CASCADE"), nullable=False
    )
    right_article_id: Mapped[UUID] = mapped_column(
        ForeignKey("normalized_articles.id", ondelete="CASCADE"), nullable=False
    )
    decision_type: Mapped[DecisionType] = mapped_column(
        _enum(DecisionType, "deduplication_decision_type"), nullable=False
    )
    outcome: Mapped[DecisionOutcome] = mapped_column(
        _enum(DecisionOutcome, "deduplication_outcome"), nullable=False
    )
    title_similarity: Mapped[Decimal | None] = mapped_column(Numeric(6, 5))
    content_similarity: Mapped[Decimal | None] = mapped_column(Numeric(6, 5))
    threshold_configuration: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False
    )
    normalization_version: Mapped[str] = mapped_column(String(100), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class ArticleAnalysis(Base):
    __tablename__ = "article_analyses"
    __table_args__ = (
        UniqueConstraint(
            "article_id",
            "analyzer_name",
            "analyzer_version",
            "schema_version",
            name="uq_article_analyses_version",
        ),
        CheckConstraint(
            "importance_score IS NULL OR "
            "(importance_score >= 0 AND importance_score <= 1)",
            name="ck_article_analyses_importance",
        ),
        CheckConstraint(
            "novelty_score IS NULL OR (novelty_score >= 0 AND novelty_score <= 1)",
            name="ck_article_analyses_novelty",
        ),
        CheckConstraint(
            "source_quality_score IS NULL OR "
            "(source_quality_score >= 0 AND source_quality_score <= 1)",
            name="ck_article_analyses_source_quality",
        ),
        Index("ix_article_analyses_status_created", "status", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    article_id: Mapped[UUID] = mapped_column(
        ForeignKey("normalized_articles.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[AnalysisStatus] = mapped_column(
        _enum(AnalysisStatus, "article_analysis_status"), nullable=False
    )
    schema_version: Mapped[str] = mapped_column(String(50), nullable=False)
    analyzer_name: Mapped[str] = mapped_column(String(100), nullable=False)
    analyzer_version: Mapped[str] = mapped_column(String(100), nullable=False)
    topics: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    countries: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    cities: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    locations: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    people: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    organizations: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    event_type: Mapped[str | None] = mapped_column(String(100))
    importance_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    novelty_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    source_quality_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    semantic_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    article: Mapped[NormalizedArticle] = relationship(back_populates="analyses")
