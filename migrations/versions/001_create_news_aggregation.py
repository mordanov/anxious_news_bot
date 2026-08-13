"""Create news aggregation schema.

Revision ID: 001_create_news_aggregation
Revises:
Create Date: 2026-08-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001_create_news_aggregation"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

source_type = postgresql.ENUM("rss", "atom", name="news_source_type", create_type=False)
cycle_status = postgresql.ENUM(
    "running",
    "completed",
    "completed_with_errors",
    "failed",
    name="collection_cycle_status",
    create_type=False,
)
source_run_status = postgresql.ENUM(
    "pending",
    "fetching",
    "processing",
    "succeeded",
    "not_modified",
    "failed",
    name="source_run_status",
    create_type=False,
)
event_group_status = postgresql.ENUM(
    "proposed",
    "confirmed",
    "superseded",
    name="event_group_status",
    create_type=False,
)
provenance_status = postgresql.ENUM(
    "accepted",
    "rejected",
    "duplicate",
    name="provenance_status",
    create_type=False,
)
decision_type = postgresql.ENUM(
    "exact_url",
    "near_duplicate",
    "event_related",
    name="deduplication_decision_type",
    create_type=False,
)
decision_outcome = postgresql.ENUM(
    "duplicate",
    "review",
    "distinct",
    "same_event",
    name="deduplication_outcome",
    create_type=False,
)
analysis_status = postgresql.ENUM(
    "not_attempted",
    "complete",
    "partial",
    "invalid",
    "failed",
    name="article_analysis_status",
    create_type=False,
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    bind = op.get_bind()
    for enum_type in (
        source_type,
        cycle_status,
        source_run_status,
        event_group_status,
        provenance_status,
        decision_type,
        decision_outcome,
        analysis_status,
    ):
        enum_type.create(bind, checkfirst=True)

    op.create_table(
        "news_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("source_type", source_type, nullable=False),
        sa.Column("endpoint_url", sa.Text(), nullable=False),
        sa.Column("region", sa.String(length=100), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=True),
        sa.Column("language_code", sa.String(length=35), nullable=False),
        sa.Column(
            "enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("quality_score", sa.Numeric(precision=3, scale=2), nullable=True),
        sa.Column("polling_interval_seconds", sa.Integer(), nullable=False),
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_poll_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("etag", sa.Text(), nullable=True),
        sa.Column("last_modified", sa.Text(), nullable=True),
        sa.Column("credential_ref", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "country_code IS NULL OR country_code ~ '^[A-Z]{2}$'",
            name="ck_news_sources_country_code",
        ),
        sa.CheckConstraint(
            "endpoint_url ~ '^https?://'", name="ck_news_sources_endpoint"
        ),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_news_sources_name"),
        sa.CheckConstraint(
            "polling_interval_seconds > 0",
            name="ck_news_sources_polling_interval",
        ),
        sa.CheckConstraint(
            "quality_score IS NULL OR (quality_score >= 0 AND quality_score <= 1)",
            name="ck_news_sources_quality",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("endpoint_url"),
    )
    op.create_index(
        "ix_news_sources_enabled_next_poll",
        "news_sources",
        ["enabled", "next_poll_at"],
    )

    op.create_table(
        "collection_cycles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            cycle_status,
            server_default=sa.text("'running'"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "new_article_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "source_success_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "source_failure_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("configuration_version", sa.String(length=100), nullable=False),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name="ck_collection_cycles_completion",
        ),
        sa.CheckConstraint(
            "new_article_count >= 0 AND source_success_count >= 0 "
            "AND source_failure_count >= 0",
            name="ck_collection_cycles_counts",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_collection_cycles_started_at", "collection_cycles", ["started_at"]
    )

    op.create_table(
        "source_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cycle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            source_run_status,
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "fetched_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "accepted_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "rejected_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column(
            "error_context", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name="ck_source_runs_completion",
        ),
        sa.CheckConstraint(
            "fetched_count >= 0 AND accepted_count >= 0 AND rejected_count >= 0",
            name="ck_source_runs_counts",
        ),
        sa.ForeignKeyConstraint(
            ["cycle_id"], ["collection_cycles.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["news_sources.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "cycle_id", "source_id", name="uq_source_runs_cycle_source"
        ),
    )
    op.create_index(
        "ix_source_runs_cycle_status", "source_runs", ["cycle_id", "status"]
    )
    op.create_index(
        "ix_source_runs_source_started", "source_runs", ["source_id", "started_at"]
    )

    op.create_table(
        "event_groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("label", sa.String(length=300), nullable=True),
        sa.Column("event_type", sa.String(length=100), nullable=True),
        sa.Column(
            "status",
            event_group_status,
            server_default=sa.text("'proposed'"),
            nullable=False,
        ),
        sa.Column(
            "representative_article_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "label IS NULL OR length(btrim(label)) > 0",
            name="ck_event_groups_label",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_event_groups_status_updated", "event_groups", ["status", "updated_at"]
    )

    op.create_table(
        "normalized_articles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("canonicalization_version", sa.String(length=50), nullable=False),
        sa.Column("primary_source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("language_code", sa.String(length=35), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column(
            "geographic_relevance",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "topic_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("event_group_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_in_cycle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("post_processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "canonical_url ~ '^https?://'", name="ck_articles_canonical_url"
        ),
        sa.CheckConstraint(
            "length(btrim(normalized_text)) > 0",
            name="ck_articles_normalized_text",
        ),
        sa.CheckConstraint("length(btrim(title)) > 0", name="ck_articles_title"),
        sa.ForeignKeyConstraint(
            ["created_in_cycle_id"], ["collection_cycles.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["event_group_id"], ["event_groups.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["primary_source_id"], ["news_sources.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("canonical_url"),
    )
    op.create_index(
        "ix_articles_event_group", "normalized_articles", ["event_group_id"]
    )
    op.create_index(
        "ix_articles_language_published",
        "normalized_articles",
        ["language_code", "published_at"],
    )
    op.create_index("ix_articles_published_at", "normalized_articles", ["published_at"])
    op.create_index(
        "ix_articles_title_trgm",
        "normalized_articles",
        ["title"],
        postgresql_using="gin",
        postgresql_ops={"title": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_articles_normalized_text_trgm",
        "normalized_articles",
        ["normalized_text"],
        postgresql_using="gin",
        postgresql_ops={"normalized_text": "gin_trgm_ops"},
    )
    op.create_foreign_key(
        "fk_event_groups_representative_article",
        "event_groups",
        "normalized_articles",
        ["representative_article_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "source_article_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=True),
        sa.Column("original_url", sa.Text(), nullable=False),
        sa.Column(
            "raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", provenance_status, nullable=False),
        sa.Column("rejection_code", sa.String(length=100), nullable=True),
        sa.Column("article_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint(
            "(status <> 'rejected') OR rejection_code IS NOT NULL",
            name="ck_source_records_rejection_code",
        ),
        sa.ForeignKeyConstraint(
            ["article_id"], ["normalized_articles.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["news_sources.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_run_id"], ["source_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_run_id",
            "source_id",
            "payload_hash",
            name="uq_source_records_run_source_payload",
        ),
    )
    op.create_index(
        "ix_source_records_article", "source_article_records", ["article_id"]
    )
    op.create_index(
        "ix_source_records_observed_at", "source_article_records", ["observed_at"]
    )
    op.create_index(
        "uq_source_records_source_external",
        "source_article_records",
        ["source_run_id", "source_id", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )

    op.create_table(
        "deduplication_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("left_article_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("right_article_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decision_type", decision_type, nullable=False),
        sa.Column("outcome", decision_outcome, nullable=False),
        sa.Column("title_similarity", sa.Numeric(precision=6, scale=5), nullable=True),
        sa.Column(
            "content_similarity", sa.Numeric(precision=6, scale=5), nullable=True
        ),
        sa.Column(
            "threshold_configuration",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("normalization_version", sa.String(length=100), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "content_similarity IS NULL OR "
            "(content_similarity >= 0 AND content_similarity <= 1)",
            name="ck_decisions_content_similarity",
        ),
        sa.CheckConstraint(
            "left_article_id < right_article_id", name="ck_decisions_pair_order"
        ),
        sa.CheckConstraint(
            "title_similarity IS NULL OR "
            "(title_similarity >= 0 AND title_similarity <= 1)",
            name="ck_decisions_title_similarity",
        ),
        sa.ForeignKeyConstraint(
            ["left_article_id"], ["normalized_articles.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["right_article_id"], ["normalized_articles.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "left_article_id",
            "right_article_id",
            "decision_type",
            "normalization_version",
            name="uq_decisions_pair_type_version",
        ),
    )
    op.create_index(
        "ix_decisions_decided_at", "deduplication_decisions", ["decided_at"]
    )
    op.create_index(
        "ix_decisions_left_type",
        "deduplication_decisions",
        ["left_article_id", "decision_type"],
    )
    op.create_index(
        "ix_decisions_right_type",
        "deduplication_decisions",
        ["right_article_id", "decision_type"],
    )

    op.create_table(
        "article_analyses",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("article_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", analysis_status, nullable=False),
        sa.Column("schema_version", sa.String(length=50), nullable=False),
        sa.Column("analyzer_name", sa.String(length=100), nullable=False),
        sa.Column("analyzer_version", sa.String(length=100), nullable=False),
        sa.Column(
            "topics",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "countries",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "cities",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "locations",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "people",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "organizations",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(length=100), nullable=True),
        sa.Column("importance_score", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("novelty_score", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column(
            "source_quality_score", sa.Numeric(precision=5, scale=4), nullable=True
        ),
        sa.Column(
            "semantic_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "importance_score IS NULL OR "
            "(importance_score >= 0 AND importance_score <= 1)",
            name="ck_article_analyses_importance",
        ),
        sa.CheckConstraint(
            "novelty_score IS NULL OR (novelty_score >= 0 AND novelty_score <= 1)",
            name="ck_article_analyses_novelty",
        ),
        sa.CheckConstraint(
            "source_quality_score IS NULL OR "
            "(source_quality_score >= 0 AND source_quality_score <= 1)",
            name="ck_article_analyses_source_quality",
        ),
        sa.ForeignKeyConstraint(
            ["article_id"], ["normalized_articles.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "article_id",
            "analyzer_name",
            "analyzer_version",
            "schema_version",
            name="uq_article_analyses_version",
        ),
    )
    op.create_index(
        "ix_article_analyses_status_created",
        "article_analyses",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_article_analyses_status_created", table_name="article_analyses")
    op.drop_table("article_analyses")
    op.drop_index("ix_decisions_right_type", table_name="deduplication_decisions")
    op.drop_index("ix_decisions_left_type", table_name="deduplication_decisions")
    op.drop_index("ix_decisions_decided_at", table_name="deduplication_decisions")
    op.drop_table("deduplication_decisions")
    op.drop_index(
        "uq_source_records_source_external", table_name="source_article_records"
    )
    op.drop_index("ix_source_records_observed_at", table_name="source_article_records")
    op.drop_index("ix_source_records_article", table_name="source_article_records")
    op.drop_table("source_article_records")
    op.drop_constraint(
        "fk_event_groups_representative_article",
        "event_groups",
        type_="foreignkey",
    )
    op.drop_index("ix_articles_normalized_text_trgm", table_name="normalized_articles")
    op.drop_index("ix_articles_title_trgm", table_name="normalized_articles")
    op.drop_index("ix_articles_published_at", table_name="normalized_articles")
    op.drop_index("ix_articles_language_published", table_name="normalized_articles")
    op.drop_index("ix_articles_event_group", table_name="normalized_articles")
    op.drop_table("normalized_articles")
    op.drop_index("ix_event_groups_status_updated", table_name="event_groups")
    op.drop_table("event_groups")
    op.drop_index("ix_source_runs_source_started", table_name="source_runs")
    op.drop_index("ix_source_runs_cycle_status", table_name="source_runs")
    op.drop_table("source_runs")
    op.drop_index("ix_collection_cycles_started_at", table_name="collection_cycles")
    op.drop_table("collection_cycles")
    op.drop_index("ix_news_sources_enabled_next_poll", table_name="news_sources")
    op.drop_table("news_sources")

    bind = op.get_bind()
    for enum_type in (
        analysis_status,
        decision_outcome,
        decision_type,
        provenance_status,
        event_group_status,
        source_run_status,
        cycle_status,
        source_type,
    ):
        enum_type.drop(bind, checkfirst=True)
