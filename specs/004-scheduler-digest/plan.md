# Implementation Plan: Scheduled News Digests

**Branch**: `004-scheduler-digest` | **Date**: 2026-08-13 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/004-scheduler-digest/spec.md`

## Summary

Add a `digest` application module that owns per-user schedule configuration,
timezone-aware due occurrence claims, execution attempts, delivery-history
eligibility, structured digest composition, and at-most-once delivery state. The
module reuses the existing news candidate pool, article analysis, deterministic
personal ranking, diversity selector, language preference, structured model
transport, PostgreSQL database, and application JobQueue. Telegram gains only a
localized `/count` command and a structured-digest delivery adapter. A migration
adds durable configuration, execution, item, delivery-part, and history records.
Unique occurrence and delivery-part constraints, transactionally claimed work,
stable execution IDs, and conservative handling of unknown Telegram outcomes
prevent retries from creating duplicate deliveries.

## Technical Context

**Language/Version**: Python 3.11  
**Primary Dependencies**: python-telegram-bot 21.6+, SQLAlchemy 2.x, Alembic 1.x,
Psycopg 3, HTTPX 0.27+, Pydantic 2.x, Tenacity 8+; Python `zoneinfo`; no new
runtime dependency  
**Storage**: PostgreSQL 16+; Alembic-managed schema; existing news, preference,
analysis, and ranking evidence reused  
**Testing**: pytest, pytest-asyncio, fixed UTC clocks, fake candidate/history/
ranking/composition/delivery ports, HTTPX MockTransport, and integration tests
against ephemeral PostgreSQL  
**Target Platform**: Linux server, one application process initially, with
database claims safe for overlapping scheduler ticks or future additional
processes  
**Project Type**: Python modular-monolith Telegram application with internal
application services and adapter boundaries  
**Performance Goals**: Claim 99% of due occurrences within five minutes; scan
10,000 configurations through indexed bounded batches; process at least five
users concurrently without cross-user cancellation; keep due scans below one
second for a normally indexed 10,000-user data set; cap each digest at 20 items
and each ranking candidate pool at 100 by default  
**Constraints**: User count is 5..20; default count is 10; persisted IANA
timezones and local daily schedule; one execution per user/local occurrence;
bounded attempts and user concurrency; no duplicate retry after an ambiguous
delivery outcome; no filler articles; history filtering precedes deterministic
ranking; model output is strict and cannot persist directly; no raw prompts,
credentials, or unrestricted user/article content in logs  
**Scale/Scope**: Initial deployment up to roughly 10,000 users, normally one
daily schedule per enabled user, up to 20 selected items, 100 candidate articles,
and configurable batches/concurrency. `/count`, daily due execution, retry,
history exclusion, structured digest composition, and Telegram delivery are in
scope. User-facing schedule/timezone/enable commands, distributed workers,
brokers, and on-demand `/news` history changes are out of scope.

## Constitution Check

*GATE: Passed before Phase 0 research and re-checked after Phase 1 design.*

- **Personalization - PASS**: Digest execution captures the current user and
  profile revision, delegates scoring to personal ranking, and treats history
  only as candidate eligibility. Explicit preferences keep their existing
  authority and are not modified by scheduling.
- **Boundaries - PASS**: New `digest` services own scheduling, occurrence state,
  composition, and history. `news` owns aggregation and generic analysis;
  `ranking` owns evaluation, scoring, and diversity; Telegram maps `/count` and
  sends already structured digests. The JobQueue class is only a timing adapter.
- **LLM trust boundary - PASS**: The digest composer returns an indexed,
  versioned title/summary document. Pydantic validation, exact index coverage,
  length constraints, source-data preservation, and deterministic application
  run before digest items persist. Existing ranking validation remains unchanged.
- **Determinism and explainability - PASS**: Stable occurrence keys, captured
  timezone/count/profile inputs, one persisted ranking request ID, ordered item
  snapshots, history reasons, content hashes, attempt rows, and provider message
  acknowledgements explain every execution and make retries resume persisted
  state rather than recompute it.
- **Data and configuration - PASS**: Migration `005` adds digest tables,
  constraints, indexes, and safe disabled defaults. Scan intervals, batches,
  concurrency, default schedule/timezone/count, candidate limit, retry policy,
  material-update threshold, content limits, and history retention are validated
  settings.
- **Reliability and tests - PASS**: Clock, repository, personal-news selection,
  composer, renderer/delivery, and trigger ports have fakes. Tests cover count
  boundaries, due/DST rules, claims, user isolation, shortages, history,
  composition validation, retry classification, per-part at-most-once behavior,
  concurrency, migration constraints, and performance.
- **Simplicity - PASS**: The existing process, PostgreSQL, shared HTTP client,
  structured model transport, and JobQueue are sufficient. No broker, worker
  service, cache, provider SDK, or new scheduling package is introduced.

## Project Structure

### Documentation (this feature)

```text
specs/004-scheduler-digest/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── digest-content.schema.json
│   ├── digest-interfaces.md
│   └── telegram-digest.md
└── tasks.md
```

### Source Code (repository root)

```text
migrations/
└── versions/
    └── 005_create_scheduler_digest.py

src/anxious_news_bot/
├── app.py
├── config.py
├── logging.py
├── digest/
│   ├── __init__.py
│   ├── domain.py
│   ├── errors.py
│   ├── observability.py
│   ├── ports.py
│   ├── schemas.py
│   ├── services/
│   │   ├── configuration.py
│   │   ├── content.py
│   │   ├── execute.py
│   │   ├── history.py
│   │   └── schedule.py
│   └── infrastructure/
│       ├── llm.py
│       ├── models.py
│       ├── persistence.py
│       └── scheduling.py
├── ranking/
│   ├── domain.py
│   ├── ports.py
│   ├── infrastructure/persistence.py
│   └── services/news.py
└── telegram/
    ├── count.py
    └── digest.py

tests/
├── fixtures/digest.py
├── unit/digest/
├── unit/telegram/
└── integration/digest/
```

**Structure Decision**: Add one `digest` module because the constitution names
digest scheduling as an explicit boundary and its lifecycle/history rules do not
belong to news aggregation or ranking. Extend `PersonalNewsService` with an
internal-user selection path, configurable candidate limit, and a generic
candidate-filter port while preserving `/news`. This lets digest history remove
ineligible candidate IDs before existing evaluation, scoring, and diversity.
Digest composition belongs to `digest`, not Telegram, and persists structured
localized items once. Telegram renders those items into bounded delivery parts
and reports acknowledgements through a delivery port. JobQueue calls only the
application-level due-cycle service.

## Phase 0: Research Outcome

Research decisions and rejected alternatives are recorded in
[research.md](research.md). All Technical Context questions are resolved.

## Phase 1: Design Outcome

- Entities, constraints, indexes, lifecycle transitions, concurrency claims,
  history semantics, and transaction boundaries are defined in
  [data-model.md](data-model.md).
- Application, persistence, ranking-filter, composition, trigger, Telegram
  command, and delivery contracts are defined in [contracts/](contracts/).
- The strict structured content schema is defined in
  [contracts/digest-content.schema.json](contracts/digest-content.schema.json).
- Setup, migration, configuration, and acceptance workflows are defined in
  [quickstart.md](quickstart.md).
- `CLAUDE.md` points to this plan. The repository does not contain an agent
  context update script, so the bounded marker update is performed directly.
- The post-design Constitution Check remains fully passed.

## Complexity Tracking

No constitution violations require justification.

