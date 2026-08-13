# Tasks: Scheduled News Digests

**Input**: Design documents from `specs/004-scheduler-digest/`  
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`,
`contracts/`, `quickstart.md`

**Tests**: Tests are required for affected constitution rules, scheduler
isolation/idempotency, deterministic history and timezone behavior, strict model
validation, persistence concurrency, Telegram adapter boundaries, and all story
acceptance scenarios. Write each listed test first and confirm it fails for the
intended missing behavior before implementation.

**Organization**: Tasks are grouped by user story so each increment can be tested
and demonstrated independently after the shared foundation.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel because it targets different files and does not
  depend on unfinished work in the same phase.
- **[Story]**: Maps work to User Story 1, 2, or 3.
- Every task includes exact repository-relative file paths.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the digest module and test layout without adding dependencies.

- [ ] T001 Create digest package skeletons in `src/anxious_news_bot/digest/__init__.py`, `src/anxious_news_bot/digest/services/__init__.py`, and `src/anxious_news_bot/digest/infrastructure/__init__.py`
- [ ] T002 [P] Create reusable fixed-clock, configuration, execution, article, composer, and delivery fakes in `tests/fixtures/digest.py`
- [ ] T003 [P] Create PostgreSQL digest integration fixtures and schema lifecycle helpers in `tests/integration/digest/__init__.py` and `tests/integration/digest/conftest.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Establish validated settings, domain contracts, durable schema, and
repository state transitions required by every story.

**CRITICAL**: No user story implementation starts until this phase is complete.

### Tests for the Foundation

- [ ] T004 [P] Add failing validation tests for all `DIGEST_*` settings, timezone/local-time parsing, count/candidate bounds, claim budgets, material-update policy/version/similarity/text bounds, retry ordering, and history-horizon compatibility in `tests/test_config.py`
- [ ] T005 [P] Add failing domain and strict schema tests for count bounds, execution/item invariants, state transitions, material-update evidence bases/outcomes/hashes/thresholds, exact content indexes, URL/text limits, and typed failures in `tests/unit/digest/test_domain.py` and `tests/unit/digest/test_schemas.py`
- [ ] T006 [P] Add failing integration tests for migration backfill defaults, material-update evidence constraints and pair/policy uniqueness, post-migration user provisioning, concurrent self-healing, enums, indexes, relationships, and terminal-state constraints in `tests/integration/digest/test_models.py` and `tests/integration/digest/test_user_provisioning.py`
- [ ] T007 [P] Add failing repository contract tests for occurrence claims, attempt compare-and-set, atomic item insertion, monotonic success/failure fields, and terminal-state rejection in `tests/integration/digest/test_execution_repository.py`

### Implementation for the Foundation

- [ ] T008 Implement validated digest settings and environment parsing without new dependencies in `src/anxious_news_bot/config.py`
- [ ] T009 [P] Implement immutable digest domain values, enums, material-update evidence snapshots, occurrence/item validation, and typed retry/delivery errors in `src/anxious_news_bot/digest/domain.py` and `src/anxious_news_bot/digest/errors.py`
- [ ] T010 Implement application protocols for clock, identity claim, configuration, execution, candidate filtering, content composition, rendering, and delivery in `src/anxious_news_bot/digest/ports.py`, then implement strict indexed content models in `src/anxious_news_bot/digest/schemas.py`
- [ ] T011 Implement digest ORM entities including immutable material-update evidence and migration `005_scheduler_digest` with disabled-safe user backfill and `004_question_dimension_context` down revision in `src/anxious_news_bot/digest/infrastructure/models.py` and `migrations/versions/005_create_scheduler_digest.py`
- [ ] T012 Extract the sole transactional application-user/profile/digest-configuration provisioner, refactor preference persistence to use it, and implement digest configuration/execution repositories, due/retry claims, state compare-and-set, atomic item/part persistence, and monotonic terminal summaries in `src/anxious_news_bot/infrastructure/users.py`, `src/anxious_news_bot/preferences/infrastructure/persistence.py`, and `src/anxious_news_bot/digest/infrastructure/persistence.py`
- [ ] T013 [P] Add redacted structured digest event builders and JSON formatter support for bounded `digest` context in `src/anxious_news_bot/digest/observability.py` and `src/anxious_news_bot/logging.py`

**Checkpoint**: Settings, contracts, migration, and persistence foundation pass
without Telegram, network access, or a live model.

---

## Phase 3: User Story 1 - Receive a Personalized Digest on Schedule (Priority: P1) - MVP

**Goal**: Claim timezone-aware due users, reuse analysis/personal ranking/diversity,
compose localized structured title/summary items, and deliver at most the captured
count while allowing shortages and isolating users.

**Independent Test**: Configure one enabled due user with a fixed timezone,
preferences, and suitable recent articles; run the due cycle and verify one
localized structured digest is delivered and recorded. Disabled/not-due users
receive nothing, and a count-10 execution with only three suitable articles sends
exactly three.

### Tests for User Story 1

- [ ] T014 [P] [US1] Add failing deterministic tests for next-occurrence calculation, IANA validation, DST earlier-fold choice, missing-time advancement, occurrence keys, and schedule revision snapshots in `tests/unit/digest/test_schedule.py`
- [ ] T015 [P] [US1] Add failing ranking regression tests for internal user selection, bounded candidate overrides, pre-evaluation candidate filtering, grounded summary fallback, selection metadata, and unchanged `/news` behavior in `tests/unit/ranking/test_news.py`
- [ ] T016 [P] [US1] Add failing composer tests for one 1..20 indexed request, Russian/English/Spanish output, exact coverage, grounding limits, metadata preservation, and no partial acceptance in `tests/unit/digest/test_content.py` and `tests/unit/digest/test_llm.py`
- [ ] T017 [P] [US1] Add failing pure Telegram rendering/delivery tests for localized headers, title-summary-source-time-URL blocks, stable hashes/ranges, 3900-character parts, item order, and empty-digest suppression in `tests/unit/telegram/test_digest.py`
- [ ] T018 [P] [US1] Add failing execution-service tests for captured count/profile/language, analysis enforcement, ranking delegation, no filler, zero-item completion, and per-user exception isolation in `tests/unit/digest/test_execute.py`
- [ ] T019 [P] [US1] Add failing end-to-end tests for enabled/due versus disabled/not-due users, overlapping claims, count-10/three-item shortage, localized item snapshots, completion summaries, a sub-second 100-row claim query over 10,000 configurations, and at least 990 durable claims from a 1,000-user due burst within five simulated minutes in `tests/integration/digest/test_scheduled_delivery.py` and `tests/integration/digest/test_performance.py`

### Implementation for User Story 1

- [ ] T020 [P] [US1] Implement daily timezone occurrence resolution, canonical occurrence keys, fold/gap policy, and multi-batch due draining until empty, per-tick claim maximum, or claim-time budget in `src/anxious_news_bot/digest/services/schedule.py`
- [ ] T021 [P] [US1] Extend delivery projections and personal-news selection with internal user IDs, selection metadata, candidate-limit override, generic candidate filtering before evaluation, and grounded summary fallback while preserving `/news` in `src/anxious_news_bot/ranking/domain.py`, `src/anxious_news_bot/ranking/ports.py`, `src/anxious_news_bot/ranking/services/news.py`, and `src/anxious_news_bot/ranking/infrastructure/persistence.py`
- [ ] T022 [P] [US1] Implement deterministic ranked-item grounding, exact composition validation, metadata merging, contiguous positions, and immutable content hashes in `src/anxious_news_bot/digest/services/content.py`
- [ ] T023 [US1] Implement the versioned structured digest title/summary adapter using the shared model transport and typed transient/permanent failures in `src/anxious_news_bot/digest/infrastructure/llm.py`
- [ ] T024 [P] [US1] Implement pure structured-digest rendering and basic acknowledged Telegram sending without ranking or translation logic in `src/anxious_news_bot/telegram/digest.py`
- [ ] T025 [US1] Implement the successful execution path from attempt claim through filtered personal selection, zero-item completion, content persistence, part preparation, acknowledged delivery, and success recording in `src/anxious_news_bot/digest/services/execute.py`
- [ ] T026 [US1] Implement the idempotent JobQueue timing adapter that invokes only due/retry application cycles in `src/anxious_news_bot/digest/infrastructure/scheduling.py`
- [ ] T027 [US1] Wire digest repository, clock, history-free MVP filter, composer, execution service, Telegram delivery, and scheduler lifecycle into `src/anxious_news_bot/app.py`

**Checkpoint**: User Story 1 delivers scheduled personalized digests independently;
history suppression and full retry hardening may still be added by User Story 3.

---

## Phase 4: User Story 2 - Choose Digest Size (Priority: P2)

**Goal**: Let any Telegram user persist a digest count from 5 through 20 using a
localized `/count` command, rejecting all invalid forms without mutation.

**Independent Test**: Send `/count 5` and `/count 20` and verify localized
confirmation plus persisted values; send missing, extra, non-integer, 4, and 21
inputs and verify guidance with the previous value unchanged.

### Tests for User Story 2

- [ ] T028 [P] [US2] Add failing configuration-service tests for 5/20 boundaries, invalid-value rejection before persistence, shared provisioner delegation, guaranteed disabled-safe configuration, and captured-count behavior in `tests/unit/digest/test_configuration.py`
- [ ] T029 [P] [US2] Add failing Telegram `/count` tests for exact argument parsing, Russian/English/Spanish confirmations and guidance, missing update data, and controlled persistence failures in `tests/unit/telegram/test_count.py`
- [ ] T030 [P] [US2] Add failing integration tests for atomic count update through the shared provisioner, first-command user creation, concurrent updates, user isolation, no-change on invalid input, and execution count snapshots that ignore later count changes in `tests/integration/digest/test_configuration.py`

### Implementation for User Story 2

- [ ] T031 [US2] Implement count validation and digest repository updates that invoke the shared application-user/profile/configuration provisioner without adding preference-domain coupling in `src/anxious_news_bot/digest/services/configuration.py` and `src/anxious_news_bot/digest/infrastructure/persistence.py`
- [ ] T032 [US2] Implement the thin localized `/count` Telegram adapter with no persistence or scheduling logic in `src/anxious_news_bot/telegram/count.py`
- [ ] T033 [US2] Register the `/count` service and command handler while preserving all existing handlers and application tests in `src/anxious_news_bot/app.py` and `tests/test_app.py`

**Checkpoint**: User Story 2 works independently against the foundational digest
configuration even when scheduled delivery is disabled.

---

## Phase 5: User Story 3 - Receive Reliable, Non-Repetitive Delivery (Priority: P3)

**Goal**: Suppress unchanged prior articles, allow auditable material updates,
retry only safe transient failures with the same execution, resume acknowledged
parts, never resend ambiguous parts, and preserve other users' progress.

**Independent Test**: Deliver an article, run a later digest with the same article
and unchanged event versions, and verify suppression while a newer high-novelty
development remains eligible. Retry a multi-part execution after one acknowledged
part and verify only pending parts send; simulate an ambiguous outcome and verify
no automatic resend.

### Tests for User Story 3

- [ ] T034 [P] [US3] Add failing tests for versioned material-update production and history filtering across novelty qualification, baseline content delta, minimum text, same-event/publication guards, duplicate/review vetoes, stable order, hashes, threshold snapshots, and cached pair/policy decisions in `tests/unit/digest/test_material_updates.py` and `tests/unit/digest/test_history.py`
- [ ] T035 [P] [US3] Add failing PostgreSQL tests for per-user history, atomic material-update evidence insertion/loading, pair/policy uniqueness, normalized-text and veto lookups, baseline content-delta eligibility, concurrent evaluation, acknowledgement uniqueness, and query bounds in `tests/integration/digest/test_delivery_history.py` and `tests/integration/digest/test_material_update_evidence.py`
- [ ] T036 [P] [US3] Add failing retry-policy tests for stable execution/ranking IDs, exponential bounded delay, attempt exhaustion, phase resume without recomposition, typed transient/permanent outcomes, and stale-attempt rejection in `tests/unit/digest/test_retry.py`
- [ ] T037 [P] [US3] Add failing delivery tests for part claim-before-send, acknowledged-part skipping, definitive retry of only pending parts, content-hash mismatch rejection, stale-sending ambiguity, provider message IDs, and terminal unknown state in `tests/integration/digest/test_delivery_idempotency.py`
- [ ] T038 [P] [US3] Add failing cycle-isolation tests proving one user's model, ranking, persistence, permanent delivery, or ambiguous delivery failure cannot cancel another due user in `tests/integration/digest/test_user_isolation.py`
- [ ] T039 [P] [US3] Add failing retention tests that preserve active/unknown evidence, enforce the freshness-horizon floor, and remove only expired terminal detail/history in `tests/unit/digest/test_retention.py` and `tests/integration/digest/test_retention.py`

### Implementation for User Story 3

- [ ] T040 [P] [US3] Implement the versioned deterministic material-update evidence producer using accepted novelty or canonical normalized-content similarity with duplicate/review vetoes, then consume its persisted outcome in history filtering in `src/anxious_news_bot/digest/services/material_updates.py` and `src/anxious_news_bot/digest/services/history.py`
- [ ] T041 [US3] Implement atomic confirmed/uncertain history writes, material-update input loading and pair/policy evidence insertion, bounded history queries, per-part claims/acknowledgements, content-hash checks, and stale-sending reconciliation in `src/anxious_news_bot/digest/infrastructure/persistence.py`
- [ ] T042 [US3] Add bounded retry scheduling, phase-aware resume, attempt exhaustion, permanent failure, terminal ambiguous delivery, and per-user isolation to `src/anxious_news_bot/digest/services/execute.py` and `src/anxious_news_bot/digest/services/schedule.py`
- [ ] T043 [P] [US3] Classify Telegram acknowledgements, definite transient failures, permanent failures, and post-transmission ambiguity without logging provider bodies or content in `src/anxious_news_bot/telegram/digest.py`
- [ ] T044 [US3] Integrate the real history filter and retry claims into personal selection and the timing adapter in `src/anxious_news_bot/app.py` and `src/anxious_news_bot/digest/infrastructure/scheduling.py`
- [ ] T045 [US3] Implement digest attempt/detail/history retention and schedule it without deleting active retry or reconciliation evidence in `src/anxious_news_bot/digest/services/retention.py`, `src/anxious_news_bot/digest/infrastructure/persistence.py`, and `src/anxious_news_bot/app.py`

**Checkpoint**: All stories pass independently and together, including
idempotency, history, retry, ambiguity, and failure-isolation scenarios.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Complete safe operations, documentation, regression, and measurable
acceptance validation across all stories.

- [ ] T046 [P] Add digest observability tests for redaction, safe reason codes, occurrence/user hashing, bounded fields, durations, and absence of prompts/article text/provider responses in `tests/unit/digest/test_observability.py` and `tests/unit/test_logging.py`
- [ ] T047 [P] Document `/count`, disabled-safe schedule provisioning, digest environment settings, migration, retry/unknown semantics, and operating commands in `README.md`, `.env.example`, and `docker-compose.yml`
- [ ] T048 Run the feature suite, full pytest suite, Ruff checks, migration upgrade/current verification, and quickstart acceptance scenarios; record any required corrections in `src/anxious_news_bot/`, `tests/`, and `specs/004-scheduler-digest/quickstart.md`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: Starts immediately.
- **Phase 2 (Foundation)**: Depends on Phase 1 and blocks every user story.
- **Phase 3 (US1)**: Depends on Phase 2; this is the MVP.
- **Phase 4 (US2)**: Depends on Phase 2 and is logically independent of US1.
- **Phase 5 (US3)**: Depends on Phase 2 and the successful scheduled-delivery
  path from US1 because it hardens that execution with history and retries.
- **Phase 6 (Polish)**: Depends on all selected story phases.

### User Story Dependency Graph

```text
Setup -> Foundation -> US1 -> US3 -> Polish
                    \-> US2 ------/
```

- **US1** has no story dependency after Foundation.
- **US2** has no story dependency after Foundation; if developed concurrently,
  serialize its final `app.py` integration task T033 with US1 task T027.
- **US3** depends on US1's successful execution and delivery path but remains
  independently testable with persisted US1 fixtures.

### Within Each User Story

- Write all listed tests and confirm the intended failures before implementation.
- Domain/schema/models precede repository services.
- Candidate filtering precedes personal evaluation and ranking.
- Structured composition precedes persistence and Telegram rendering.
- A delivery part is persisted and claimed before external send.
- Integration and app wiring follow core services.

### Parallel Opportunities

- T002 and T003 can run in parallel after T001.
- T004 through T007 can be authored in parallel.
- T009 and T013 can run in parallel after foundation tests because observability
  uses primitive bounded payloads; T010 follows T009, while T011 follows T009/T010
  and T012 follows T011.
- T014 through T019 can be authored in parallel.
- T020, T021, T022, and T024 target independent modules and can run in parallel;
  T023 follows T022, and T025 follows all five.
- T028 through T030 can be authored in parallel.
- T034 through T039 can be authored in parallel.
- T040 and T043 can run in parallel; T041 follows the history contract, T042
  follows persistence behavior, and T044/T045 integrate afterward.
- T046 and T047 can run in parallel before final validation.

---

## Parallel Example: User Story 1

```text
Task T020: Implement timezone occurrence and due-cycle rules in src/anxious_news_bot/digest/services/schedule.py
Task T021: Extend reusable personal-news selection in src/anxious_news_bot/ranking/services/news.py
Task T022: Implement structured content application validation in src/anxious_news_bot/digest/services/content.py
Task T024: Implement deterministic Telegram digest rendering in src/anxious_news_bot/telegram/digest.py
```

## Parallel Example: User Story 2

```text
Task T028: Write count service tests in tests/unit/digest/test_configuration.py
Task T029: Write Telegram count adapter tests in tests/unit/telegram/test_count.py
Task T030: Write count persistence tests in tests/integration/digest/test_configuration.py
```

## Parallel Example: User Story 3

```text
Task T034: Write deterministic history-filter tests in tests/unit/digest/test_history.py
Task T036: Write retry-policy tests in tests/unit/digest/test_retry.py
Task T037: Write persisted delivery idempotency tests in tests/integration/digest/test_delivery_idempotency.py
Task T038: Write cross-user isolation tests in tests/integration/digest/test_user_isolation.py
```

---

## Implementation Strategy

### MVP First (User Story 1)

1. Complete Setup and Foundation.
2. Implement US1 tests and successful scheduled-delivery path.
3. Validate due/not-due/disabled behavior, timezone occurrence identity,
   personalized ranking reuse, structured localization, shortages, and isolated
   users.
4. Demonstrate with one operationally enabled acceptance user.

### Incremental Delivery

1. **Foundation**: Durable digest state and strict ports exist.
2. **US1**: Scheduled personalized digest delivery is usable.
3. **US2**: Users control digest size through `/count`.
4. **US3**: History, bounded retries, part resume, ambiguity handling, and
   retention make delivery production-safe.
5. **Polish**: Operational documentation and full regression evidence complete.

### Parallel Team Strategy

1. Complete Setup/Foundation together.
2. Start US1 core and US2 command work in parallel.
3. Serialize only their `app.py` integration edits.
4. Start US3 after the US1 execution contract stabilizes while US2 finishes.
5. Run Phase 6 only after all selected stories merge.

## Notes

- No task adds a runtime dependency, worker, broker, cache, or second scheduler.
- `/news` remains on-demand and does not acquire scheduled delivery-history rules.
- Unknown provider outcome favors no duplicate over automatic redelivery.
- Model output supplies only localized title/summary and never authoritative IDs,
  source, time, URL, score, schedule, or state.
- Migration revision strings must fit the existing 32-character Alembic version
  column.
