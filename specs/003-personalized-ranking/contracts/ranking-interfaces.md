# Ranking Application Interfaces and Deterministic Policy

## Explicit preference ports

```text
ExplicitPreferenceInterpreter.interpret(
  request_id,
  statement,
  profile_snapshot,
  relevant_history,
) -> untrusted mapping

ExplicitPreferenceService.specify(
  user_identity,
  telegram_update_id,
  statement,
  language_code,
) -> SpecifyState

PreferenceRepository.claim_explicit_request(...)
PreferenceRepository.load_explicit_context(...)
PreferenceRepository.duplicate_candidates(...)
PreferenceRepository.apply_explicit_changes(...)
PreferenceRepository.fail_explicit_request(...)
```

Interpretation occurs outside a persistence transaction. Application uses one
profile revision compare-and-swap transaction.

## Evaluation ports

```text
ArticlePreferenceEvaluator.evaluate(
  article_snapshot,
  profile_snapshot,
  evaluation_identity,
) -> untrusted mapping

RankingRepository.claim_evaluation(...)
RankingRepository.load_evaluation_context(...)
RankingRepository.record_attempt(...)
RankingRepository.accept_evaluation(...)
RankingRepository.fail_evaluation(...)
```

The evaluator sees only bounded article content and the exact ordered active
parameter snapshot. Accepted results must cover every active parameter exactly
once and may not introduce unknown identifiers.

## Ranking ports

```text
PersonalRankingService.rank(
  user_id,
  request_id,
  candidate_article_ids,
  requested_count,
  ranking_at,
) -> RankingResult

RankingRepository.load_snapshot(...)
RankingRepository.find_complete_run(...)
RankingRepository.persist_complete_run(...)
RankingRepository.mark_stale_or_failed(...)
```

Repositories provide versioned domain snapshots; scoring and diversity services
do not import persistence or Telegram types.

## Exact scoring contract

For active nonzero-weight parameters:

```text
contribution_i = weight_i * relevance_i
numerator      = sum(contribution_i)
denominator    = sum(abs(weight_i))
personal_signed = numerator / denominator
personal_factor = (personal_signed + 1) / 2
```

Special states:

- no active parameters: signed `0`, factor `0.5`, `no_active_parameters`;
- all active weights zero: signed `0`, factor `0.5`, `all_weights_zero`;
- missing relevance for an active nonzero parameter: ineligible
  `incomplete_personal_evaluation`.

Final score:

```text
cP * personal_factor
+ cI * importance
+ cF * freshness
+ cQ * source_quality
+ cN * novelty
```

All factors and coefficients are in `[0,1]`, coefficients sum exactly `1.00000`,
and `cP >= 0.40000`. Arithmetic uses a fixed precision-28 decimal context and
half-even rounding. Intermediate values remain unquantized; persisted factors,
contributions, personal scores, and final score are quantized once to eight
decimal places.

Freshness under policy version 1:

```text
age_seconds = max(0, ranking_at - published_at)
freshness = max(0, 1 - age_seconds / freshness_horizon_seconds)
```

Publication beyond configured future tolerance is invalid.

## Eligibility contract

Before diversity, an article is excluded for any of:

- missing/currently incomplete generic analysis;
- incomplete personal evaluation when active nonzero parameters exist;
- source quality below configured minimum;
- missing or invalid publication time;
- age beyond the freshness horizon when obsolete filtering is enabled;
- disqualifying duplicate outcome;
- aligned explicit veto under configured policy.

No generic fallback silently converts incomplete personal evidence to neutral.

## Stable ranking order

```text
final_score DESC
personal_signed DESC
importance DESC
published_at DESC NULLS LAST
article_id ASC
```

This key is used in memory, persistence reads, replay tests, and explanation
ordering.

## Diversity contract

1. Sort eligible records by the stable ranking order.
2. Partition records into explicit-protected and ordinary groups without changing
   order within either group.
3. Greedily consider protected first, then ordinary records.
4. Select a record only if adding it respects the current event/topic/source cap
   vector.
5. If fewer than requested are selected, discard the attempt and rerun from the
   original groups under the next configured relaxation vector.
6. Stop when requested count is reached, candidates are exhausted, or all
   configured relaxation vectors are used.
7. Never relax eligibility or explicit vetoes.

Protection requires active explicit authority,
`abs(weight) >= explicit_weight_threshold`, and
`sign(weight) * relevance >= explicit_relevance_threshold`. Explicit veto uses
`sign(weight) * relevance <= -explicit_relevance_threshold`. Protection grants
first access to cap capacity; it does not bypass caps or quality.

Every record receives an eligibility and selection reason. A complete run stores
the cap vector used and unsatisfied limits.

## Snapshot and idempotency contract

- Explicit request: `(user_id, telegram_update_id, text_hash)`.
- Evaluation: user, article analysis, profile revision, parameter-set hash,
  schema, evaluator, and prompt versions.
- Ranking: `(user_id, request_id)` and a canonical snapshot key containing profile
  revision, candidate-set hash, configuration version, `ranking_at`, and requested
  count.
- Candidate hash orders article identities before hashing and includes article
  analysis, event, duplicate, source, and evaluation versions.
- The database claims identities atomically.
- Replays return complete persisted output.
- Same idempotency identity with different input hash fails.
- A version mismatch before completion marks the operation stale; snapshots are
  never mixed.

## Failure contract

- Retry only configured transient transport, rate-limit, and server failures.
- Reject schema, ownership, numeric, semantic, and configuration failures without
  broad retry.
- Never overwrite previous valid evaluation evidence with failed output.
- One stale `/specify` request may be reinterpreted once against the latest
  profile.
- One user's failed request, evaluation, or ranking does not cancel another's.
- No transaction remains open during an external model call.

## Explanation contract

User-facing explanations return factor values, final score, eligibility/selection
outcome, and the configured top contributions by absolute magnitude. Ties use
parameter ID. Internal evidence retains all contributions and hashes but never
stores or returns chain-of-thought.
