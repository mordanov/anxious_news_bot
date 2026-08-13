# Implementation Plan: User Preference Tuning

**Branch**: `002-user-preference-tuning` | **Date**: 2026-08-13 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/002-user-preference-tuning/spec.md`

## Summary

Add a User Preferences module and thin Telegram `/tune` adapter to the existing
Python modular monolith. Each durable session presents exactly 10 four-option
questions, resumes after restart, and uses prior profile and questionnaire context
for later sessions. Provider-neutral model adapters return strict versioned
questionnaire and change-proposal documents; application services validate them,
prevent semantic duplicates, and atomically apply deterministic incremental
changes against a profile revision. Exact decimal weights, idempotent callbacks,
and before/after history preserve profile integrity and auditability.

## Technical Context

**Language/Version**: Python 3.11
**Primary Dependencies**: python-telegram-bot 21.6+, SQLAlchemy 2.x, Alembic 1.x,
Psycopg 3, HTTPX 0.27+, Pydantic 2.x, Tenacity 8+
**Storage**: PostgreSQL 16+ with existing `pg_trgm`; Alembic-managed schema
**Testing**: pytest, pytest-asyncio, fake questionnaire/interpreter ports, HTTPX
MockTransport, and integration tests against ephemeral PostgreSQL
**Target Platform**: Linux server, single application process initially
**Project Type**: Python modular-monolith Telegram application with internal
application services
**Performance Goals**: 95% of locally accepted answers display the next state
within 2 seconds; 95% of completed sessions display an outcome within 10 seconds
after external interpretation returns; indexed resume and profile lookups remain
bounded by one user
**Constraints**: Exactly 10 questions and four options; weights use exact
two-decimal values in `[-1.00, +1.00]`; model output cannot persist directly;
failed batches leave the profile unchanged; explicit preferences cannot be
silently weakened or generalized; callbacks and completed questionnaires are
idempotent; no live Telegram or model service in business-logic tests; no secrets
or unnecessary answer text in logs
**Scale/Scope**: Initial single-instance deployment, up to roughly 10,000 users,
one active questionnaire per user, 10 questions per session, and normally fewer
than 100 preference parameters per user; direct editing, inference from behavior,
ranking, and digest delivery remain out of scope

## Constitution Check

*GATE: Passed before Phase 0 research and re-checked after Phase 1 design.*

- **Personalization — PASS**: Every profile and questionnaire is user-scoped.
  Origin remains explicit, and deterministic application rejects
  questionnaire-derived attempts to weaken or generalize explicit intent.
- **Boundaries — PASS**: `preferences` owns domain and application behavior.
  Telegram only maps commands/callbacks to application services; aggregation,
  ranking, and digest modules are not dependencies.
- **LLM trust boundary — PASS**: Generator, interpreter, and optional equivalence
  classifier return untrusted mappings through provider-neutral ports. Strict
  schemas and semantic validators run before any atomic repository operation.
- **Determinism and explainability — PASS**: Exact decimals, profile revisions,
  absolute target weights, versioned schemas, semantic keys, update batches, and
  before/after history make accepted state transitions reproducible and auditable.
  This feature does not calculate final ranking.
- **Data and configuration — PASS**: PostgreSQL is authoritative and all new
  structures use Alembic. Model endpoint/name, timeouts, retry limits, context
  bounds, question limits, and duplicate thresholds are settings.
- **Reliability and tests — PASS**: Ports allow model, clock, token, and persistence
  test doubles. Tests cover strict contracts, questionnaire quality, decimals,
  duplicate parameters, explicit-authority rules, concurrent updates, callback
  replay, restart/resume, atomic rollback, and user isolation.
- **Simplicity — PASS**: The existing process, HTTP client, PostgreSQL, and
  `pg_trgm` are sufficient. No worker, broker, cache, vector database, or provider
  SDK is added.

## Project Structure

### Documentation (this feature)

```text
specs/002-user-preference-tuning/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── preference-interfaces.md
│   ├── questionnaire-generation.schema.json
│   ├── preference-changes.schema.json
│   └── telegram-tune.md
└── tasks.md
```

### Source Code (repository root)

```text
migrations/
└── versions/

src/anxious_news_bot/
├── app.py
├── config.py
├── preferences/
│   ├── domain.py
│   ├── ports.py
│   ├── schemas.py
│   ├── services/
│   │   ├── apply_changes.py
│   │   ├── duplicates.py
│   │   └── tune.py
│   └── infrastructure/
│       ├── llm.py
│       ├── models.py
│       └── persistence.py
└── telegram/
    └── tune.py

tests/
├── unit/preferences/
├── integration/preferences/
└── unit/telegram/
```

**Structure Decision**: Extend the existing single package with one
`preferences` domain/application module and one thin Telegram adapter. Domain
values and ports do not import Telegram, HTTP, ORM, or provider-specific types.
Application services coordinate validation and state transitions; infrastructure
contains HTTP and PostgreSQL mapping. This preserves the modular monolith without
introducing infrastructure beyond the existing application and database.

## Phase 0: Research Outcome

Research decisions and rejected alternatives are recorded in
[research.md](research.md). All Technical Context questions are resolved.

## Phase 1: Design Outcome

- Relational entities, constraints, relationships, concurrency rules, and state
  transitions are defined in [data-model.md](data-model.md).
- Application and persistence boundaries are defined in
  [contracts/preference-interfaces.md](contracts/preference-interfaces.md).
- Strict model documents are defined in
  [contracts/questionnaire-generation.schema.json](contracts/questionnaire-generation.schema.json)
  and [contracts/preference-changes.schema.json](contracts/preference-changes.schema.json).
- Telegram command and callback behavior is defined in
  [contracts/telegram-tune.md](contracts/telegram-tune.md).
- Setup and acceptance workflow is defined in [quickstart.md](quickstart.md).
- The post-design Constitution Check remains fully passed.

## Complexity Tracking

No constitution violations require justification.
