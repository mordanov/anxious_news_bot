# Contract: Digest Application Interfaces

## Domain Values

```text
DigestCount:
  integer in [5, 20]

DueOccurrence:
  execution_id
  user_id
  telegram_user_id
  occurrence_key
  scheduled_for_utc
  local_date
  local_time
  timezone_name
  schedule_revision
  digest_count

StructuredDigest:
  execution_id
  user_id
  language
  items[] ordered by position

StructuredDigestItem:
  position
  article_id
  article_analysis_id
  event_group_id?
  ranking_run_id
  title
  summary
  source
  publication_time
  url
  score
```

## DigestConfigurationRepository

```text
set_count(telegram_user_id, language_hint, count, changed_at)
  -> DigestConfigurationSnapshot

get(user_id)
  -> DigestConfigurationSnapshot | missing

claim_due(now, batch_size)
  -> tuple[DueOccurrence]

record_success(execution_id, completed_at)
  -> DigestExecutionSnapshot

record_failure(execution_id, failure, completed_at)
  -> DigestExecutionSnapshot
```

Rules:

- `set_count` rejects values outside `5..20` before persistence and ensures the
  shared application user/profile/digest configuration through the sole
  infrastructure provisioner.
- `claim_due` returns only enabled rows with `next_due_at <= now`.
- Claiming and advancing each configuration is atomic.
- Repeated claims for the same occurrence return no second execution.
- Success/failure summary fields use monotonic timestamp comparisons.
- “Failure summary” means the latest terminally failed execution; recovered
  transient attempts remain only in attempt history.

## Shared ApplicationUserProvisioner

```text
ensure(session, telegram_user_id, language_hint, digest_defaults)
  -> ProvisionedUser

ProvisionedUser:
  application_user
  preference_profile
  digest_configuration
```

Rules:

- Upserts all three rows in one caller-owned transaction.
- Uses disabled-safe digest defaults and never enables delivery implicitly.
- Is the sole creation path used by preference and digest repositories.
- Is concurrency-safe and self-heals a missing profile or configuration.

## DigestExecutionRepository

```text
claim_attempt(execution_id, phase, now)
  -> AttemptClaim | terminal | busy

record_selection(execution_id, selection)
  -> DigestExecutionSnapshot

record_items(execution_id, validated_items, now)
  -> StructuredDigest

load_digest(execution_id)
  -> StructuredDigest

prepare_delivery_parts(execution_id, part_descriptors)
  -> tuple[DeliveryPartSnapshot]

claim_delivery_part(execution_id, ordinal, now)
  -> DeliveryPartClaim | terminal | ambiguous

acknowledge_delivery_part(claim, provider_message_id, sent_at)
  -> DeliveryPartSnapshot

record_delivery_unknown(claim, reason_code, occurred_at)
  -> DigestExecutionSnapshot

record_transient_failure(attempt, reason_code, next_retry_at)
  -> DigestExecutionSnapshot

record_permanent_failure(attempt, reason_code, failed_at)
  -> DigestExecutionSnapshot

claim_retries(now, batch_size)
  -> tuple[execution_id]
```

Rules:

- State transitions follow `data-model.md`; compare-and-set rejects stale claims.
- Items are inserted as one exact contiguous set and become immutable.
- Preparing parts is idempotent only when ordinal, range, and content hash match.
- A `sent` or `unknown` part can never be claimed for automatic resend.
- Unknown delivery inserts conservative history and terminates automation.

## DigestHistoryFilter

Implements the ranking module's generic candidate-filter protocol:

```text
filter(user_id, candidate_ids, ranking_at)
  -> CandidateFilterResult

CandidateFilterResult:
  eligible_article_ids[] preserving input order
  decisions[]:
    article_id
    outcome: eligible | same_article | unchanged_story
    evidence_history_id?
    analysis_id?
```

Rules:

- Same normalized article is always excluded after confirmed or uncertain
  history.
- Same event group is excluded unless a later article has either accepted
  novelty at the configured threshold or persisted material-update evidence from
  the versioned deterministic producer below.
- Duplicate/review evidence and insufficient/short normalized text force
  `unchanged`.
- Decisions are deterministic and contain no free-form model reason.
- The filter does not reorder eligible candidates.

## MaterialUpdateEvidenceProducer

```text
evaluate(delivery_history, candidate_article, candidate_analysis, policy)
  -> MaterialUpdateEvidence

MaterialUpdateEvidence:
  delivery_history_id
  candidate_article_id
  candidate_analysis_id
  event_group_id
  policy_version
  basis: accepted_novelty | content_delta | insufficient_evidence
  outcome: material_update | unchanged
  prior_text_hash
  candidate_text_hash
  content_similarity?
  novelty_score?
  threshold_snapshot
```

Rules:

- Different articles, same event group, and later candidate publication are
  mandatory; otherwise outcome is unchanged.
- Accepted non-baseline or baseline analysis may qualify only when its novelty
  meets the configured threshold.
- Otherwise canonical normalized texts must each meet the configured minimum
  length and their deterministic similarity must be at or below the configured
  material-change maximum.
- A persisted near-duplicate decision with `duplicate` or `review` outcome for
  the pair vetoes content-delta qualification.
- The repository inserts or loads evidence under the unique pair/policy key
  before the history filter returns eligibility.
- Hashes and threshold snapshots make the decision auditable without copying
  article text into digest evidence or logs.

## Personal News Selection Extension

The ranking application service exposes:

```text
select_for_user(
  user_id,
  request_id,
  count,
  candidate_limit,
  candidate_filter?
) -> PersonalNewsSelection

PersonalNewsSelection:
  ranking_run_id?
  profile_revision
  ranking_at
  items[] ordered by selected position
```

Rules:

- `count` remains bounded by ranking and digest rules.
- `candidate_limit` is positive, no lower than count, and no greater than the
  ranking maximum.
- Candidate filtering occurs after recent generic candidates/analysis are
  prepared and before personal evaluation and ranking.
- Existing `top(telegram_user_id, request_id, count=10)` delegates to this path
  without a history filter, preserving `/news` behavior.
- Ranking mathematics and diversity stay exclusively in ranking services.

## DigestContentComposer

```text
compose(execution_id, language, ranked_items)
  -> tuple[LocalizedContent]

LocalizedContent:
  index
  title
  summary
```

Rules:

- Accepts `0..20` items; zero returns no model call.
- Sends only bounded title plus normalized summary/source-text excerpt as
  grounding.
- Returns the strict document in `digest-content.schema.json`.
- Exact indexes `1..N` must each occur once.
- Output is untrusted until strict schema and coverage validation pass.
- Source, publication time, URL, score, and IDs never come from the model.
- A validation/provider failure produces a typed transient or permanent
  composition failure; no partial output persists.

## DigestDeliveryPort

```text
render(digest, renderer_version)
  -> tuple[RenderedPart]

send(telegram_user_id, rendered_part)
  -> DeliveryAcknowledgement

RenderedPart:
  ordinal
  first_item_position
  last_item_position
  content
  content_hash

DeliveryAcknowledgement:
  provider_message_id
  accepted_at
```

Rules:

- Rendering is pure and deterministic for the same digest and renderer version.
- Every part stays within the provider message limit.
- Every item occurs in exactly one part in original order.
- `send` raises typed `DefiniteTransientDeliveryError`,
  `PermanentDeliveryError`, or `AmbiguousDeliveryError`.
- The execution service claims a part before calling `send`.
- Ambiguous errors are terminal and must not trigger automatic resend.

## DigestExecutionService

```text
execute(execution_id) -> DigestExecutionSnapshot
run_due_cycle(now) -> DueCycleResult
retry_due(now) -> RetryCycleResult
```

Execution order:

1. Claim attempt.
2. Load captured user/config/language/profile context.
3. Prepare recent analyzed candidates through personal-news selection.
4. Apply delivery-history candidate filter.
5. Reuse personal evaluation, deterministic ranking, and diversity.
6. Complete zero-item execution without delivery, or compose and persist all
   structured items.
7. Render and persist delivery part descriptors.
8. Claim/send/acknowledge each pending part in ordinal order.
9. Complete only when all parts are acknowledged.
10. Classify and persist transient, permanent, or ambiguous failure.

Cycle rules:

- One user's exception is captured and never cancels another execution.
- Concurrency and batch size are bounded configuration.
- A tick drains multiple claim batches until no due rows remain, the configured
  maximum claims per tick is reached, or the configured claim-time budget
  expires.
- The performance clock stops when the unique execution is durably claimed;
  ranking/model/delivery latency is measured separately.
- Retry claims use the same execution and skip completed preparation phases.
- Attempts stop at the configured maximum.

## Timing Adapter

```text
start()
stop()
tick(context)
```

- The adapter registers one repeating callback.
- The callback invokes due and retry cycles only.
- It contains no timezone, ranking, history, or retry classification logic.
- `start` and `stop` are idempotent.
