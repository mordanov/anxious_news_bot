# Implementation Plan: News Aggregation and Article Analysis

**Branch**: `001-news-aggregation` | **Date**: 2026-08-12 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/001-news-aggregation/spec.md`

## Summary

Add a News Aggregator and Article Analysis module to the existing Python modular
monolith. The pipeline fetches enabled RSS/Atom sources concurrently, normalizes
and validates records, persists canonical articles in PostgreSQL, detects exact and
near duplicates, optionally enriches articles through a strictly validated
boundary, and returns the articles created by the cycle. Each pipeline capability
is replaceable and source failures are isolated. PostgreSQL uniqueness and
idempotent writes make retries deterministic; no user preferences or personal
ranking enter this module.

## Technical Context

**Language/Version**: Python 3.11  
**Primary Dependencies**: python-telegram-bot 21.6+, SQLAlchemy 2.x, Alembic 1.x,
Psycopg 3, HTTPX 0.27+, feedparser 6.x, Pydantic 2.x, Tenacity 8+  
**Storage**: PostgreSQL 16+ with `pg_trgm`; Alembic-managed schema  
**Testing**: pytest, pytest-asyncio, HTTPX MockTransport, fake enrichers, and
integration tests against ephemeral PostgreSQL  
**Target Platform**: Linux server, single application process initially  
**Project Type**: Python modular-monolith Telegram application with internal
application services  
**Performance Goals**: At least 95% of successful cycles expose newly available
articles within 10 minutes of the final source response; exact canonical lookups
remain index-backed; bounded source concurrency prevents resource exhaustion  
**Constraints**: One source failure cannot cancel sibling sources; repeated input
must be idempotent; no direct LLM persistence; no live network or LLM in unit tests;
no user-specific data in aggregation; secrets and raw payloads excluded from logs  
**Scale/Scope**: Initial single-instance deployment, tens of configured sources,
up to roughly 10,000 ingested source records per day, World/Russia/Spain coverage,
RSS/Atom first with replaceable adapters for later source types

## Constitution Check

*GATE: Passed before Phase 0 research and re-checked after Phase 1 design.*

- **Personalization — PASS**: Aggregation produces only general article metadata.
  No user profile, preference weight, or personalized relevance is in the model or
  interfaces.
- **Boundaries — PASS**: `news` is a domain/application module. Telegram remains a
  thin startup/scheduling adapter, and Personal Ranking is not a dependency.
- **LLM trust boundary — PASS**: Optional enrichment returns strict versioned
  Pydantic output. Deterministic mapping persists only validated sections; invalid
  output is retained as a sanitized failure outcome, not article metadata.
- **Determinism and explainability — PASS**: URL policy, normalization versions,
  database uniqueness, deduplication thresholds, comparison evidence, and cycle
  outcomes make decisions repeatable and auditable.
- **Data and configuration — PASS**: PostgreSQL is authoritative, all schema
  changes use Alembic, and polling, timeouts, concurrency, URL policy, retry limits,
  and duplicate thresholds are configuration.
- **Reliability and tests — PASS**: Ports allow network, clock, enrichment, and
  persistence test doubles. Source transactions are isolated and PostgreSQL
  integration tests cover uniqueness, upserts, migrations, and `pg_trgm`.
- **Simplicity — PASS**: One process and one database are sufficient. There is no
  broker, worker service, cache, or vector store.

## Project Structure

### Documentation (this feature)

```text
specs/001-news-aggregation/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── aggregation-interfaces.md
│   └── enrichment-result.schema.json
└── tasks.md
```

### Source Code (repository root)

```text
alembic.ini
migrations/
├── env.py
└── versions/

src/anxious_news_bot/
├── app.py
├── config.py
├── logging.py
└── news/
    ├── domain.py
    ├── ports.py
    ├── schemas.py
    ├── services/
    │   ├── aggregate.py
    │   ├── canonicalize.py
    │   └── deduplicate.py
    └── infrastructure/
        ├── feeds.py
        ├── persistence.py
        └── models.py

tests/
├── unit/news/
├── integration/news/
└── fixtures/feeds/
```

**Structure Decision**: Extend the existing single Python package with one `news`
module. Domain values and ports remain independent of Telegram, HTTP, ORM, and LLM
providers. Application services orchestrate the pipeline; infrastructure adapters
contain feed parsing and PostgreSQL mapping. This is the smallest structure that
keeps the required stages independently replaceable and testable.

## Phase 0: Research Outcome

Research decisions and rejected alternatives are recorded in
[research.md](research.md). All Technical Context questions are resolved.

## Phase 1: Design Outcome

- The relational model, constraints, relationships, and state transitions are
  defined in [data-model.md](data-model.md).
- Replaceable application boundaries are defined in
  [contracts/aggregation-interfaces.md](contracts/aggregation-interfaces.md).
- Strict enrichment output is defined in
  [contracts/enrichment-result.schema.json](contracts/enrichment-result.schema.json).
- The implementation and acceptance workflow is defined in
  [quickstart.md](quickstart.md).
- Agent guidance points to this plan.

## Complexity Tracking

No constitution violations require justification.

