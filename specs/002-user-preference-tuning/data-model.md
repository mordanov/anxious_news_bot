# Data Model: User Preference Tuning

## ApplicationUser

Stable application identity mapped from the Telegram adapter.

| Field | Type | Rules |
|---|---|---|
| id | UUID | Primary key, application-assigned |
| telegram_user_id | 64-bit integer | Required, unique |
| language_code | text | Optional normalized interaction language |
| created_at / updated_at | timestamp | UTC |

**Constraints**: Telegram identity is resolved at the adapter boundary. Preference
services receive `ApplicationUser.id`, not an unverified Telegram identifier.

## PreferenceProfile

Concurrency and lifecycle root for one user's parameters.

| Field | Type | Rules |
|---|---|---|
| user_id | UUID | Primary key and reference to ApplicationUser |
| revision | integer | Non-negative, starts at 0, increments once per applied batch |
| created_at / updated_at | timestamp | UTC |

**Constraints**: Exactly one profile per user. A revision compare-and-swap protects
multi-row updates from stale interpretation and lost updates.

## PreferenceParameter

One durable semantic dimension used by future personal ranking.

| Field | Type | Rules |
|---|---|---|
| id | UUID | Primary key, stable |
| user_id | UUID | Required reference to PreferenceProfile |
| semantic_key | text | Required normalized meaning key |
| name | text | Required, non-blank, bounded |
| description | text | Required, non-blank, bounded |
| evaluation_instructions | text | Required, non-blank, bounded |
| weight | decimal | Required `NUMERIC(3,2)`, range -1.00–1.00 |
| origin | enum | `questionnaire`, `explicit`, `inference`, `system` |
| active | boolean | Required, defaults true |
| created_at / updated_at | timestamp | UTC |

**Constraints**: `(user_id, semantic_key)` is unique across active and inactive
parameters so equivalent concepts are refined or reactivated rather than
recreated. Weight has a database range check; application validation rejects
non-canonical precision before persistence. Questionnaire application cannot
change an explicit parameter in a way that weakens, generalizes, or relabels its
specific intent.

## Questionnaire

Durable `/tune` session and its processing state.

| Field | Type | Rules |
|---|---|---|
| id | UUID | Primary key |
| user_id | UUID | Required reference to ApplicationUser |
| status | enum | See state transitions |
| schema_version | text | Required questionnaire contract version |
| profile_revision | integer | Revision supplied to generation |
| generation_context_hash | text | Required deterministic hash of bounded context |
| error_code | text | Optional sanitized terminal/retry classification |
| created_at / updated_at | timestamp | UTC |
| completed_at | timestamp | Optional UTC terminal time |

**Constraints**: A partial unique index permits only one questionnaire per user in
`generating`, `answering`, `answers_complete`, `interpreting`, or `applying`.
Question and answer content is not copied into logs.

**Transitions**:

```text
generating -> answering
generating -> failed
answering -> answers_complete
answers_complete -> interpreting
interpreting -> applying
interpreting -> failed
applying -> applied
applying -> answers_complete   (stale profile; regenerate interpretation)
applying -> failed             (non-retryable validated/application failure)
```

Only `applied` and `failed` are terminal. `/tune` resumes any nonterminal state.

## QuestionnaireQuestion

One generated question in a questionnaire.

| Field | Type | Rules |
|---|---|---|
| id | UUID | Primary key, application-assigned |
| questionnaire_id | UUID | Required reference to Questionnaire |
| ordinal | integer | Required, range 1–10 |
| dimension_key | text | Required normalized generation dimension |
| text | text | Required, non-blank, bounded |
| created_at | timestamp | UTC |

**Constraints**: `(questionnaire_id, ordinal)` is unique. A completed generated
questionnaire has exactly ordinals 1 through 10. Dimension and text uniqueness are
validated across the questionnaire and relevant prior context.

## QuestionOption

One offered answer for a generated question.

| Field | Type | Rules |
|---|---|---|
| id | UUID | Primary key, application-assigned |
| question_id | UUID | Required reference to QuestionnaireQuestion |
| ordinal | integer | Required, range 1–4 |
| label | text | Required, non-blank, bounded |
| callback_token_hash | text | Required, unique cryptographic digest |
| created_at | timestamp | UTC |

**Constraints**: `(question_id, ordinal)` and normalized `(question_id, label)` are
unique. Exactly ordinals 1 through 4 exist for every accepted question. Only the
opaque token is sent to Telegram; lookup uses its digest.

## QuestionnaireAnswer

The one selected option for a question.

| Field | Type | Rules |
|---|---|---|
| id | UUID | Primary key |
| question_id | UUID | Required, unique reference to QuestionnaireQuestion |
| option_id | UUID | Required reference to QuestionOption |
| answered_at | timestamp | UTC |

**Constraints**: The option must belong to the referenced question, enforced by a
composite relationship or application validation plus database keys. Unique
`question_id` makes duplicate callback delivery idempotent. Answers are immutable.

## PreferenceUpdateBatch

One validated interpretation and its idempotent application record.

| Field | Type | Rules |
|---|---|---|
| id | UUID | Primary key |
| questionnaire_id | UUID | Required, unique reference to Questionnaire |
| user_id | UUID | Required reference to PreferenceProfile |
| schema_version | text | Required change-contract version |
| base_profile_revision | integer | Required non-negative revision |
| proposal_hash | text | Required deterministic hash of normalized changes |
| status | enum | `validated`, `applied`, `stale`, `rejected` |
| error_code | text | Optional sanitized classification |
| created_at / applied_at | timestamp | UTC |

**Constraints**: Only a fully validated normalized proposal can create a batch.
The batch, profile revision increment, parameter mutations, history, and applied
questionnaire state commit in one transaction. A unique questionnaire reference
prevents replay.

## PreferenceChangeHistory

Immutable audit record for one parameter action in an applied batch.

| Field | Type | Rules |
|---|---|---|
| id | UUID | Primary key |
| batch_id | UUID | Required reference to PreferenceUpdateBatch |
| parameter_id | UUID | Required reference to PreferenceParameter |
| action | enum | `create`, `adjust`, `refine`, `deactivate`, `reactivate` |
| source | enum | `questionnaire`, `explicit`, `inference`, `system` |
| questionnaire_id | UUID | Optional; required for questionnaire source |
| previous_state | JSON | Null only for create; strict parameter snapshot |
| new_state | JSON | Required strict parameter snapshot |
| reason | text | Required, non-blank, bounded |
| changed_at | timestamp | UTC |

**Constraints**: `(batch_id, parameter_id, action)` is unique. Snapshots include
semantic key, descriptive fields, exact weight string, origin, and active state.
Rows are append-only.

## Relationships

```text
ApplicationUser 1 ── 1 PreferenceProfile 1 ── * PreferenceParameter
ApplicationUser 1 ── * Questionnaire
Questionnaire 1 ── 10 QuestionnaireQuestion
QuestionnaireQuestion 1 ── 4 QuestionOption
QuestionnaireQuestion 1 ── 0..1 QuestionnaireAnswer
Questionnaire 1 ── 0..1 PreferenceUpdateBatch
PreferenceUpdateBatch 1 ── * PreferenceChangeHistory
PreferenceParameter 1 ── * PreferenceChangeHistory
```

## Transaction and idempotency rules

1. Creating a questionnaire claims the user's active-session partial unique index.
   A conflict loads and resumes the existing session.
2. Generated questions and options become visible only after the complete document
   passes structural and semantic validation.
3. Recording an answer inserts once by question identity and returns the persisted
   current state after any conflict.
4. The tenth answer and `answers_complete` transition commit together.
5. Interpretation runs outside a database transaction against a captured profile
   revision.
6. Application claims the questionnaire, compares and increments the expected
   profile revision, applies all changes, writes history, and marks the batch and
   questionnaire applied in one transaction.
7. A stale revision applies nothing and returns the questionnaire to
   `answers_complete` for fresh interpretation.

## Retention and privacy

- Preference parameters and applied history remain durable while the user profile
  exists.
- Questionnaire content, selected answers, context hashes, and applied batch
  references remain long enough to support adaptation and audit; retention is
  configurable and deletion must preserve any legally required minimal audit
  linkage.
- Raw model requests/responses are not stored by default. Invalid outcomes retain
  schema version, stage, sanitized error code, and correlation identifiers.
- Structured logs exclude question/answer text, model credentials, callback
  tokens, and full profile snapshots.
