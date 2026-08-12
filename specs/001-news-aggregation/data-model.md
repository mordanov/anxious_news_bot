# Data Model: News Aggregation and Article Analysis

## NewsSource

Configurable origin processed by the aggregator.

| Field | Type | Rules |
|---|---|---|
| id | UUID | Primary key, stable |
| name | text | Required, non-blank |
| source_type | enum | Initially `rss` or `atom` |
| endpoint_url | text | Required HTTP(S), encrypted configuration if sensitive |
| region | text | Required; initially World, Russia, or Spain |
| country_code | text | Optional ISO country code |
| language_code | text | Required normalized language tag |
| enabled | boolean | Defaults true |
| quality_score | decimal | Optional, range 0.00–1.00 |
| polling_interval_seconds | integer | Positive configured value |
| etag | text | Optional conditional-fetch value |
| last_modified | text | Optional conditional-fetch value |
| created_at / updated_at | timestamp | UTC |

**Constraints**: Endpoint and source identity are unique according to configuration.
Credentials are referenced from protected configuration, never stored in logs.

## CollectionCycle

One attempted orchestration of all enabled sources.

| Field | Type | Rules |
|---|---|---|
| id | UUID | Primary key |
| status | enum | `running`, `completed`, `completed_with_errors`, `failed` |
| started_at / completed_at | timestamp | UTC; completion follows start |
| new_article_count | integer | Non-negative |
| source_success_count / source_failure_count | integer | Non-negative |
| configuration_version | text | Required audit value |

**Transitions**: `running` → `completed`, `completed_with_errors`, or `failed`.
An advisory lock permits only one active cycle for the same configured scope.

## SourceRun

Source-specific result inside a cycle and the source failure-isolation boundary.

| Field | Type | Rules |
|---|---|---|
| id | UUID | Primary key |
| cycle_id | UUID | Required reference to CollectionCycle |
| source_id | UUID | Required reference to NewsSource |
| status | enum | `pending`, `fetching`, `processing`, `succeeded`, `not_modified`, `failed` |
| fetched_count / accepted_count / rejected_count | integer | Non-negative |
| started_at / completed_at | timestamp | UTC |
| error_code | text | Optional sanitized classification |
| error_context | JSON | Optional bounded, sanitized diagnostics |

**Constraints**: One SourceRun per cycle/source pair.

## SourceArticleRecord

Immutable-enough provenance for one record observed from one source.

| Field | Type | Rules |
|---|---|---|
| id | UUID | Primary key |
| source_run_id | UUID | Required reference to SourceRun |
| source_id | UUID | Required reference to NewsSource |
| external_id | text | Optional source-provided identity |
| original_url | text | Required |
| raw_payload | JSON | Optional bounded source data for diagnostics |
| payload_hash | text | Required deterministic hash |
| observed_at | timestamp | UTC |
| status | enum | `accepted`, `rejected`, `duplicate` |
| rejection_code | text | Required only when rejected |
| article_id | UUID | Optional reference to accepted NormalizedArticle |

**Constraints**: Repeated source identity or payload hash is idempotent for a source.

## NormalizedArticle

Canonical general-news representation consumed by later modules.

| Field | Type | Rules |
|---|---|---|
| id | UUID | Primary key |
| title | text | Required, normalized, non-blank |
| summary | text | Optional |
| canonical_url | text | Required and unique |
| canonicalization_version | text | Required |
| primary_source_id | UUID | Required reference to NewsSource |
| published_at | timestamp | Optional UTC |
| ingested_at | timestamp | Required UTC |
| language_code | text | Required |
| normalized_text | text | Required, non-blank |
| geographic_relevance | JSON | Validated countries/regions/locations |
| topic_metadata | JSON | Validated general topics |
| event_group_id | UUID | Optional reference to EventGroup |
| created_in_cycle_id | UUID | Required reference to CollectionCycle |

**Constraints**: Canonical URL uniqueness is database-enforced. No user identifier,
preference, interest score, or personalized rank is permitted.

## DeduplicationDecision

Auditable comparison between two candidate articles.

| Field | Type | Rules |
|---|---|---|
| id | UUID | Primary key |
| left_article_id / right_article_id | UUID | Required distinct article references |
| decision_type | enum | `exact_url`, `near_duplicate`, `event_related` |
| outcome | enum | `duplicate`, `review`, `distinct`, `same_event` |
| title_similarity / content_similarity | decimal | Optional, range 0.00–1.00 |
| threshold_configuration | JSON | Required values used for the decision |
| normalization_version | text | Required |
| evidence | JSON | Bounded, reviewable evidence |
| decided_at | timestamp | UTC |

**Constraints**: Article pair is stored in deterministic identifier order and is
unique per decision type and algorithm/configuration version.

## EventGroup

General-news event that may have coverage from multiple sources.

| Field | Type | Rules |
|---|---|---|
| id | UUID | Primary key |
| label | text | Optional validated description |
| event_type | text | Optional validated value |
| status | enum | `proposed`, `confirmed`, `superseded` |
| representative_article_id | UUID | Optional; digest selection may override later |
| created_at / updated_at | timestamp | UTC |

Membership is represented by each article's optional `event_group_id`. Reassignment
must retain a DeduplicationDecision or audit event explaining the change.

## ArticleAnalysis

Versioned structured enrichment for one article.

| Field | Type | Rules |
|---|---|---|
| id | UUID | Primary key |
| article_id | UUID | Required reference to NormalizedArticle |
| status | enum | `not_attempted`, `complete`, `partial`, `invalid`, `failed` |
| schema_version | text | Required |
| analyzer_name / analyzer_version | text | Required |
| topics | JSON | Validated bounded list |
| countries / cities / locations | JSON | Validated bounded lists |
| people / organizations | JSON | Validated bounded lists |
| event_type | text | Optional validated enum/value |
| importance_score | decimal | Optional, range 0.00–1.00 |
| novelty_score | decimal | Optional, range 0.00–1.00 |
| source_quality_score | decimal | Optional, range 0.00–1.00 |
| semantic_metadata | JSON | Optional validated representation metadata |
| error_code | text | Optional sanitized classification |
| created_at | timestamp | UTC |

**Constraints**: Unique by article, analyzer, analyzer version, and schema version.
Only independently validated sections are stored. Importance is never interpreted
as personal interest.

## Relationships

```text
CollectionCycle 1 ── * SourceRun * ── 1 NewsSource
SourceRun       1 ── * SourceArticleRecord * ── 0..1 NormalizedArticle
CollectionCycle 1 ── * NormalizedArticle
NormalizedArticle 1 ── * ArticleAnalysis
NormalizedArticle * ── 0..1 EventGroup
NormalizedArticle * ── * DeduplicationDecision (paired comparison)
```

## Retention and deletion

- Normalized articles and accepted provenance remain durable for downstream use.
- Raw payload retention is configurable and may expire earlier than normalized
  content; payload hashes and processing outcomes remain for audit.
- Source and cycle diagnostics are bounded and sanitized.
- Disabling a source does not delete its historical articles or provenance.

