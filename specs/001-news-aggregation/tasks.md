# Tasks: News Aggregation and Article Analysis

**Input**: Design documents from `specs/001-news-aggregation/`  
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`,
`contracts/aggregation-interfaces.md`, `contracts/enrichment-result.schema.json`

**Tests**: Tests are required for affected constitution rules: deterministic
normalization and deduplication, source failure isolation, idempotency, strict
enrichment validation, and operation without live sources or LLMs.

**Organization**: Tasks are grouped by user story so each increment has an explicit
independent acceptance test.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel because it changes different files and has no
  dependency on another incomplete task in the same group.
- **[Story]**: Maps the task to a user story (`US1`–`US4`).
- Every task names the file or directory it changes.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Add the selected dependencies and create the package, migration, and
test layout used by every story.

- [ ] T001 Add SQLAlchemy, Alembic, Psycopg, HTTPX, feedparser, Pydantic, and Tenacity dependency constraints to `pyproject.toml`
- [ ] T002 Create news package initializers in `src/anxious_news_bot/news/__init__.py`, `src/anxious_news_bot/news/services/__init__.py`, and `src/anxious_news_bot/news/infrastructure/__init__.py`
- [ ] T003 Configure Alembic metadata and asynchronous database URL handling in `alembic.ini` and `migrations/env.py`
- [ ] T004 [P] Add reusable valid, malformed, duplicate, and empty RSS/Atom samples under `tests/fixtures/feeds/`
- [ ] T005 [P] Add ephemeral PostgreSQL lifecycle, migration, and transaction fixtures in `tests/integration/conftest.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Establish shared domain contracts, persistence mapping, configuration,
and error boundaries before implementing any user journey.

**CRITICAL**: No user story work begins until this phase is complete.

- [ ] T006 Extend environment settings with database URL, fetch timeout, retry, concurrency, URL policy, retention, and duplicate-threshold validation in `src/anxious_news_bot/config.py`
- [ ] T007 [P] Define source, cycle, source-run, article, provenance, decision, event-group, and analysis domain values and status enums in `src/anxious_news_bot/news/domain.py`
- [ ] T008 [P] Define typed fetcher, normalizer, deduplicator, enricher, repository, clock, and aggregator protocols from the interface contract in `src/anxious_news_bot/news/ports.py`
- [ ] T009 [P] Define the bounded error taxonomy and sanitized diagnostic values in `src/anxious_news_bot/news/errors.py`
- [ ] T010 Implement SQLAlchemy mappings, relationships, checks, unique constraints, and indexes from `data-model.md` in `src/anxious_news_bot/news/infrastructure/models.py`
- [ ] T011 Create the initial PostgreSQL migration including `pg_trgm`, all news tables, constraints, and indexes in `migrations/versions/001_create_news_aggregation.py`
- [ ] T012 Implement async engine/session lifecycle and one-session-per-unit-of-work behavior in `src/anxious_news_bot/news/infrastructure/database.py`
- [ ] T013 Add structured source/cycle/stage logging helpers that exclude secrets and unnecessary payload content in `src/anxious_news_bot/news/observability.py`

**Checkpoint**: Domain contracts import without infrastructure dependencies, the
migration upgrades a clean PostgreSQL database, and all story phases can begin.

---

## Phase 3: User Story 1 - Build a Reliable News Pool (Priority: P1) MVP

**Goal**: Fetch enabled RSS/Atom sources into a validated normalized pool while
isolating source and record failures and returning only newly created articles.

**Independent Test**: Configure two available fixture sources and one timed-out
source, run a cycle, and verify that valid articles from available sources are
stored and returned while malformed records and the failed source are recorded
without cancelling sibling work.

### Tests for User Story 1

> Write these tests first and confirm that they fail before implementation.

- [ ] T014 [P] [US1] Add table-driven canonical URL and normalized article validation tests in `tests/unit/news/test_canonicalize.py`
- [ ] T015 [P] [US1] Add RSS/Atom parsing, ETag, Last-Modified, 304, timeout, retry, and malformed-feed tests using HTTPX MockTransport in `tests/unit/news/test_feeds.py`
- [ ] T016 [P] [US1] Add source failure-isolation, disabled-source, malformed-record, and newly-available-result coordinator tests in `tests/unit/news/test_aggregate.py`
- [ ] T017 [P] [US1] Add PostgreSQL migration, source-run transition, canonical uniqueness, provenance idempotency, and retry tests in `tests/integration/news/test_ingestion_repository.py`

### Implementation for User Story 1

- [ ] T018 [P] [US1] Implement deterministic versioned HTTP(S) URL canonicalization and tracking-parameter policy in `src/anxious_news_bot/news/services/canonicalize.py`
- [ ] T019 [P] [US1] Implement RSS/Atom HTTP fetching, conditional requests, bounded retries, parsing, and typed source failures in `src/anxious_news_bot/news/infrastructure/feeds.py`
- [ ] T020 [US1] Implement required-field validation and deterministic conversion from raw records to normalized candidates in `src/anxious_news_bot/news/services/normalize.py`
- [ ] T021 [US1] Implement source, cycle, source-run, provenance, and atomic canonical-article repository operations in `src/anxious_news_bot/news/infrastructure/persistence.py`
- [ ] T022 [US1] Implement bounded concurrent source orchestration, isolated transactions, cycle finalization, and newly available article results in `src/anxious_news_bot/news/services/aggregate.py`
- [ ] T023 [US1] Wire database lifecycle and the NewsAggregator service into application startup and shutdown without adding business logic to handlers in `src/anxious_news_bot/app.py`

**Checkpoint**: User Story 1 passes independently and is the deployable MVP.

---

## Phase 4: User Story 2 - Consolidate Duplicate Coverage (Priority: P2)

**Goal**: Consolidate canonical and near-duplicate coverage, group reports of the
same event, retain all source URLs, and preserve reviewable decision evidence.

**Independent Test**: Submit exact canonical duplicates, labeled near-duplicate and
unrelated pairs, plus distinct-source same-event reports; verify one canonical
article per URL, threshold-based decisions, event membership, retained provenance,
and persisted evidence.

### Tests for User Story 2

> Write these tests first and confirm that they fail before implementation.

- [ ] T024 [P] [US2] Add deterministic candidate ordering, threshold boundary, review-band, and unrelated-pair tests in `tests/unit/news/test_deduplicate.py`
- [ ] T025 [P] [US2] Add event grouping, reassignment evidence, and source-URL retention tests in `tests/unit/news/test_event_grouping.py`
- [ ] T026 [P] [US2] Add PostgreSQL trigram candidate search, decision uniqueness, and indexed-query integration tests in `tests/integration/news/test_deduplication_repository.py`

### Implementation for User Story 2

- [ ] T027 [P] [US2] Implement normalized title/content comparison, deterministic pair ordering, and configured duplicate/review/distinct outcomes in `src/anxious_news_bot/news/services/deduplicate.py`
- [ ] T028 [P] [US2] Implement evidence-backed event proposal, assignment, and reassignment rules separate from textual duplication in `src/anxious_news_bot/news/services/event_grouping.py`
- [ ] T029 [US2] Add bounded `pg_trgm` candidate queries and deduplication/event decision persistence to `src/anxious_news_bot/news/infrastructure/persistence.py`
- [ ] T030 [US2] Integrate exact resolution, near-duplicate classification, and event grouping into the ingestion sequence in `src/anxious_news_bot/news/services/aggregate.py`

**Checkpoint**: User Story 2 passes against a labeled duplicate corpus without
requiring enrichment or personal ranking.

---

## Phase 5: User Story 3 - Enrich Articles for Later Ranking (Priority: P3)

**Goal**: Store validated general article analysis and separate importance metadata
while preserving articles through partial, invalid, or failed enrichment.

**Independent Test**: Feed complete, partial, invalid, and failed fake enrichment
responses into stored articles and verify that only validated sections are stored,
status is explicit, articles survive, and no user-specific data is accepted.

### Tests for User Story 3

> Write these tests first and confirm that they fail before implementation.

- [ ] T031 [P] [US3] Add strict bounds, unknown-field, invalid-score, and partial-section schema tests in `tests/unit/news/test_enrichment_schemas.py`
- [ ] T032 [P] [US3] Add complete, partial, invalid, failed, and no-user-data enrichment service tests with fake enrichers in `tests/unit/news/test_enrich.py`
- [ ] T033 [P] [US3] Add analysis version uniqueness and validated-section persistence integration tests in `tests/integration/news/test_analysis_repository.py`

### Implementation for User Story 3

- [ ] T034 [P] [US3] Implement strict Pydantic enrichment result and independently validated section models matching the JSON contract in `src/anxious_news_bot/news/schemas.py`
- [ ] T035 [US3] Implement deterministic enrichment validation, partial-result mapping, and failure degradation in `src/anxious_news_bot/news/services/enrich.py`
- [ ] T036 [US3] Add versioned ArticleAnalysis persistence that accepts only validated domain values to `src/anxious_news_bot/news/infrastructure/persistence.py`
- [ ] T037 [US3] Integrate optional enrichment after durable article creation without rolling back valid articles on analysis failure in `src/anxious_news_bot/news/services/aggregate.py`

**Checkpoint**: User Story 3 passes without a live LLM and importance remains
independent from personal interest.

---

## Phase 6: User Story 4 - Extend Source Coverage (Priority: P4)

**Goal**: Add, disable, or reconfigure supported sources and regions without
changing the common article model or aggregation coordinator.

**Independent Test**: Register a supported source for a new region, disable an
existing source, run a cycle, and verify that only enabled due sources are fetched
through the appropriate replaceable adapter.

### Tests for User Story 4

> Write these tests first and confirm that they fail before implementation.

- [ ] T038 [P] [US4] Add adapter selection, unsupported source type, new-region, disabled-source, and not-yet-due tests in `tests/unit/news/test_source_catalog.py`
- [ ] T039 [P] [US4] Add enabled/due source query and persisted polling metadata integration tests in `tests/integration/news/test_source_repository.py`

### Implementation for User Story 4

- [ ] T040 [US4] Implement source-type adapter registration and supported-source resolution in `src/anxious_news_bot/news/services/source_catalog.py`
- [ ] T041 [US4] Add enabled/due source selection and conditional-fetch metadata updates to `src/anxious_news_bot/news/infrastructure/persistence.py`
- [ ] T042 [US4] Route each configured source through the catalog without region-specific branches in `src/anxious_news_bot/news/services/aggregate.py`

**Checkpoint**: User Story 4 passes for a new region without modifying domain
article definitions or coordinator rules.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Validate the complete pipeline, operational documentation, security,
performance, and constitution boundaries.

- [ ] T043 [P] Add multilingual labeled duplicate fixtures and calculate precision/false-merge acceptance metrics in `tests/fixtures/duplicates/` and `tests/integration/news/test_duplicate_quality.py`
- [ ] T044 [P] Add structured-log redaction tests covering credentials, URLs with secrets, and raw payloads in `tests/unit/news/test_observability.py`
- [ ] T045 Add bounded-concurrency and 10-minute readiness acceptance coverage in `tests/integration/news/test_cycle_performance.py`
- [ ] T046 Document database setup, migrations, source configuration, enrichment opt-in, and cycle operation in `README.md`
- [ ] T047 Execute and record the complete acceptance walkthrough commands in `specs/001-news-aggregation/quickstart.md`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: Starts immediately. T004 and T005 can run in parallel after
  T001 establishes dependencies.
- **Foundational (Phase 2)**: Depends on Setup and blocks all stories. T007–T009 can
  run in parallel; T010 depends on T007; T011 depends on T010; T012 depends on T006
  and T010.
- **US1 (Phase 3)**: Depends on Foundational and creates the deployable normalized
  pool required by later stories.
- **US2 (Phase 4)**: Depends on US1's article/provenance pipeline.
- **US3 (Phase 5)**: Depends on US1 but does not depend on US2.
- **US4 (Phase 6)**: Depends on US1 but does not depend on US2 or US3.
- **Polish (Phase 7)**: Depends on all selected user stories.

### User Story Dependency Graph

```text
Setup -> Foundation -> US1 (MVP) -> US2
                            |-----> US3
                            `-----> US4
US2 + US3 + US4 -> Polish
```

### Within Each User Story

1. Write the story's tests and verify they fail for the expected missing behavior.
2. Implement new domain-independent services and adapters.
3. Extend persistence only after service contracts are established.
4. Integrate into `aggregate.py` last.
5. Run the story's independent test before starting a dependent story.

## Parallel Opportunities

- **Setup**: T004 feed fixtures and T005 PostgreSQL fixtures can proceed in parallel.
- **Foundation**: T007 domain values, T008 ports, and T009 errors are independent
  files and can proceed in parallel.
- **US1**: T014–T017 test files can be authored in parallel; T018 canonicalization
  and T019 feed fetching can then be implemented in parallel.
- **US2**: T024–T026 tests can be authored in parallel; T027 deduplication and T028
  event grouping can then be implemented in parallel.
- **US3**: T031–T033 tests can be authored in parallel before schema/service work.
- **US4**: T038 and T039 cover independent unit and persistence surfaces.
- **Cross-story**: After US1, US2, US3, and US4 may be assigned concurrently,
  accounting for the shared `persistence.py` and `aggregate.py` integration tasks.

## Parallel Execution Examples

### User Story 1

```text
T014 tests/unit/news/test_canonicalize.py
T015 tests/unit/news/test_feeds.py
T016 tests/unit/news/test_aggregate.py
T017 tests/integration/news/test_ingestion_repository.py

Then in parallel:
T018 src/anxious_news_bot/news/services/canonicalize.py
T019 src/anxious_news_bot/news/infrastructure/feeds.py
```

### User Story 2

```text
T024 tests/unit/news/test_deduplicate.py
T025 tests/unit/news/test_event_grouping.py
T026 tests/integration/news/test_deduplication_repository.py

Then in parallel:
T027 src/anxious_news_bot/news/services/deduplicate.py
T028 src/anxious_news_bot/news/services/event_grouping.py
```

### User Story 3

```text
T031 tests/unit/news/test_enrichment_schemas.py
T032 tests/unit/news/test_enrich.py
T033 tests/integration/news/test_analysis_repository.py
```

### User Story 4

```text
T038 tests/unit/news/test_source_catalog.py
T039 tests/integration/news/test_source_repository.py
```

## Implementation Strategy

### MVP First

1. Complete Setup and Foundation.
2. Complete US1 through T023.
3. Run the US1 unit and PostgreSQL integration tests.
4. Demonstrate an isolated failed source alongside successful normalized articles.
5. Deploy only this increment if a general article pool is immediately valuable.

### Incremental Delivery

1. **US1**: Reliable normalized pool and source isolation.
2. **US2**: Duplicate consolidation and event evidence.
3. **US3**: Optional validated enrichment.
4. **US4**: Operational source and region extension.
5. **Polish**: Quality metrics, redaction, performance, and documentation.

## Notes

- Every task uses an exact path and all story tasks carry their `[US#]` label.
- `[P]` means file-level parallelism only; shared database and aggregate integration
  tasks remain sequential.
- Unit tests use fixtures, mock transports, fixed clocks, and fake enrichers.
- PostgreSQL-specific constraints, migrations, advisory locks, and `pg_trgm` are
  tested against PostgreSQL, not SQLite.
- No task adds personal ranking, user preferences, a message broker, a vector
  database, or business logic to Telegram handlers.
