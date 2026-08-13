# Contract: User Preference Tuning Interfaces

These contracts define application behavior independently from Telegram,
PostgreSQL, and any model provider.

## Shared values

### ProfileSnapshot

Contains user identity, profile revision, and bounded parameter snapshots with
stable identifier, semantic key, name, description, evaluation instructions,
canonical weight string, origin, and active state.

### QuestionnaireContext

Contains the profile snapshot, interaction language, bounded relevant prior
questions and selected option labels, strong-interest dimensions, ambiguous
dimensions, and configured quality/repetition rules. It contains no repository,
credentials, Telegram objects, or authority to write state.

### TuneState

One of `generating`, `question`, `processing`, `completed`, or `failed`. A question
state contains questionnaire identity, ordinal/count, text, and four opaque option
tokens with labels. It never exposes internal option or user identifiers.

## QuestionnaireGenerator

`generate(context) -> Mapping[str, object]`

- MUST return a document intended to conform to
  [questionnaire-generation.schema.json](questionnaire-generation.schema.json).
- MUST use the supplied current profile and prior context to prefer unexplored,
  strong-interest, or ambiguous dimensions.
- MUST NOT persist, assign application identities, or access another user's data.
- Provider failure and malformed output MUST be distinguishable.

The application validates the untrusted mapping strictly, assigns UUIDs and opaque
tokens, and stores all 10 questions and 40 options atomically.

## QuestionnaireQualityValidator

`validate(candidate, prior_context) -> QuestionnaireValidation`

- MUST enforce exact ordinals, normalized option uniqueness, bounded text, semantic
  dimension uniqueness, and configured substantial-repetition rules.
- MUST reject disguised yes/no, leading, vague, irrelevant, or double-barreled
  questions according to versioned deterministic heuristics and an optional
  replaceable semantic check.
- MUST return typed issues without mutating the candidate.

## PreferenceInterpreter

`propose(profile, questionnaire, answers) -> Mapping[str, object]`

- MUST receive exactly 10 persisted question/answer pairs and the profile revision
  used for interpretation.
- MUST return a document intended to conform to
  [preference-changes.schema.json](preference-changes.schema.json).
- MUST use absolute target weights and existing parameter IDs for non-create
  actions.
- MUST NOT persist or receive a repository.

Application validation rejects unknown IDs, duplicate targets, invalid weights,
unsupported actions, semantic duplicates, and every questionnaire action targeting
an explicit, inference, or system parameter before constructing an update batch.
Create actions receive questionnaire origin from application code. Equivalent
protected parameters reject creation; only a distinct semantic key may create a
separate questionnaire-origin parameter.

## PreferenceEquivalenceClassifier

`classify(proposal, candidates) -> Mapping[str, object]`

- MAY be used only after deterministic semantic-key and trigram candidate checks.
- MUST return a strict versioned `equivalent` or `distinct` decision with candidate
  identifier, confidence, and bounded reason.
- MUST NOT merge, create, refine, or persist a parameter.

The application treats an equivalent result as a rejected create action requiring
reuse/refinement. Invalid or uncertain classification never silently merges
parameters.

## PreferenceRepository

The repository contract provides:

- resolve or create an application user from a verified adapter identity;
- load a profile snapshot at a revision;
- create or resume one active questionnaire;
- atomically store a validated 10-question/40-option document;
- load the first unanswered question;
- resolve an opaque callback token within a user's active questionnaire;
- record one immutable answer idempotently;
- transition questionnaire states with expected-state checks;
- load bounded relevant prior questionnaire context;
- retrieve duplicate candidates for a proposed parameter;
- atomically apply a validated update batch against an expected profile revision;
- claim and purge a bounded batch of expired terminal questionnaire details;
- claim and purge a bounded batch of expired full change-history rows only after
  verifying a matching immutable compact audit row exists for every detailed row;
- return the persisted tune state after conflicts or retries.

The implementation MUST use independent sessions per application operation and
MUST NOT keep a transaction open during model calls.

## PreferenceTuningService

`start_or_resume(user_identity, language) -> TuneState`

1. Resolve the verified application user.
2. Resume an active questionnaire if present.
3. Otherwise capture the current profile and bounded prior context.
4. Create a generating questionnaire claim.
5. Call the generator outside the transaction.
6. Validate and atomically store the complete questionnaire.
7. Return the first unanswered question or a controlled failure state.

`answer(user_identity, callback_token) -> TuneState`

1. Validate token shape and resolve it for the verified user.
2. Record the current question's answer idempotently.
3. Return the next unanswered question when fewer than 10 answers exist.
4. After answer 10, transition to processing and interpret outside a transaction.
5. Validate the complete proposed batch, including duplicate and explicit-authority
   rules.
6. Apply it atomically against the captured profile revision.
7. Return completed, retryable processing, stale-profile reprocessing, or failed
   state without partial preference changes.

## PreferenceRetentionService

`purge_expired(now) -> RetentionResult`

1. Derive questionnaire and full-history cutoffs from validated configuration.
2. Claim at most the configured batch size of eligible terminal records.
3. Remove expired details without touching active questionnaires, current
   parameters, questionnaire/update-batch identity, update-batch digest, or any
   compact per-change audit row.
4. Commit one bounded transaction and return examined, removed, and preserved
   counts by data class.

The service runs on a configurable application schedule outside Telegram handlers.
An overlapping or repeated tick is a safe no-op for already claimed or removed
records. A zero full-history retention value means history cleanup is disabled.
Missing compact evidence blocks deletion and produces a typed retention-integrity
failure rather than weakening auditability.

## Telegram adapter

The adapter specified in [telegram-tune.md](telegram-tune.md):

- maps `/tune` and callback updates to the two service operations;
- renders `TuneState` into messages and inline keyboards;
- promptly acknowledges callback queries;
- contains no generation prompts, validation, preference calculation, repository
  calls, or business state.

## Error taxonomy

- `QuestionnaireGenerationFailed`: provider unavailable or exhausted transient
  retry.
- `QuestionnaireInvalid`: structural, quality, uniqueness, or repetition failure.
- `AnswerRejected`: malformed token, foreign user, stale question, or invalid
  option.
- `InterpretationFailed`: provider unavailable or malformed response.
- `PreferenceProposalInvalid`: unknown target, weight, action, duplicate, or
  explicit-authority violation.
- `ProfileRevisionStale`: profile changed after interpretation; no changes applied.
- `PersistenceConflict`: unexpected conflict not resolved by idempotency rules.

Logs and user-visible errors use classifications and correlation identifiers, not
credentials, callback tokens, full questions/answers, or profile snapshots.
