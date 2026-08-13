# Data Model: Explicit Preferences and Personalized Ranking

This feature extends the existing users, profiles, preference parameters, change
history, news sources, normalized articles, generic analyses, event groups, and
duplicate decisions. Existing identifiers remain stable.

## Existing entity changes

### PreferenceUpdateBatch

Generalize the existing questionnaire-only batch so exactly one source request
owns each batch.

| Field | Type | Rules |
|---|---|---|
| questionnaire_id | UUID | Becomes optional unique reference |
| explicit_request_id | UUID | Optional unique reference to ExplicitPreferenceRequest |
| remaining fields | existing | Unchanged revision, proposal hash, status, count, digest, timestamps |

**Constraints**:

- Exactly one of `questionnaire_id` and `explicit_request_id` is non-null.
- `questionnaire` batches retain the existing questionnaire source policy.
- `explicit` batches apply the policy in [Explicit update authority](#explicit-update-authority).
- Batch, profile revision, parameter mutations, evidence, full history, compact
  audit, request completion, and resulting revision commit in one transaction.

### PreferenceChangeHistory

| New field | Type | Rules |
|---|---|---|
| explicit_request_id | UUID | Optional reference; required when source is `explicit` |

Exactly one applicable source reference is retained for questionnaire and explicit
changes. Existing source, snapshots, reason, and timestamp remain append-only.

### PreferenceChangeAudit

| New field | Type | Rules |
|---|---|---|
| explicit_request_id | UUID | Optional reference; required when source is `explicit` |

Compact audit rows retain request identity after full history or raw request text
expires. Existing database triggers continue to reject updates and deletes.

## ExplicitPreferenceRequest

Durable `/specify` request, idempotency record, and processing state.

| Field | Type | Rules |
|---|---|---|
| id | UUID | Primary key |
| user_id | UUID | Required reference to ApplicationUser |
| telegram_update_id | 64-bit integer | Required adapter idempotency identity |
| normalized_text_hash | text | Required 64-character canonical digest |
| raw_text | text | Required initially, non-blank, bounded; retention-eligible |
| language_code | text | Optional normalized language |
| status | enum | See transitions |
| schema_version | text | Required explicit-change contract version |
| base_profile_revision | integer | Required non-negative revision |
| interpretation_version | text | Optional until interpretation begins |
| proposal_hash | text | Optional until a proposal validates |
| error_code | text | Optional sanitized failure classification |
| created_at / updated_at | timestamp | UTC |
| completed_at | timestamp | Optional UTC terminal time |

**Constraints**:

- `(user_id, telegram_update_id)` is unique.
- Replaying the same identity and text hash returns persisted state.
- Reusing the identity with a different text hash is rejected.
- `raw_text` may be compacted to null after retention; hash and request identity
  remain.

**Transitions**:

```text
received -> interpreting
received -> failed
interpreting -> validated
interpreting -> failed
validated -> applying
validated -> stale
applying -> applied
applying -> stale
applying -> failed
stale -> interpreting        (one bounded re-interpretation)
```

`applied` and `failed` are terminal. A stale request after the configured retry
limit becomes `failed`.

## PreferenceEvidence

Append-only authority evidence linking an accepted preference action to the
canonical parameter it supports.

| Field | Type | Rules |
|---|---|---|
| id | UUID | Primary key; shared with matching change identity where practical |
| parameter_id | UUID | Required reference to PreferenceParameter |
| user_id | UUID | Required reference to PreferenceProfile |
| source | enum | `explicit`, `questionnaire`, `inference`, or `system` |
| explicit_request_id | UUID | Required for explicit source |
| questionnaire_id | UUID | Required for questionnaire source |
| action | enum | `create`, `adjust`, `refine`, `deactivate`, `reactivate` |
| requested_weight | decimal | Optional exact weight for create/adjust evidence |
| active | boolean | Evidence lifecycle state produced by the action |
| reason_hash | text | Required canonical reason digest |
| created_at | timestamp | UTC, immutable |

**Constraints**:

- Exactly one applicable source request is set.
- Rows are immutable and not removed by verbose-history retention.
- Parameter `origin` remains immutable creation provenance.
- Effective authority is derived from applicable evidence in precedence order
  `explicit > questionnaire > inference > system`; it is not stored as a mutable
  replacement for origin.
- Parameters without evidence rows fall back to immutable origin. Migration `003`
  backfills evidence from retained applied history when its source request is
  available.

## Explicit update authority

| Target creation origin | Adjust | Refine | Deactivate | Reactivate | Equivalent create |
|---|---|---|---|---|---|
| explicit | Allowed if semantically targeted | Allowed | Allowed | Allowed | Reuse |
| questionnaire | Allowed; attach explicit evidence | Allowed | Allowed | Allowed | Reuse |
| inference | Allowed; attach explicit evidence | Allowed | Allowed | Allowed | Reuse |
| system | Allowed when user-owned and not policy-locked | Allowed | Allowed | Allowed | Reuse |

All actions require target ownership, semantic relation to the request, a changed
result, and whole-batch validation. Unrelated explicit parameters are protected.
A distinct narrower concept may create a new explicit-origin parameter.

## ArticlePreferenceEvaluationRun

One versioned attempt group to evaluate an article against a profile snapshot.

| Field | Type | Rules |
|---|---|---|
| id | UUID | Primary key |
| user_id | UUID | Required reference to PreferenceProfile |
| article_id | UUID | Required reference to NormalizedArticle |
| article_analysis_id | UUID | Required complete generic ArticleAnalysis |
| profile_revision | integer | Required non-negative captured revision |
| parameter_set_hash | text | Required digest of ordered active parameter snapshots |
| schema_version | text | Required relevance contract version |
| evaluator_name / evaluator_version | text | Required |
| prompt_version | text | Required |
| status | enum | `pending`, `evaluating`, `complete`, `incomplete`, `failed`, `stale` |
| attempt_count | integer | Non-negative, bounded by configuration |
| accepted_attempt_id | UUID | Optional reference to successful attempt |
| error_code | text | Optional sanitized terminal classification |
| created_at / updated_at / completed_at | timestamp | UTC |

**Constraints**:

- Unique by user, article, article analysis, profile revision, parameter-set hash,
  schema version, evaluator version, and prompt version.
- Only one accepted attempt exists.
- A new failed version never changes an older valid version.

**Transitions**:

```text
pending -> evaluating
evaluating -> complete
evaluating -> incomplete
evaluating -> failed
pending/evaluating -> stale
incomplete/failed -> evaluating   (bounded later retry)
```

## ArticlePreferenceEvaluationAttempt

Append-only diagnostic record for one external evaluation attempt.

| Field | Type | Rules |
|---|---|---|
| id | UUID | Primary key |
| run_id | UUID | Required reference to ArticlePreferenceEvaluationRun |
| ordinal | integer | Positive and unique within run |
| response_hash | text | Optional digest; raw response separately retention-limited |
| raw_response | JSON/text | Optional bounded untrusted response; retention-eligible |
| status | enum | `received`, `invalid`, `transient_failure`, `accepted`, `failed` |
| error_code | text | Optional sanitized classification |
| started_at / completed_at | timestamp | UTC |

No prompt, credential, or chain-of-thought is retained.

## ArticleParameterRelevance

Accepted relevance for one active parameter in an evaluation run.

| Field | Type | Rules |
|---|---|---|
| id | UUID | Primary key |
| evaluation_run_id | UUID | Required reference to complete run |
| parameter_id | UUID | Required reference to PreferenceParameter |
| parameter_snapshot_hash | text | Required canonical parameter digest |
| relevance | decimal | Required `NUMERIC(5,4)`, range -1.0000–1.0000 |
| reason_code | text | Required bounded classification, not chain-of-thought |
| created_at | timestamp | UTC |

**Constraints**:

- `(evaluation_run_id, parameter_id)` is unique.
- The accepted parameter set exactly equals the run's active parameter snapshot.
- Negative zero, excess precision, and float-derived values are rejected before
  persistence.
- Rows become immutable when the run becomes complete.

## RankingConfigurationSnapshot

Versioned validated calculation and selection policy retained for replay.

| Field | Type | Rules |
|---|---|---|
| version | text | Primary key, stable |
| configuration_hash | text | Required unique canonical digest |
| personal / importance / freshness / quality / novelty coefficient | decimal | Each `NUMERIC(6,5)`, range 0–1 |
| freshness_horizon_seconds | integer | Positive |
| future_tolerance_seconds | integer | Non-negative |
| minimum_source_quality | decimal | Range 0–1 |
| maximum_candidate_count | integer | Positive, initial maximum 500 |
| event / topic / source caps | integer | Positive |
| explicit_weight_threshold | decimal | Range 0–1 |
| explicit_relevance_threshold | decimal | Range 0–1 |
| explanation_contribution_limit | integer | Positive |
| tie_policy_version | text | Required |
| retention_policy_version | text | Required |
| created_at | timestamp | UTC |

**Constraints**:

- Coefficients sum exactly `1.00000`.
- Personal coefficient is at least `0.40000`.
- Configuration is immutable once referenced by a ranking run.
- Relaxation vectors are derived deterministically from the base caps and included
  in the canonical configuration hash.
- Explicit protection is
  `abs(weight) >= weight_threshold AND sign(weight) * relevance >= relevance_threshold`.
  Explicit veto uses the symmetric negative relevance threshold.

## RankingRun

One immutable-input scoring and diversity operation for one user.

| Field | Type | Rules |
|---|---|---|
| id | UUID | Primary key |
| request_id | text/UUID | Required caller idempotency identity |
| user_id | UUID | Required reference to PreferenceProfile |
| profile_revision | integer | Required captured revision |
| candidate_set_hash | text | Required canonical digest |
| configuration_version | text | Required reference to RankingConfigurationSnapshot |
| ranking_at | timestamp | Required immutable calculation time |
| requested_count | integer | Positive |
| status | enum | `pending`, `scoring`, `diversifying`, `complete`, `failed`, `stale` |
| selected_count / excluded_count | integer | Non-negative |
| selected_cap_vector | JSON | Optional until complete; validated integer caps |
| unsatisfied_limits | JSON | Required list, empty when all satisfied |
| error_code | text | Optional sanitized classification |
| created_at / completed_at | timestamp | UTC |

**Constraints**:

- `(user_id, request_id)` is unique.
- A unique snapshot key covers user, profile revision, candidate-set hash,
  configuration version, ranking_at, and requested count.
- `selected_count <= requested_count`.
- Runs are append-only after `complete`.

**Transitions**:

```text
pending -> scoring
scoring -> diversifying
scoring -> failed
scoring -> stale
diversifying -> complete
diversifying -> failed
diversifying -> stale
```

## ArticleRankingRecord

Score, eligibility, and final disposition of one candidate article.

| Field | Type | Rules |
|---|---|---|
| id | UUID | Primary key |
| ranking_run_id | UUID | Required reference to RankingRun |
| article_id | UUID | Required reference to NormalizedArticle |
| article_analysis_id | UUID | Optional only when generic analysis is missing; otherwise references the accepted ArticleAnalysis |
| evaluation_run_id | UUID | Optional for documented neutral or ineligible states |
| event_group_id / source_id | UUID | Snapshot identities used by diversity |
| topic_key | text | Optional deterministic primary topic snapshot |
| personal_numerator / denominator | decimal | Required exact snapshots |
| personal_state | enum | `complete`, `no_active_parameters`, `all_weights_zero` |
| personal_signed / personal_factor | decimal | Required bounded values |
| importance / freshness / quality / novelty | decimal | Required normalized values |
| unrounded_score | decimal | Required high-precision canonical value |
| final_score | decimal | Required eight-decimal rounded value |
| eligible | boolean | Required |
| eligibility_reason | text | Required code |
| explicit_protected | boolean | Required |
| explicit_veto | boolean | Required |
| initial_position | integer | Optional; set for eligible sorted candidates |
| final_position | integer | Optional; set only when selected |
| selection_reason | text | Required code |
| diversity_pass | integer | Optional selected relaxation pass |

**Constraints**:

- `(ranking_run_id, article_id)` is unique.
- All factors and final score are in `[0,1]`; signed personal score is in
  `[-1,1]`.
- Ineligible or vetoed records have no final position.
- Final positions are unique and contiguous within a complete run.

## RankingParameterContribution

Immutable contribution snapshot for one active nonzero-weight parameter.

| Field | Type | Rules |
|---|---|---|
| id | UUID | Primary key |
| article_ranking_id | UUID | Required reference to ArticleRankingRecord |
| parameter_id | UUID | Required stable identity |
| parameter_snapshot_hash | text | Required |
| parameter_origin | enum | Required creation provenance snapshot |
| effective_authority | enum | Required derived authority snapshot |
| weight | decimal | Required exact `NUMERIC(3,2)` |
| relevance | decimal | Required `NUMERIC(5,4)` |
| contribution | decimal | Required signed eight-decimal value |
| explanation_ordinal | integer | Optional, unique when displayed |

**Constraints**:

- `(article_ranking_id, parameter_id)` is unique.
- Contribution equals weight multiplied by relevance under the canonical decimal
  policy.
- Display ordinals select the configured largest absolute contributions, then
  stable parameter identifier.

## RankingAudit

Compact immutable evidence retained when verbose ranking detail expires.

| Field | Type | Rules |
|---|---|---|
| id | UUID | Primary key shared with ArticleRankingRecord |
| ranking_run_id / user_id / article_id | UUID | Required identities |
| profile_revision | integer | Required |
| configuration_version | text | Required |
| input_hash | text | Required canonical input digest |
| factor_hash | text | Required factor and coefficient digest |
| contribution_hash | text | Required ordered contribution digest |
| score_hash | text | Required signed/personal/final score digest |
| selection_hash | text | Required eligibility/diversity outcome digest |
| final_score | decimal | Required eight-decimal value |
| final_position | integer | Optional |
| ranked_at | timestamp | Required UTC |

Rows are append-only and retained while any downstream delivery reference depends
on the ranking.

## Relationships

```text
ApplicationUser 1 ── * ExplicitPreferenceRequest
ExplicitPreferenceRequest 1 ── 0..1 PreferenceUpdateBatch
ExplicitPreferenceRequest 1 ── * PreferenceEvidence
PreferenceParameter 1 ── * PreferenceEvidence

ApplicationUser 1 ── * ArticlePreferenceEvaluationRun
NormalizedArticle 1 ── * ArticlePreferenceEvaluationRun
ArticleAnalysis 1 ── * ArticlePreferenceEvaluationRun
ArticlePreferenceEvaluationRun 1 ── * ArticlePreferenceEvaluationAttempt
ArticlePreferenceEvaluationRun 1 ── * ArticleParameterRelevance
PreferenceParameter 1 ── * ArticleParameterRelevance

ApplicationUser 1 ── * RankingRun
RankingConfigurationSnapshot 1 ── * RankingRun
RankingRun 1 ── * ArticleRankingRecord
ArticleRankingRecord 1 ── * RankingParameterContribution
ArticleRankingRecord 1 ── 1 RankingAudit
```

## Transaction and concurrency rules

1. `/specify` claims `(user_id, telegram_update_id)` before interpretation.
2. Interpretation reads bounded history and a profile snapshot, then runs outside
   a transaction.
3. Application claims the request, verifies semantic targets and profile revision,
   applies the full batch, increments the revision once, writes evidence, full
   history, compact audit, and terminal request state in one transaction.
4. A stale profile commits no parameter changes and permits one fresh
   reinterpretation.
5. Evaluation run identity is claimed before an external call. Each attempt is
   append-only; only a complete document covering the exact parameter snapshot is
   accepted atomically.
6. Ranking loads one profile/configuration/candidate evidence snapshot, calculates
   outside write transactions, then persists the run, all candidate records,
   contributions, compact audits, and completion state atomically.
7. Before a ranking becomes complete, all input versions and the candidate hash
   are rechecked. A mismatch marks the run stale and persists no complete result.
8. Replaying an applied request, complete evaluation, or complete ranking returns
   the persisted outcome.

## Retention and privacy

- Raw explicit request text and raw untrusted responses default to 30 days.
- Full evaluation attempts, relevance details, ranking records, contributions, and
  selection evidence default to 90 days.
- PreferenceEvidence and existing compact preference audit follow the account
  audit lifetime and are not removed by verbose cleanup.
- RankingAudit remains while any retained delivery reference points to it.
- Cleanup operates in configured bounded batches, excludes active requests/runs,
  preserves current preference parameters and accepted reusable evaluations, and
  refuses detailed deletion when required compact evidence is absent.
- Logs contain safe identities, versions, counts, stage/status, and error codes;
  they exclude raw statements, article text, prompts, responses, credentials,
  and profile snapshots.
