# Tasks: User Preference Tuning

**Input**: Design documents from `specs/002-user-preference-tuning/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Tests are required for affected constitution rules, deterministic
preference updates, strict model boundaries, questionnaire validation, failure
isolation, and PostgreSQL concurrency/idempotency.

**Organization**: Tasks are grouped by user story so each story can be implemented
and tested as a coherent increment.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel because it changes different files and has no
  dependency on another incomplete task in the same phase
- **[Story]**: Maps the task to a user story from spec.md
- Every task includes an exact file path

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the module layout and shared database boundary required by the
feature without introducing a separate service.

- [ ] T001 Create preference, service, infrastructure, and Telegram package initializers in src/anxious_news_bot/preferences/__init__.py, src/anxious_news_bot/preferences/services/__init__.py, src/anxious_news_bot/preferences/infrastructure/__init__.py, and src/anxious_news_bot/telegram/__init__.py
- [ ] T002 Extract the reusable async Database, declarative Base, and timestamp mixin from the news module into src/anxious_news_bot/infrastructure/database.py and update imports in src/anxious_news_bot/news/infrastructure/database.py and src/anxious_news_bot/news/infrastructure/models.py
- [ ] T003 Add validated model endpoint, timeout, retry, history-bound, question-quality, duplicate-threshold, questionnaire/history-retention, cleanup-cadence, and cleanup-batch settings in src/anxious_news_bot/config.py

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Define the durable domain, trust boundaries, and PostgreSQL structures
that all user stories use.

**CRITICAL**: No user story work begins until this phase is complete.

- [ ] T004 Define user, profile, parameter, questionnaire, question, option, answer, update-batch, full history, compact per-change audit, status, origin, and action domain values in src/anxious_news_bot/preferences/domain.py
- [ ] T005 [P] Define generator, quality-validator, interpreter, equivalence-classifier, clock, token-factory, repository, and tuning-service protocols in src/anxious_news_bot/preferences/ports.py
- [ ] T006 [P] Define strict frozen Pydantic questionnaire, option, change-union, equivalence, canonical decimal, and snapshot schemas in src/anxious_news_bot/preferences/schemas.py
- [ ] T007 [P] Define typed generation, validation, answer, interpretation, stale-profile, proposal, and persistence errors in src/anxious_news_bot/preferences/errors.py
- [ ] T008 Implement SQLAlchemy mappings, constraints, relationships, partial active-questionnaire uniqueness, callback-token lookup index, profile revisions, update-batch summaries, full history, and immutable compact per-change audit fields in src/anxious_news_bot/preferences/infrastructure/models.py
- [ ] T009 Create the Alembic migration for application users, profiles, parameters, questionnaires, questions, options, answers, update batches, full history, and immutable compact per-change audit rows in migrations/versions/002_create_user_preferences.py
- [ ] T010 Implement the async preference repository unit-of-work skeleton and domain/ORM mappings in src/anxious_news_bot/preferences/infrastructure/persistence.py
- [ ] T011 [P] Add sanitized preference-stage structured logging helpers that exclude question text, answers, tokens, credentials, and profile snapshots in src/anxious_news_bot/preferences/observability.py
- [ ] T012 [P] Add deterministic fake generator, interpreter, equivalence classifier, clock, and callback-token fixtures in tests/fixtures/preferences.py
- [ ] T013 Add PostgreSQL migration, constraint, relationship, partial-unique-index, and weight-range integration tests in tests/integration/preferences/test_models.py

**Checkpoint**: Shared domain, contracts, storage, and test doubles are ready.

---

## Phase 3: User Story 1 - Tune a Personal News Profile (Priority: P1) MVP

**Goal**: A new user can start or resume `/tune`, answer exactly 10 four-option
questions, and receive a deterministic preference update only after answer 10.

**Independent Test**: Start `/tune` for a user with no profile, restart after nine
answers, resume question 10, complete it, and verify exactly one validated profile
update while duplicate callbacks do not advance twice.

### Tests for User Story 1

- [ ] T014 [P] [US1] Add strict questionnaire contract tests for 10 questions, four unique ordered options, extra fields, ordinals, lengths, and malformed types in tests/unit/preferences/test_questionnaire_schemas.py
- [ ] T015 [P] [US1] Add question-quality tests for concrete single-dimension wording, disguised yes/no, leading, vague, irrelevant, double-barreled, and duplicate questions in tests/unit/preferences/test_questionnaire_quality.py
- [ ] T016 [P] [US1] Add tuning-service tests for create, active-session resume, answers 1–9 without profile mutation, answer 10 interpretation/application, provider failure, and deterministic state rendering in tests/unit/preferences/test_tune.py
- [ ] T017 [P] [US1] Add repository integration tests for one active questionnaire, atomic 10-question/40-option storage, current-option ownership, duplicate callback replay, raced options, and restart/resume in tests/integration/preferences/test_questionnaires.py
- [ ] T018 [P] [US1] Add Telegram adapter tests for `/tune`, four-button rendering, prompt callback acknowledgement, opaque callback shape, stale options, missing users/messages, and controlled failures in tests/unit/telegram/test_tune.py

### Implementation for User Story 1

- [ ] T019 [P] [US1] Implement deterministic questionnaire structural and question-quality validation in src/anxious_news_bot/preferences/services/questionnaire_quality.py
- [ ] T020 [P] [US1] Implement bounded opaque callback-token generation and hashing in src/anxious_news_bot/preferences/services/tokens.py
- [ ] T021 [US1] Implement user/profile resolution, active questionnaire claims, atomic question storage, token resolution, idempotent answers, and tune-state reads in src/anxious_news_bot/preferences/infrastructure/persistence.py
- [ ] T022 [US1] Implement the provider-neutral HTTPX structured-output generator and interpreter adapter with bounded retries and response sizes in src/anxious_news_bot/preferences/infrastructure/llm.py
- [ ] T023 [US1] Implement minimal validated create/adjust proposal application after exactly 10 answers, preserving exact weights and questionnaire origin in src/anxious_news_bot/preferences/services/apply_changes.py
- [ ] T024 [US1] Implement start/resume and answer orchestration without holding transactions during model calls in src/anxious_news_bot/preferences/services/tune.py
- [ ] T025 [US1] Implement thin `/tune` command, opaque callback handler, and TuneState rendering in src/anxious_news_bot/telegram/tune.py
- [ ] T026 [US1] Wire the preference repository, model adapters, tuning service, `/tune` command, callback handler, and shared-client shutdown into src/anxious_news_bot/app.py

**Checkpoint**: User Story 1 is a complete restart-safe MVP.

---

## Phase 4: User Story 2 - Improve Preferences Over Repeated Sessions (Priority: P2)

**Goal**: Later questionnaires use bounded prior context, explore useful dimensions,
avoid substantial repetition, and reuse/refine equivalent parameters.

**Independent Test**: Complete two sessions for one user and verify that session
two receives current-profile and prior-answer context, rejects substantial repeated
questions, and adjusts or refines an equivalent parameter instead of creating a
duplicate.

### Tests for User Story 2

- [ ] T027 [P] [US2] Add adaptive-context tests for relevant history bounds, unexplored dimensions, strong interests, ambiguous preferences, language, and user isolation in tests/unit/preferences/test_context.py
- [ ] T028 [P] [US2] Add repetition tests across consecutive questionnaires, including allowed ambiguity clarification and normalized paraphrase fixtures, in tests/unit/preferences/test_repetition.py
- [ ] T029 [P] [US2] Add semantic-key, exact, trigram-candidate, inactive-parameter reuse, and equivalence-classifier duplicate tests in tests/unit/preferences/test_duplicates.py
- [ ] T030 [P] [US2] Add PostgreSQL history-selection and per-user duplicate-candidate integration tests in tests/integration/preferences/test_context_and_duplicates.py

### Implementation for User Story 2

- [ ] T031 [P] [US2] Implement bounded adaptive context selection and dimension classification in src/anxious_news_bot/preferences/services/context.py
- [ ] T032 [P] [US2] Implement normalized substantial-repetition comparison and allowed-clarification evidence in src/anxious_news_bot/preferences/services/repetition.py
- [ ] T033 [US2] Implement semantic-key normalization, PostgreSQL trigram candidate handling, and strict read-only equivalence classification in src/anxious_news_bot/preferences/services/duplicates.py
- [ ] T034 [US2] Extend questionnaire context queries, inactive-parameter lookup, and duplicate-candidate retrieval in src/anxious_news_bot/preferences/infrastructure/persistence.py
- [ ] T035 [US2] Extend generation and interpretation request construction with bounded prior context and existing-parameter reuse instructions in src/anxious_news_bot/preferences/infrastructure/llm.py
- [ ] T036 [US2] Integrate adaptive context, repetition validation, and reuse/refinement outcomes into src/anxious_news_bot/preferences/services/tune.py

**Checkpoint**: User Story 2 improves profiles incrementally without substantial
question or parameter duplication.

---

## Phase 5: User Story 3 - Preserve a Valid and Auditable Profile (Priority: P3)

**Goal**: Every change batch is strictly validated, atomic, idempotent,
revision-safe, deterministic, and reconstructable from immutable history.

**Independent Test**: Submit valid and invalid batches, inject failures after each
write, race two applications, replay one questionnaire, and change the profile
revision during interpretation; verify only one complete valid batch applies and
every applied change has full audit evidence.

### Tests for User Story 3

- [ ] T037 [P] [US3] Add strict discriminated change-contract tests for actions, required fields, unknown IDs, duplicate targets, canonical decimal strings, boundaries, negative zero, exponent notation, precision, and range in tests/unit/preferences/test_change_schemas.py
- [ ] T038 [P] [US3] Add deterministic proposal-validation and application tests for create, adjust, refine, deactivate, reactivate, unchanged actions, and stable normalized hashes in tests/unit/preferences/test_apply_changes.py
- [ ] T039 [P] [US3] Add PostgreSQL atomic rollback tests with failure injection after profile, parameter, full-history, compact-audit, batch, and questionnaire writes in tests/integration/preferences/test_atomic_application.py
- [ ] T040 [P] [US3] Add concurrent revision-CAS, stale interpretation, repeated questionnaire, and identical-input determinism integration tests in tests/integration/preferences/test_application_concurrency.py
- [ ] T041 [P] [US3] Add full-history reconstruction plus compact per-change hash/identity and append-only constraint tests for every applied action in tests/integration/preferences/test_history.py

### Implementation for User Story 3

- [ ] T042 [US3] Complete normalized proposal validation, exact Decimal handling, supported-action semantics, duplicate-target rejection, and deterministic proposal hashing in src/anxious_news_bot/preferences/services/apply_changes.py
- [ ] T043 [US3] Implement one-transaction questionnaire claim, profile revision compare-and-swap, parameter mutation, immutable before/after history, matching compact per-change audit rows, batch completion, rollback, and replay resolution in src/anxious_news_bot/preferences/infrastructure/persistence.py
- [ ] T044 [US3] Implement stale-profile re-interpretation, typed invalid-batch outcomes, retry boundaries, and deterministic completion handling in src/anxious_news_bot/preferences/services/tune.py
- [ ] T045 [US3] Emit sanitized generation, answer, interpretation, validation, stale, apply, and failure events through src/anxious_news_bot/preferences/observability.py

**Checkpoint**: User Story 3 makes profile state trustworthy and auditable under
invalid output, failure, replay, and concurrency.

---

## Phase 6: User Story 4 - Retain Explicit User Authority (Priority: P4)

**Goal**: Origin semantics remain accurate and questionnaire changes cannot
silently weaken, generalize, relabel, or replace specific explicit preferences.

**Independent Test**: Apply questionnaire proposals to a profile containing all
origins and verify origins remain accurate, legitimate non-explicit changes work,
and any forbidden explicit-preference action rejects the whole batch.

### Tests for User Story 4

- [ ] T046 [P] [US4] Add action-by-origin policy unit tests proving questionnaire create origin, allowed questionnaire-target actions, rejected explicit/inference/system adjust (including strengthen), refine, deactivate, reactivate, equivalent create, and mixed-batch atomic rejection in tests/unit/preferences/test_explicit_authority.py
- [ ] T047 [P] [US4] Add PostgreSQL tests proving origin immutability, questionnaire history source separation, protected-parameter non-mutation, equivalent-create rejection, distinct narrower creation, and forbidden mixed-batch atomicity in tests/integration/preferences/test_explicit_authority.py

### Implementation for User Story 4

- [ ] T048 [US4] Implement the action-by-origin matrix, immutable origins, questionnaire-only target mutation, protected equivalent-create rejection, distinct narrower creation, and whole-batch failure in src/anxious_news_bot/preferences/services/apply_changes.py
- [ ] T049 [US4] Include immutable origin and specificity evidence in interpretation context and instruct proposals to target only questionnaire-origin parameters without accepting generated origin values in src/anxious_news_bot/preferences/infrastructure/llm.py

**Checkpoint**: All four user stories are independently testable and preserve user
authority.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Enforce measurable quality, performance, privacy, documentation, and
full-system acceptance criteria.

- [ ] T050 [P] Add reviewed questionnaire-quality and consecutive-session repetition fixtures with enforced SC-002 and SC-005 thresholds in tests/fixtures/preference_quality_cases.py and tests/integration/preferences/test_questionnaire_quality_metrics.py
- [ ] T051 [P] Add reviewed semantic-equivalence fixtures with enforced SC-010 recall and exact-match guarantees in tests/fixtures/preference_duplicate_cases.py and tests/integration/preferences/test_duplicate_quality_metrics.py
- [ ] T052 [P] Add answer-state and post-interpretation latency checks for the plan and SC-004 targets in tests/integration/preferences/test_tune_performance.py
- [ ] T053 [P] Add structured-log redaction tests for credentials, callback tokens, question/answer text, and profile snapshots in tests/unit/preferences/test_observability.py
- [ ] T054 [P] Add retention configuration, cutoff, disabled-history-cleanup, batch-bound, active-session exclusion, and result-count unit tests in tests/unit/preferences/test_retention.py
- [ ] T055 [P] Add PostgreSQL retention tests for applied/failed/active questionnaires, current parameters, bounded and repeated cleanup, full-history expiry, immutable compact per-change survival, hash/identity auditability, missing-audit deletion refusal, and preserved batch digests in tests/integration/preferences/test_retention.py
- [ ] T056 Implement deterministic retention cutoffs, disabled-history semantics, and bounded cleanup orchestration in src/anxious_news_bot/preferences/services/retention.py
- [ ] T057 Implement claimed-batch questionnaire-detail and full-history cleanup that requires and preserves matching immutable compact per-change audit rows and update-batch digests in src/anxious_news_bot/preferences/infrastructure/persistence.py
- [ ] T058 Register configurable recurring retention cleanup outside Telegram handlers with overlap-safe outcomes in src/anxious_news_bot/preferences/infrastructure/retention.py and src/anxious_news_bot/app.py
- [ ] T059 Update configuration, retention, migration, `/tune`, model-provider, privacy, and test instructions in README.md and docker-compose.yml
- [ ] T060 Execute every acceptance scenario from specs/002-user-preference-tuning/quickstart.md and record the verified commands and outcomes in specs/002-user-preference-tuning/quickstart.md
- [ ] T061 Run the full pytest, Ruff format/lint, Bandit, pip-audit, Alembic upgrade, and Docker Compose startup gates defined in .github/workflows/ci.yml and docker-compose.yml

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 — Setup**: Starts immediately.
- **Phase 2 — Foundational**: Depends on Phase 1 and blocks every user story.
- **Phase 3 — US1**: Depends on Phase 2 and delivers the MVP.
- **Phase 4 — US2**: Depends on Phase 2; integrates with US1's session workflow for
  end-to-end delivery but its context, repetition, and duplicate services are
  independently testable.
- **Phase 5 — US3**: Depends on Phase 2; hardens the update path introduced by US1
  and can be developed in parallel with US2 after the MVP interfaces stabilize.
- **Phase 6 — US4**: Depends on US3 proposal validation/application and may begin
  after T042–T043.
- **Phase 7 — Polish**: Depends on all selected user stories.

### User Story Dependency Graph

```text
Setup -> Foundational -> US1 (MVP)
                    |-> US2
                    |-> US3 -> US4
US1 + US2 + US3 + US4 -> Polish
```

### Within Each User Story

- Write and run story tests first; confirm they fail for the intended missing
  behavior.
- Implement pure validators and services before persistence/orchestration.
- Complete persistence behavior before Telegram or application wiring.
- Do not hold a database transaction across a model call.
- Finish the story's independent test before moving to the next priority.

### Parallel Opportunities

- T005–T007 and T011–T012 can proceed in parallel after T004 defines shared terms.
- T014–T018, T027–T030, T037–T041, and T046–T047 are independent test files and
  can be authored in parallel within their story.
- T019 and T020, T031 and T032, and T050–T055 affect separate files.
- US2 and US3 can proceed in parallel after the US1 interfaces stabilize.

---

## Parallel Example: User Story 1

```text
Task T014: Write strict questionnaire schema tests in tests/unit/preferences/test_questionnaire_schemas.py
Task T015: Write question-quality tests in tests/unit/preferences/test_questionnaire_quality.py
Task T017: Write questionnaire persistence tests in tests/integration/preferences/test_questionnaires.py
Task T018: Write Telegram adapter tests in tests/unit/telegram/test_tune.py
```

## Parallel Example: User Story 2

```text
Task T027: Write adaptive-context tests in tests/unit/preferences/test_context.py
Task T028: Write repetition tests in tests/unit/preferences/test_repetition.py
Task T029: Write duplicate detection tests in tests/unit/preferences/test_duplicates.py
Task T030: Write context/duplicate persistence tests in tests/integration/preferences/test_context_and_duplicates.py
```

## Parallel Example: User Story 3

```text
Task T037: Write strict change-contract tests in tests/unit/preferences/test_change_schemas.py
Task T039: Write rollback tests in tests/integration/preferences/test_atomic_application.py
Task T040: Write concurrency tests in tests/integration/preferences/test_application_concurrency.py
Task T041: Write audit-history tests in tests/integration/preferences/test_history.py
```

## Parallel Example: User Story 4

```text
Task T046: Write authority policy tests in tests/unit/preferences/test_explicit_authority.py
Task T047: Write authority persistence tests in tests/integration/preferences/test_explicit_authority.py
```

---

## Implementation Strategy

### MVP First

1. Complete Setup and Foundational phases.
2. Complete User Story 1.
3. Run the US1 unit, integration, and Telegram adapter tests.
4. Demonstrate restart-safe `/tune` completion with fake model ports.
5. Continue to adaptive quality and hardening only after the MVP is stable.

### Incremental Delivery

1. **US1**: Durable 10-question tuning and basic validated update.
2. **US2**: Adaptive sessions, repetition control, and parameter reuse.
3. **US3**: Full action contract, auditability, rollback, concurrency, and replay.
4. **US4**: Explicit preference authority.
5. **Polish**: Enforced quality/performance metrics and operational documentation.

### Parallel Team Strategy

1. Complete the shared foundation together.
2. Stabilize US1 ports and repository contracts.
3. Develop US2 adaptation and US3 hardening in parallel.
4. Add US4 authority rules after the US3 validator/application boundary.
5. Run cross-cutting gates after merging selected stories.

## Notes

- `[P]` tasks target separate files or independent tests.
- Story labels provide requirement and acceptance-flow traceability.
- PostgreSQL-only constraints, trigram behavior, transactions, and concurrency use
  PostgreSQL integration tests rather than SQLite substitutes.
- Model and Telegram boundaries use fakes or mock transports in automated tests.
- Commit after each task or coherent task group.
