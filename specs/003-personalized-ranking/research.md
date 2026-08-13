# Research: Explicit Preferences and Personalized Ranking

## 1. Module ownership

**Decision**: Extend `preferences` for `/specify` and add a single `ranking`
module for user-specific article evaluation, mathematical scoring, explanations,
and diversity. Keep generic `ArticleAnalysis`, sources, normalized articles,
event groups, and duplicate decisions in `news`.

**Rationale**: The existing preferences module already owns profile revision CAS,
semantic duplicate handling, immutable origins, exact weights, and change audit.
The constitution assigns personalized decisions only to personal ranking and
requires aggregation to remain a general pool. One ranking module preserves that
boundary without adding a service.

**Alternatives considered**:
- Put relevance in `news`: rejected because user-specific evidence would leak
  personalization into general aggregation/analysis.
- Split evaluation, scoring, and diversity into separate deployables: rejected
  because no independent scaling or failure requirement exists.

## 2. Explicit authority over immutable origin

**Decision**: Keep `PreferenceParameter.origin` immutable. Add append-only
`PreferenceEvidence` for each applied `/specify` action. New concepts created by
`/specify` have `explicit` origin; reused questionnaire/inference/system concepts
retain creation provenance but gain explicit evidence. Effective policy authority
is the highest active evidence source in the order
`explicit > questionnaire > inference > system`.
When no evidence rows predate this feature, effective authority falls back to the
parameter's immutable origin. Migration `003` backfills evidence from retained
applied history where a source request can be identified.

**Rationale**: Origin answers "how was this canonical concept created?" while
evidence answers "what authority currently supports it?" Separating them preserves
provenance, satisfies the existing database immutability trigger, and lets direct
user intent govern later policy and diversity.

**Alternatives considered**:
- Rewrite origin to `explicit`: rejected because it destroys provenance and
  conflicts with existing immutability.
- Duplicate a reused parameter with explicit origin: rejected because it violates
  semantic uniqueness.
- Add only a mutable authority flag: rejected because it lacks per-request audit
  and cannot explain supersession.

## 3. Explicit update policy

**Decision**: `/specify` may create an explicit-origin parameter or adjust,
refine, deactivate, or reactivate any semantically matching user-owned parameter,
subject to whole-batch validation. It may not mutate unrelated explicit
parameters. Every applied target receives explicit evidence and source=`explicit`
history. Exact or semantic equivalents are reused; a narrower distinct concept
may be created.

**Rationale**: Explicit intent must outrank weaker evidence but cannot be used as
an excuse to alter unrelated direct user choices. The existing incremental,
atomic profile update machinery can be generalized around an action-by-source
policy instead of duplicated.

**Alternatives considered**:
- Allow explicit updates only against explicit-origin parameters: rejected because
  weaker questionnaire or inferred state could not be corrected by the user.
- Replace the full profile from `/specify`: rejected because failure and model
  variability would put unrelated preferences at risk.

## 4. Personal score normalization

**Decision**: For complete relevance evidence over active nonzero-weight
parameters:

```text
numerator   = sum(weight_i * relevance_i)
denominator = sum(abs(weight_i))
personal_signed = numerator / denominator
personal_factor = (personal_signed + 1) / 2
```

`personal_signed` is in `[-1,1]`; `personal_factor` is in `[0,1]`. If there are no
active parameters, or all active weights are zero, the signed score is `0` and
the factor is `0.5`, with distinct evidence states. A missing relevance for any
active nonzero-weight parameter makes personal evaluation incomplete rather than
silently neutral.

**Rationale**: The weighted mean cannot grow with parameter count and zero-weight
parameters do not dilute results. Mapping only for final-factor combination
preserves the signed personal score in explanations.

**Alternatives considered**:
- Raw dot product: rejected because its range changes with profile size.
- Divide by parameter count: rejected because zero and tiny parameters dilute
  strong evidence.
- Silently substitute missing relevance with zero: rejected because absence is
  not neutral evidence.

## 5. Generic factors, freshness, and coefficients

**Decision**: Importance, freshness, source quality, novelty, and mapped personal
relevance are exact decimals in `[0,1]`. Initial freshness is a versioned linear
decay from `1` at publication to `0` at a configurable 72-hour horizon, evaluated
against immutable `ranking_at`; publication more than five minutes in the future
is invalid. Final score is:

```text
final = c_personal * personal_factor
      + c_importance * importance
      + c_freshness * freshness
      + c_quality * source_quality
      + c_novelty * novelty
```

Initial coefficients are `0.45`, `0.20`, `0.15`, `0.10`, and `0.10`. Every
coefficient is in `[0,1]`, the exact sum is `1.00000`, and personal is at least
`0.40000`. Invalid configuration fails closed; coefficients are not silently
renormalized.

**Rationale**: A convex combination keeps the final score predictable in `[0,1]`.
The personal floor prevents generic importance from dominating valid
configuration, while separate factors remain explainable.

**Alternatives considered**:
- Add raw age or timestamps: rejected because units are incomparable.
- Implicitly renormalize arbitrary coefficients: rejected because the stored
  configuration would not describe the calculation actually performed.
- Exponential decay initially: deferred because linear decay is easier to inspect
  and the policy is versioned/configurable.

## 6. Exact arithmetic, rounding, and ordering

**Decision**: Parse canonical decimal strings directly into `Decimal`; never pass
through binary float. Use one explicit context with precision 28 and
`ROUND_HALF_EVEN`. Retain unquantized intermediate values and quantize final
factor, contribution, personal, and final-score persistence to eight decimal
places. Sort by:

```text
final_score DESC
personal_signed DESC
importance DESC
published_at DESC NULLS LAST
article_id ASC
```

**Rationale**: Exact numeric storage and an explicit rounding boundary make Python
and PostgreSQL behavior reproducible. A complete final key removes unspecified
tie ordering.

**Alternatives considered**:
- Float arithmetic: rejected because repeated calculations and serialization can
  differ.
- Random or ingestion-order ties: rejected because neither is stable input
  evidence.

**References**:
- [PostgreSQL exact numeric types](https://www.postgresql.org/docs/current/datatype-numeric.html)
- [PostgreSQL result ordering](https://www.postgresql.org/docs/current/queries-order.html)
- [Python decimal arithmetic](https://docs.python.org/3/library/decimal.html)

## 7. Quality gates and incomplete evidence

**Decision**: Rank only articles with a current complete generic analysis, valid
publication timestamp, source quality at or above configurable `0.35`, no
disqualifying duplicate decision, and complete personal evaluation when active
nonzero preferences exist. No-active/all-zero profiles use the documented neutral
personal state. Model evaluation failure produces an incomplete run eligible for
reprocessing and never overwrites a prior valid version.

**Rationale**: This separates lack of evidence from neutral evidence and prevents
personal relevance from rescuing obsolete, duplicate, or untrusted content.

**Alternatives considered**:
- Generic fallback after failed personal evaluation: rejected for the first
  release because it can silently ignore direct intent. Returning fewer eligible
  results is controlled and explainable.
- Delete the previous valid evaluation before retry: rejected because transient
  failures would regress durable state.

## 8. Deterministic diversity

**Decision**: Apply quality gates, then sort canonically and greedily select under
configured event/topic/source caps. Initial caps are event `2`, topic `3`, source
`3` for a ten-item target. Articles with aligned explicit-authority contribution
meeting configured absolute weight `0.75` and
`sign(weight) * relevance >= 0.60` are "protected" and consume capacity first,
but never bypass eligibility or the current cap vector. The symmetric condition
`sign(weight) * relevance <= -0.60` is an explicit veto. If the target cannot be
filled, retry selection from the original sorted pool using versioned cap vectors
that relax source first, then topic, then event. Record the chosen vector and every
rejection/relaxation; return fewer items if eligible candidates are exhausted.

**Rationale**: Constrained greedy selection is simple, deterministic, and directly
explainable. Protection gives explicit intent first access to limited capacity
without turning it into a quality bypass.

**Alternatives considered**:
- Random shuffling: rejected because replay is impossible.
- Maximal marginal relevance: deferred because it adds similarity calibration and
  explanation complexity not required by current event/topic/source metadata.
- Post-hoc swaps: rejected because cascading cap effects are harder to audit.

## 9. Idempotency and immutable snapshots

**Decision**:

- Explicit request identity: unique `(user_id, telegram_update_id)` with
  normalized text hash; same key with a different hash is rejected.
- Explicit interpretation identity: request ID, base profile revision, schema,
  prompt, and model versions.
- Evaluation identity: user, article, article-analysis ID, profile revision,
  relevance schema, evaluator version.
- Ranking identity: caller request ID, user, profile revision, candidate-set hash,
  ranking configuration version, and immutable `ranking_at`.
- Candidate-set hash: canonical digest over sorted article IDs plus article
  analysis, event assignment, duplicate decision, and evaluation versions.

Unique constraints claim each operation. Retries append attempts; the first
schema-valid accepted result wins. Profile mutation retains revision CAS. Ranking
runs consume one snapshot and do not mix evidence versions.

**Rationale**: Idempotency keys express business identity rather than timing and
allow safe replay after Telegram, HTTP, or process retries.

**Alternatives considered**:
- Deduplicate only by text: rejected because a user may intentionally repeat a
  statement later.
- Treat timestamps as identity: rejected because retries naturally receive new
  timestamps.

**Reference**:
- [PostgreSQL INSERT ON CONFLICT](https://www.postgresql.org/docs/current/sql-insert.html)

## 10. Retry and stale-input behavior

**Decision**: Retry only transient transport errors, rate limits, and server
errors with configured capped exponential backoff. Schema, ownership, semantic,
and configuration failures are terminal for that attempt. `/specify` interprets
outside a transaction; one stale profile conflict reloads, rematches, and
reinterprets once. Evaluation attempts are append-only and individually isolated.
Before accepting a rank for downstream use, input hashes and versions must still
match; otherwise the run becomes stale and is recomputed.

**Rationale**: Bounded retries recover transient failures without multiplying
invalid requests. Fresh interpretation is required because applying old semantic
targets to a new profile is unsafe.

**Alternatives considered**:
- Retry every exception: rejected because validation and authentication failures
  are not transient.
- Apply stale output if target IDs still exist: rejected because semantic context,
  authority, and weights may have changed.

**Reference**:
- [Google Cloud retry strategy guidance](https://cloud.google.com/storage/docs/retry-strategy)

## 11. Explanation and retention

**Decision**: Persist factor snapshots, coefficients, unrounded canonical input
hashes, quantized results, all signed parameter contributions, eligibility,
protection, cap vector, exclusion reason, and final position. User-facing output
shows the top three contributions by absolute magnitude with stable ties; it
never exposes prompts or chain-of-thought. Raw explicit text and raw model
responses default to 30 days, full evaluation/ranking detail to 90 days, and
operational logs to 14 days. Preference statements and compact profile audit
follow account-lifetime policy. Compact ranking audit rows with input, factor,
score, configuration, and selection hashes remain while any delivery reference
depends on them. Cleanup is bounded, excludes active runs, and refuses detailed
deletion without required compact evidence.

**Rationale**: This is sufficient to reconstruct accepted scores while minimizing
sensitive free text and verbose model data.

**Alternatives considered**:
- Store only final score: rejected because ranking would not be explainable.
- Retain raw prompts indefinitely: rejected by minimization and purpose-specific
  retention principles.

**References**:
- [JSON Schema 2020-12](https://json-schema.org/draft/2020-12/json-schema-core)
- [EDPB data protection basics](https://www.edpb.europa.eu/sme/learn-the-basics/data-protection-basics_en)
