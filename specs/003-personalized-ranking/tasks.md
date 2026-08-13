# Tasks: Explicit Preferences and Personalized Ranking

**Input**: Design documents from `specs/003-personalized-ranking/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/,
quickstart.md

**Tests**: Tests are required for affected constitution rules, strict model
boundaries, explicit authority, atomic profile changes, exact ranking mathematics,
determinism, explanations, diversity, retention, and PostgreSQL concurrency.

**Organization**: Tasks are grouped by user story so each story can be implemented
and tested as a coherent increment.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel because it changes different files and has no
  dependency on another incomplete task in the same phase
- **[Story]**: Maps the task to a user story from spec.md
- Every task includes an exact file path

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the ranking module layout and shared structured-model boundary
without adding a service or runtime dependency.

- [X] T001 Create ranking, service, and infrastructure package initializers in src/anxious_news_bot/ranking/__init__.py, src/anxious_news_bot/ranking/services/__init__.py, and src/anxious_news_bot/ranking/infrastructure/__init__.py
- [X] T002 Add validated explicit-request limits, ranking model, exact coefficient, freshness, eligibility, candidate, diversity, explanation, retry, and retention settings in src/anxious_news_bot/config.py
- [X] T003 Extract the reusable bounded structured-output HTTP transport from the preference adapter into src/anxious_news_bot/infrastructure/structured_model.py and update src/anxious_news_bot/preferences/infrastructure/llm.py to use it without behavior changes

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Define exact domain values, trust boundaries, persistence structures,
and test doubles used by every user story.

**CRITICAL**: No user story work begins until this phase is complete.

- [X] T004 Define evaluation, ranking, eligibility, personal-state, selection, configuration, factor, contribution, and retention domain values with fixed Decimal policy in src/anxious_news_bot/ranking/domain.py
- [X] T005 [P] Define evaluator, ranking repository, configuration provider, clock, scoring, diversity, explanation, and retention protocols in src/anxious_news_bot/ranking/ports.py
- [X] T006 [P] Define strict frozen article-evaluation, ranking-configuration, factor, contribution, snapshot, result, and explanation schemas in src/anxious_news_bot/ranking/schemas.py
- [X] T007 [P] Define explicit-request and source-aware discriminated change schemas while preserving questionnaire contract compatibility in src/anxious_news_bot/preferences/schemas.py
- [X] T008 [P] Define typed explicit-request, evaluation, configuration, stale-snapshot, ranking, and retention errors plus sanitized stage logging in src/anxious_news_bot/ranking/errors.py and src/anxious_news_bot/ranking/observability.py
- [X] T009 Implement ExplicitPreferenceRequest, PreferenceEvidence, evaluation run/attempt/relevance, configuration snapshot, ranking run/record/contribution, and compact ranking-audit mappings plus preference batch/history/audit source linkage in src/anxious_news_bot/preferences/infrastructure/models.py and src/anxious_news_bot/ranking/infrastructure/models.py
- [X] T010 Create migration 003 with constraints, indexes, exact numerics, append-only triggers, nullable source linkage, legacy evidence backfill, ranking audit protection, and downgrade ordering in migrations/versions/003_create_personalized_ranking.py
- [X] T011 [P] Add deterministic explicit interpreter, relevance evaluator, clock, configuration, article/profile snapshot, and repository fixtures in tests/fixtures/ranking.py
- [X] T012 Add PostgreSQL migration, relationship, check-constraint, source-link XOR, unique-idempotency, append-only trigger, and evidence-backfill tests in tests/integration/ranking/test_models.py
- [X] T013 [P] Add configuration parsing tests for exact coefficient sum, personal floor, ranges, limits, model settings, and invalid fail-closed startup in tests/test_config.py

**Checkpoint**: Shared exact domain, structured contracts, storage, configuration,
and test doubles are ready.

---

## Phase 3: User Story 1 - State an Explicit Preference (Priority: P1) MVP

**Goal**: A user can submit `/specify`, apply one specific explicit incremental
profile change safely, reuse equivalent parameters, and receive an idempotent
auditable result.

**Independent Test**: Submit a specific Kirov request to a profile containing
broad, equivalent, inactive, questionnaire, inference, system, and unrelated
explicit parameters; verify one revision-safe specific change, immutable creation
origin, explicit evidence/history, duplicate reuse, replay safety, and controlled
failure.

### Tests for User Story 1

- [X] T014 [P] [US1] Add strict explicit-change contract tests for request identity, every action, canonical weights, negative zero, precision, unknown fields, duplicate targets, and malformed types in tests/unit/preferences/test_explicit_schemas.py
- [X] T015 [P] [US1] Add action-by-source authority tests for specific creation, every target origin, equivalent reuse, narrower distinct creation, unrelated explicit protection, no-op rejection, and whole-batch atomicity in tests/unit/preferences/test_explicit_authority.py
- [X] T016 [P] [US1] Add explicit-service tests for claim, context, interpretation outside transactions, duplicate resolution, successful application, no-change, provider failure, validation failure, and one stale reinterpretation in tests/unit/preferences/test_specify.py
- [X] T017 [P] [US1] Add PostgreSQL request idempotency, same-key/different-text rejection, profile CAS, concurrent replay, atomic rollback, evidence authority, immutable origin, history, compact-audit, and failed-user versus concurrently successful-user isolation tests in tests/integration/ranking/test_explicit_preferences.py
- [X] T018 [P] [US1] Add MockTransport tests for bounded explicit interpretation requests, profile/history context, structured schema, model/version identity, retries, response limits, and credential redaction in tests/unit/preferences/test_explicit_llm.py
- [X] T019 [P] [US1] Add Telegram tests for `/specify` text extraction, update identity, language, processing/applied/no-change/invalid/stale/failed rendering, missing objects, length handling, and raw-text log exclusion in tests/unit/telegram/test_specify.py

### Implementation for User Story 1

- [X] T020 [US1] Generalize deterministic preference proposal hashing and application validation around source-specific authority policies without weakening questionnaire rules in src/anxious_news_bot/preferences/services/apply_changes.py
- [X] T021 [US1] Implement effective authority derivation, append-only explicit evidence, equivalent/inactive reuse, specificity validation, and unrelated explicit protection in src/anxious_news_bot/preferences/services/duplicates.py and src/anxious_news_bot/preferences/services/authority.py
- [X] T022 [US1] Implement explicit request claims, bounded context/history reads, source-aware atomic application, revision CAS, replay resolution, evidence/history/audit writes, and controlled failure state in src/anxious_news_bot/preferences/infrastructure/persistence.py
- [X] T023 [US1] Implement structured explicit-statement interpretation with specific-intent and reuse instructions through the shared model transport in src/anxious_news_bot/preferences/infrastructure/llm.py
- [X] T024 [US1] Implement `/specify` orchestration with input normalization, idempotency, duplicate classification, strict validation, one stale reinterpretation, and no transaction across model calls in src/anxious_news_bot/preferences/services/specify.py
- [X] T025 [US1] Implement the thin `/specify` command adapter and bounded SpecifyState rendering in src/anxious_news_bot/telegram/specify.py
- [X] T026 [US1] Wire the explicit interpreter, source-aware preference service, `/specify` command, and shared-client lifecycle into src/anxious_news_bot/app.py
- [X] T027 [US1] Emit sanitized received, interpretation, validation, duplicate, stale, application, replay, and failure events without raw statements or profile snapshots in src/anxious_news_bot/preferences/observability.py

**Checkpoint**: User Story 1 is a complete independently testable `/specify` MVP.

---

## Phase 4: User Story 2 - Evaluate Articles Against Preferences (Priority: P2)

**Goal**: Produce complete, validated, versioned article-to-parameter relevance
evidence without corrupting previous valid data when evaluation fails.

**Independent Test**: Evaluate matching, neutral, and contradicting articles for
two isolated users; verify exact complete parameter coverage, bounded canonical
scores, versioned idempotency, bounded retries, preserved prior valid evidence,
and later reprocessing.

### Tests for User Story 2

- [X] T028 [P] [US2] Add strict relevance contract tests for identities, exact active-parameter coverage, canonical four-decimal bounds, negative zero, duplicate/unknown/missing parameters, reason codes, and extra fields in tests/unit/ranking/test_evaluation_schemas.py
- [X] T029 [P] [US2] Add reviewed matching, neutral, contradiction, multilingual, broad/specific, positive/negative, and zero-weight evaluation fixtures in tests/fixtures/ranking_evaluation_cases.py and direction-metric tests in tests/unit/ranking/test_evaluation_quality.py
- [X] T030 [P] [US2] Add evaluation-service tests for claim/replay, no-active profiles, transient retries, terminal invalid output, stale inputs, preserved prior valid evidence, later reprocessing, and failed-user versus concurrently successful-user isolation in tests/unit/ranking/test_evaluate.py
- [X] T031 [P] [US2] Add PostgreSQL evaluation identity, append-only attempts, accepted-attempt uniqueness, parameter coverage, user ownership, concurrent claim, version isolation, and valid-evidence preservation tests in tests/integration/ranking/test_evaluations.py

### Implementation for User Story 2

- [X] T032 [P] [US2] Implement bounded structured article/profile request construction and untrusted relevance output through the shared model transport in src/anxious_news_bot/ranking/infrastructure/llm.py
- [X] T033 [US2] Implement canonical parameter-set hashing, exact relevance validation, complete coverage checks, retry classification, stale detection, and evaluation orchestration in src/anxious_news_bot/ranking/services/evaluate.py
- [X] T034 [US2] Implement evaluation context queries, atomic run claims, append-only attempts, accepted relevance persistence, replay, failure, and prior-valid-version preservation in src/anxious_news_bot/ranking/infrastructure/persistence.py
- [X] T035 [US2] Compose the ranking evaluator and repository without scheduling evaluation from aggregation or Telegram handlers in src/anxious_news_bot/app.py
- [X] T036 [US2] Emit sanitized evaluation claim, attempt, validation, acceptance, stale, reprocess, and failure events without article text, prompts, responses, or profile snapshots in src/anxious_news_bot/ranking/observability.py

**Checkpoint**: User Story 2 provides durable relevance evidence independently of
final ranking.

---

## Phase 5: User Story 3 - Receive Deterministic Explainable Ranking (Priority: P3)

**Goal**: Rank a fixed candidate snapshot with exact deterministic mathematics,
quality eligibility, stable ties, replay, and reconstructable explanations.

**Independent Test**: Rank fixed complete evidence repeatedly and verify
hand-calculated positive/negative/zero contributions, neutral profile states,
freshness and generic factors, identical ordering, stable ties, full explanation,
snapshot staleness, and idempotent persisted replay.

### Tests for User Story 3

- [X] T037 [P] [US3] Add exact scoring tests for positive, negative, zero, cancelling, boundary, no-active, all-zero, missing-relevance, weighted-mean normalization, one-point quantization, and float rejection in tests/unit/ranking/test_score.py
- [X] T038 [P] [US3] Add configuration and freshness tests for convex coefficients, personal floor, linear decay boundaries, future tolerance, obsolete horizon, immutable ranking time, and canonical configuration hash in tests/unit/ranking/test_configuration.py
- [X] T039 [P] [US3] Add eligibility tests for incomplete generic/personal evidence, source-quality floor, publication validity, obsolete content, disqualifying duplicates, explicit veto, and deterministic reason precedence in tests/unit/ranking/test_eligibility.py
- [X] T040 [P] [US3] Add ranking-explanation contract tests for factors, top absolute signed contributions, stable contribution ties, origin versus authority, selection state, bounded names, and no prompt/chain-of-thought fields in tests/unit/ranking/test_explanations.py
- [X] T041 [P] [US3] Add ranking-service tests for candidate bounds, immutable snapshots, canonical candidate hash, deterministic sort ties, replay, same-key/different-input rejection, and stale version outcomes in tests/unit/ranking/test_rank.py
- [X] T042 [P] [US3] Add PostgreSQL atomic run/record/contribution/audit persistence, configuration immutability, input-version recheck, concurrent replay, failed-user versus concurrently successful-user isolation, score reconstruction, append-only audit, and 500-candidate performance tests in tests/integration/ranking/test_ranking.py

### Implementation for User Story 3

- [X] T043 [P] [US3] Implement fixed-context Decimal contribution, weighted personal normalization, neutral profile states, generic factor combination, one-point quantization, and canonical stable ordering in src/anxious_news_bot/ranking/services/score.py
- [X] T044 [P] [US3] Implement versioned configuration snapshots, exact validation, canonical hashing, freshness calculation, and deterministic eligibility reason precedence in src/anxious_news_bot/ranking/services/configuration.py and src/anxious_news_bot/ranking/services/eligibility.py
- [X] T045 [P] [US3] Implement deterministic top-contribution ordering and strict explanation rendering from persisted evidence in src/anxious_news_bot/ranking/services/explain.py
- [X] T046 [US3] Implement candidate/configuration/evaluation snapshot reads, run idempotency claims, atomic record/contribution/audit writes, version recheck, replay, and stale/failure persistence in src/anxious_news_bot/ranking/infrastructure/persistence.py
- [X] T047 [US3] Implement ranking orchestration across snapshot loading, eligibility, scoring, canonical ordering, explanation evidence, and atomic persistence in src/anxious_news_bot/ranking/services/rank.py
- [X] T048 [US3] Compose the validated ranking configuration provider and PersonalRankingService for downstream use without adding digest delivery in src/anxious_news_bot/app.py

**Checkpoint**: User Story 3 produces deterministic explainable ranked records
from accepted evidence.

---

## Phase 6: User Story 4 - Preserve Quality and Diversity (Priority: P4)

**Goal**: Select a varied deterministic result under event/topic/source caps,
protect aligned strong explicit intent, apply symmetric explicit vetoes, and record
every rejection or relaxation.

**Independent Test**: Select from repeated events, topics, and sources containing
protected, vetoed, low-quality, and ordinary articles; verify stable cap
enforcement, protection priority, no quality bypass, configured relaxation order,
shortage behavior, and replayable reasons.

### Tests for User Story 4

- [X] T049 [P] [US4] Add constrained-greedy tests for event/topic/source caps, protected-first capacity, symmetric explicit veto, quality non-bypass, stable ordering, exact target, exhausted pool, and configured relaxation vectors in tests/unit/ranking/test_diversify.py
- [X] T050 [P] [US4] Add reviewed repeated-event/topic/source and strong-explicit fixtures with cap-satisfaction and explicit-protection metrics in tests/fixtures/ranking_diversity_cases.py and tests/unit/ranking/test_diversity_quality.py
- [X] T051 [P] [US4] Add PostgreSQL selection tests for cap-vector snapshots, per-record reasons, final-position contiguity, unsatisfied limits, deterministic replay, and compact selection hashes in tests/integration/ranking/test_diversity.py

### Implementation for User Story 4

- [X] T052 [US4] Implement protected/veto classification and deterministic constrained-greedy selection with restart-from-original relaxation passes in src/anxious_news_bot/ranking/services/diversify.py
- [X] T053 [US4] Integrate diversity after scoring while preserving canonical input order, eligibility, exact target semantics, and recorded shortage outcomes in src/anxious_news_bot/ranking/services/rank.py
- [X] T054 [US4] Persist cap vectors, diversity passes, unsatisfied limits, final contiguous positions, selection reasons, and selection hashes atomically in src/anxious_news_bot/ranking/infrastructure/persistence.py
- [X] T055 [US4] Emit sanitized diversity protection, veto, cap rejection, relaxation, shortage, selection, and completion events with bounded counts in src/anxious_news_bot/ranking/observability.py

**Checkpoint**: All four stories are independently testable and the complete
pipeline preserves quality, explicit authority, diversity, determinism, and
explainability.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Enforce measurable quality, privacy, retention, performance,
documentation, and full-system acceptance criteria.

- [X] T056 [P] Add reviewed explicit-specificity and semantic-equivalence fixtures with enforced SC-001 and SC-002 thresholds in tests/fixtures/explicit_preference_cases.py and tests/integration/ranking/test_explicit_quality_metrics.py
- [X] T057 [P] Add 100-run byte-stable score, explanation, exclusion, ordering, and tie determinism tests for SC-007 in tests/integration/ranking/test_determinism.py
- [X] T058 [P] Add score and explanation reconstruction plus compact input/factor/contribution/score/selection hash verification tests for SC-008 in tests/integration/ranking/test_explainability.py
- [X] T059 [P] Add representative 500-candidate pure-scoring and end-to-end already-evaluated ranking latency gates for the plan and SC-011 in tests/integration/ranking/test_performance.py
- [X] T060 [P] Add structured-log redaction tests for credentials, raw explicit text, article content, prompts, raw responses, and profile snapshots in tests/unit/ranking/test_observability.py
- [X] T061 [P] Add boundary tests proving specify/evaluation/ranking paths never invoke source fetching, aggregation, digest scheduling, or delivery in tests/unit/ranking/test_boundaries.py
- [X] T062 [P] Add retention unit tests for raw-text/response and detail cutoffs, disabled retention, bounded batches, active-run exclusion, result counts, idempotent scheduler registration, overlap suppression, failure isolation, and subsequent-run recovery in tests/unit/ranking/test_retention.py
- [X] T063 [P] Add PostgreSQL retention tests for active/terminal explicit requests, accepted/failed evaluations, current reusable evidence, ranking detail expiry, compact preference/ranking audit survival, missing-audit refusal, delivery-reference preservation, and repeated bounded cleanup in tests/integration/ranking/test_retention.py
- [X] T064 Implement deterministic bounded raw explicit text, raw response, evaluation detail, ranking detail, and compact-audit-aware cleanup in src/anxious_news_bot/ranking/services/retention.py and src/anxious_news_bot/ranking/infrastructure/persistence.py
- [X] T065 Register configurable overlap-safe ranking retention cleanup outside Telegram and aggregation handlers in src/anxious_news_bot/ranking/infrastructure/retention.py and src/anxious_news_bot/app.py
- [X] T066 Update model-provider, `/specify`, ranking mathematics, coefficients, eligibility, diversity, explanation, privacy, retention, and operation instructions in README.md, .env.example, and docker-compose.yml
- [X] T067 Execute every acceptance scenario from specs/003-personalized-ranking/quickstart.md and record verified commands and outcomes in specs/003-personalized-ranking/quickstart.md
- [X] T068 Run full pytest, Ruff format/lint, Bandit, pip-audit, Alembic upgrade/downgrade/upgrade, Docker Compose configuration/startup, and migration metadata gates from .github/workflows/ci.yml and docker-compose.yml

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 — Setup**: Starts immediately.
- **Phase 2 — Foundational**: Depends on Setup and blocks every user story.
- **Phase 3 — US1**: Depends on Foundation and delivers the `/specify` MVP.
- **Phase 4 — US2**: Depends on Foundation and may proceed in parallel with US1.
- **Phase 5 — US3**: Depends on US2 accepted evaluation contracts and persistence.
- **Phase 6 — US4**: Depends on US3 scored/eligible record contracts and integrates
  US1 explicit authority evidence.
- **Phase 7 — Polish**: Depends on every selected user story.

### User Story Dependency Graph

```text
Setup -> Foundation -> US1 (/specify MVP) ---------\
                    \-> US2 -> US3 -> US4 ----------> Polish
                                  \---- uses explicit authority from US1
```

### User Story Dependencies

- **US1 (P1)**: Starts after Foundation; independently usable and recommended MVP.
- **US2 (P2)**: Starts after Foundation; independently persists validated semantic
  evidence and does not require `/specify`.
- **US3 (P3)**: Requires US2 evaluation identities and accepted relevance evidence;
  it can be tested with seeded profiles independently of Telegram.
- **US4 (P4)**: Requires US3 eligible scored records. Explicit protection integrates
  US1 evidence but can be independently tested with seeded evidence.

### Within Each User Story

- Write the listed tests first and confirm they fail for the intended missing
  behavior.
- Implement pure schemas, validators, mathematics, and policies before
  persistence/orchestration.
- Complete persistence before Telegram or composition-root wiring.
- Never hold a database transaction during a model call.
- Verify the independent story checkpoint before moving to the next priority.

### Parallel Opportunities

- T005–T008 and T011 can proceed in parallel after T004 establishes shared terms.
- T014–T019, T028–T031, T037–T042, and T049–T051 are independent test files.
- T043–T045 affect separate pure ranking services and can proceed in parallel.
- T056–T063 are independent cross-cutting test files.
- US1 and US2 may be implemented by separate developers after Foundation.

---

## Parallel Example: User Story 1

```text
Task T014: Write strict explicit schema tests in tests/unit/preferences/test_explicit_schemas.py
Task T015: Write source-authority policy tests in tests/unit/preferences/test_explicit_authority.py
Task T017: Write PostgreSQL explicit request/application tests in tests/integration/ranking/test_explicit_preferences.py
Task T019: Write Telegram /specify adapter tests in tests/unit/telegram/test_specify.py
```

## Parallel Example: User Story 2

```text
Task T028: Write relevance contract tests in tests/unit/ranking/test_evaluation_schemas.py
Task T029: Write reviewed evaluation fixtures and metrics in tests/fixtures/ranking_evaluation_cases.py
Task T030: Write evaluation orchestration tests in tests/unit/ranking/test_evaluate.py
Task T031: Write PostgreSQL evaluation evidence tests in tests/integration/ranking/test_evaluations.py
```

## Parallel Example: User Story 3

```text
Task T037: Write exact scoring tests in tests/unit/ranking/test_score.py
Task T038: Write configuration/freshness tests in tests/unit/ranking/test_configuration.py
Task T040: Write explanation contract tests in tests/unit/ranking/test_explanations.py
Task T042: Write PostgreSQL ranking/replay/performance tests in tests/integration/ranking/test_ranking.py
```

## Parallel Example: User Story 4

```text
Task T049: Write constrained-greedy tests in tests/unit/ranking/test_diversify.py
Task T050: Write reviewed diversity fixtures and metrics in tests/fixtures/ranking_diversity_cases.py
Task T051: Write PostgreSQL selection evidence tests in tests/integration/ranking/test_diversity.py
```

---

## Implementation Strategy

### MVP First: User Story 1

1. Complete Setup and Foundation.
2. Complete US1 tests and `/specify` implementation.
3. Validate specific explicit intent, duplicate reuse, source authority, atomic
   profile application, replay, audit, Telegram rendering, and failure behavior.
4. Stop and demo `/specify` independently before ranking work is required.

### Incremental Delivery

1. **Foundation**: exact shared contracts, configuration, persistence, and test
   doubles.
2. **US1**: explicit preference MVP.
3. **US2**: durable semantic article evaluation.
4. **US3**: deterministic explainable ranking.
5. **US4**: quality-preserving diversity.
6. **Polish**: measurable metrics, privacy, retention, performance, docs, and
   complete gates.

### Parallel Team Strategy

After Foundation:

- Developer A implements US1 `/specify`.
- Developer B implements US2 evaluation.
- After US2 stabilizes, Developer B or C implements US3 scoring/ranking.
- US4 begins after US3 record contracts stabilize and integrates explicit evidence
  from US1.

## Notes

- `[P]` marks different files with no incomplete dependency conflict.
- `[USn]` maps directly to the prioritized stories in spec.md.
- All model output remains untrusted until strict local validation succeeds.
- Every adjustment, threshold, cap, retry, retention period, and version is
  configured rather than hard-coded.
- Ranking consumes the general news pool but never fetches sources or delivers
  digests.
