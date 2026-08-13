# Data Model: Scheduled News Digests

## Design Rules

- All identifiers are UUIDs unless noted otherwise.
- All persisted instants are timezone-aware UTC values.
- User schedules use a validated IANA timezone and a local `HH:MM` wall-clock
  value; UTC offsets are never stored as the schedule source of truth.
- Digest count is always in `5..20`.
- One `(user_id, occurrence_key)` may create only one execution.
- External calls occur outside database transactions. State is claimed in a
  short transaction, work is performed, and the outcome is committed separately.
- Raw prompts, model credentials, unrestricted source text, and Telegram tokens
  are not stored in digest records or diagnostics.

## Entity: DigestConfiguration

One row per application user.

| Field | Type | Rules |
|-------|------|-------|
| user_id | UUID | Primary key; FK to `application_users`, cascade delete |
| enabled | boolean | Required; defaults false for existing and new users |
| digest_count | integer | Required; check `5 <= digest_count <= 20`; default 10 |
| schedule_local_time | time | Required minute precision; default `09:00` |
| timezone_name | string(64) | Required validated IANA identifier; default `UTC` |
| next_due_at | datetime nullable | UTC instant for next occurrence; null while disabled |
| schedule_revision | integer | Required, non-negative; increment on schedule/timezone/enable changes |
| last_success_execution_id | UUID nullable | Most recent successful execution reference |
| last_success_at | datetime nullable | Completion time of most recent success |
| last_failure_execution_id | UUID nullable | Most recent failed execution reference |
| last_failure_at | datetime nullable | Completion time of most recent failure |
| last_failure_code | string(100) nullable | Safe canonical reason code |
| created_at | datetime | Required |
| updated_at | datetime | Required |

**Indexes and constraints**:

- Partial due-scan index on `(next_due_at, user_id)` where `enabled = true`.
- `next_due_at` must be non-null when enabled after configuration activation.
- Last success and failure fields update only when the candidate timestamp is
  newer than the currently stored timestamp.
- Execution references use deferred or post-create foreign keys to avoid table
  creation cycles.

## Entity: DigestExecution

One durable lifecycle per user and intended local occurrence.

| Field | Type | Rules |
|-------|------|-------|
| id | UUID | Primary key |
| user_id | UUID | FK to digest configuration/application user |
| occurrence_key | string(160) | Canonical `local-date/local-time/timezone` identity |
| scheduled_for | datetime | Resolved UTC instant for the occurrence |
| local_date | date | Captured intended local calendar date |
| local_time | time | Captured intended local time |
| timezone_name | string(64) | Captured IANA timezone |
| schedule_revision | integer | Captured configuration revision |
| digest_count | integer | Captured count, check `5..20` |
| language_code | string(35) | Captured supported user language |
| profile_revision | integer nullable | Captured by selection once profile loads |
| ranking_request_id | string(200) | Stable value derived from execution ID |
| ranking_run_id | UUID nullable | Accepted deterministic ranking run |
| status | enum | See lifecycle below |
| attempt_count | integer | Non-negative; incremented when an attempt is claimed |
| selected_count | integer nullable | `0..digest_count` after selection |
| next_retry_at | datetime nullable | Present only while waiting for retry |
| failure_code | string(100) nullable | Safe canonical reason |
| failure_class | enum nullable | `transient`, `permanent`, or `ambiguous_delivery` |
| started_at | datetime nullable | First processing claim |
| content_ready_at | datetime nullable | Structured items persisted |
| delivery_started_at | datetime nullable | First part claimed |
| completed_at | datetime nullable | Terminal transition time |
| created_at | datetime | Required |
| updated_at | datetime | Required |

**Execution status values**:

- `scheduled`: occurrence claimed, no attempt currently running.
- `processing`: loading inputs, filtering, evaluating, or ranking.
- `composing`: validating localized title/summary output.
- `ready`: immutable items exist and delivery parts may be rendered/claimed.
- `delivering`: one or more delivery parts are in progress.
- `retrying`: transient failure recorded and `next_retry_at` set.
- `completed`: zero-item execution or all delivery parts acknowledged.
- `failed`: terminal permanent or retry-exhausted failure.
- `delivery_unknown`: a provider outcome is ambiguous; no automatic resend.

**Indexes and constraints**:

- Unique `(user_id, occurrence_key)`.
- Index `(status, next_retry_at)` for retry claims.
- Index `(user_id, scheduled_for desc)` for user status/history.
- `selected_count <= digest_count`.
- Terminal states require `completed_at`; `retrying` requires `next_retry_at` and
  transient failure class; `delivery_unknown` requires ambiguous failure class.

## Entity: DigestExecutionAttempt

One bounded processing attempt within an execution.

| Field | Type | Rules |
|-------|------|-------|
| id | UUID | Primary key |
| execution_id | UUID | FK to execution, cascade delete |
| ordinal | integer | Positive; unique within execution |
| phase | enum | `prepare`, `compose`, or `deliver` |
| status | enum | `running`, `completed`, `transient_failure`, `permanent_failure`, `ambiguous` |
| error_code | string(100) nullable | Safe canonical reason |
| started_at | datetime | Required |
| completed_at | datetime nullable | Required when no longer running |

No model payload, user text, or article text is retained here.

## Entity: DigestItem

Immutable ordered content accepted before delivery.

| Field | Type | Rules |
|-------|------|-------|
| id | UUID | Primary key |
| execution_id | UUID | FK to execution, cascade delete |
| position | integer | Positive; unique within execution |
| article_id | UUID | FK to normalized article, restrict delete |
| article_analysis_id | UUID | FK to accepted analysis, restrict delete |
| event_group_id | UUID nullable | Captured story/event identity |
| ranking_run_id | UUID | FK to ranking run, restrict delete |
| title | string(500) | Non-empty localized title |
| summary | string(1200) | Non-empty localized concise summary |
| source_name | string(200) | Non-empty deterministic source snapshot |
| published_at | datetime | Source publication instant |
| canonical_url | string(2048) | Valid normalized HTTP(S) URL snapshot |
| score | decimal | Exact ranking score snapshot |
| content_schema_version | string(20) | Structured composer schema version |
| content_hash | string(64) | Hash of canonical item snapshot |
| delivery_part_ordinal | integer nullable | Assigned during deterministic rendering |
| created_at | datetime | Required |

**Constraints**:

- Unique `(execution_id, position)` and `(execution_id, article_id)`.
- Item positions are contiguous from 1 through `selected_count`, checked by
  application validation before insertion.
- The number of inserted rows must exactly equal execution `selected_count`.

## Entity: DigestDeliveryPart

One Telegram-sized rendering part. The delivery adapter may produce multiple
parts for a digest, but each part has independent at-most-once state.

| Field | Type | Rules |
|-------|------|-------|
| id | UUID | Primary key |
| execution_id | UUID | FK to execution, cascade delete |
| ordinal | integer | Positive; unique within execution |
| content_hash | string(64) | Hash of exact rendered content |
| first_item_position | integer | First included item |
| last_item_position | integer | Last included item; not below first |
| status | enum | `pending`, `sending`, `sent`, `failed`, or `unknown` |
| provider_message_id | string(100) nullable | Stored only after acknowledgement |
| attempt_count | integer | Non-negative |
| claimed_at | datetime nullable | Latest send claim |
| sent_at | datetime nullable | Provider acknowledgement time |
| failure_code | string(100) nullable | Safe canonical reason |
| created_at | datetime | Required |
| updated_at | datetime | Required |

**Constraints**:

- Unique `(execution_id, ordinal)`.
- `sent` requires provider message ID and `sent_at`.
- `unknown` is terminal and cannot transition back to pending.
- Exact rendered message text is reconstructed from immutable items and renderer
  version; it need not be duplicated in this table.

## Entity: DigestDeliveryHistory

Per-user evidence used by later candidate filtering.

| Field | Type | Rules |
|-------|------|-------|
| id | UUID | Primary key |
| user_id | UUID | FK to application user, cascade delete |
| execution_id | UUID | FK to execution, cascade delete |
| digest_item_id | UUID | FK to item, cascade delete |
| article_id | UUID | FK to normalized article, restrict delete |
| article_analysis_id | UUID | FK to analysis, restrict delete |
| event_group_id | UUID nullable | Story identity at delivery |
| publication_time | datetime | Captured source publication time |
| outcome | enum | `confirmed` or `uncertain` |
| delivered_at | datetime | Acknowledged or ambiguity time |

**Indexes and constraints**:

- Unique `(execution_id, article_id)`.
- Index `(user_id, article_id, delivered_at desc)`.
- Index `(user_id, event_group_id, delivered_at desc)` where event group is not
  null.
- `uncertain` history is treated as delivered for repetition filtering.
- A later article in the same event group is eligible only when it was published
  after prior history and its accepted complete analysis meets the configured
  material-update novelty threshold.

## Existing Entity Extensions

### DeliveryArticle / RankedNews Selection

The existing delivery projection gains:

- a required grounded summary (normalized summary or bounded normalized-text
  excerpt);
- accepted `article_analysis_id`;
- nullable `event_group_id`;
- the ranking run ID and captured profile revision in the selection result.

The existing `/news` output remains backward compatible and may ignore these
additional fields.

### Application User Creation

Digest configuration creation reuses the existing preference repository's
atomic application-user/profile claim. It does not create a competing identity
upsert path.

## Relationships

```text
ApplicationUser 1 --- 1 DigestConfiguration
ApplicationUser 1 --- * DigestExecution
DigestExecution 1 --- * DigestExecutionAttempt
DigestExecution 1 --- * DigestItem
DigestExecution 1 --- * DigestDeliveryPart
DigestExecution 1 --- * DigestDeliveryHistory
DigestItem       1 --- 0..1 DigestDeliveryHistory
NormalizedArticle 1 --- * DigestItem / DigestDeliveryHistory
ArticleAnalysis   1 --- * DigestItem / DigestDeliveryHistory
RankingRun        1 --- * DigestItem
```

## Lifecycle Transitions

```text
scheduled -> processing
processing -> composing | retrying | completed(selected_count=0) | failed
composing -> ready | retrying | failed
ready -> delivering
delivering -> completed | retrying | failed | delivery_unknown
retrying -> processing | composing | ready | delivering | failed
```

- Accepted structured items are immutable. A retry after `ready` resumes delivery
  and never re-ranks or re-composes.
- A retry before items exist reuses `ranking_request_id`; the ranking module
  returns the already completed run for identical captured inputs.
- `completed`, `failed`, and `delivery_unknown` are terminal.
- A stale `sending` part cannot be blindly reclaimed. It transitions to `unknown`
  unless provider evidence proves it was not accepted.

## Transaction Boundaries

1. **Due claim**: lock due configurations with skip-locked semantics; derive
   occurrence; insert execution on conflict-do-nothing; advance `next_due_at`;
   commit.
2. **Attempt claim**: lock execution; reject terminal/concurrent work; increment
   attempt count; add running attempt; transition phase; commit.
3. **Selection completion**: validate ranking result and history decisions;
   persist ranking linkage and selected count; commit.
4. **Composition acceptance**: validate exact indexed output; atomically insert
   all immutable items and move to `ready`; commit.
5. **Part preparation**: deterministically render all parts; atomically insert
   hashes/ranges on first delivery; later attempts verify identical hashes.
6. **Part claim**: lock one pending/definitively failed part; set `sending`;
   commit before external send.
7. **Part acknowledgement**: set `sent`, store provider message ID, and insert
   confirmed history for included items atomically.
8. **Ambiguous outcome**: set `unknown`, insert uncertain history, and terminally
   mark execution `delivery_unknown`.
9. **Execution completion**: when every part is sent, mark completed and update
   configuration last-success fields only if newer.
10. **Failure/retry**: finish attempt and set retry or terminal state; update
    last-failure fields only for a terminal failure newer than the stored one.

## Retention

- Delivery history remains at least through the configured history horizon,
  which cannot be shorter than the ranking freshness horizon.
- Execution summaries and terminal state may outlive detailed attempts and
  delivery parts for audit.
- Rows needed by active retries, `sending`, or `unknown` reconciliation are never
  removed.
- Ranking and article records referenced by retained digest items/history use
  restrictive deletion; their existing retention jobs must skip referenced rows.

