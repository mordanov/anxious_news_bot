# Implementation Plan: Explicit Preferences and Personalized Ranking

**Branch**: `003-personalized-ranking` | **Date**: 2026-08-13 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/003-personalized-ranking/spec.md`

## Summary

Extend the existing modular monolith with a thin Telegram `/specify` adapter, an
explicit-preference application path in the preferences module, and a new personal
ranking module. Structured model adapters propose explicit preference changes and
bounded article-to-parameter relevance documents; strict local schemas and
semantic policy validate both. PostgreSQL transactions apply profile changes with
revision compare-and-swap and retain append-only explicit evidence without
rewriting immutable parameter origin. Ranking uses exact decimal arithmetic:
personal relevance is the weighted mean `sum(weight * relevance) /
sum(abs(weight))`, mapped to `[0,1]` and combined with separately normalized
importance, freshness, source quality, and novelty. A deterministic constrained
greedy selector applies quality gates and diversity caps while protecting strong
explicit intent. Versioned runs, contribution rows, factor snapshots, selection
reasons, and compact hashes make every retained result replayable and explainable.

## Technical Context

**Language/Version**: Python 3.11  
**Primary Dependencies**: python-telegram-bot 21.6+, SQLAlchemy 2.x, Alembic 1.x,
Psycopg 3, HTTPX 0.27+, Pydantic 2.x, Tenacity 8+; no new runtime dependency  
**Storage**: PostgreSQL 16+ with existing `pg_trgm`; Alembic-managed schema  
**Testing**: pytest, pytest-asyncio, fixed decimal fixtures, fake interpretation
and relevance ports, HTTPX MockTransport, and integration tests against ephemeral
PostgreSQL  
**Target Platform**: Linux server, single application process initially  
**Project Type**: Python modular-monolith Telegram application with internal
application services  
**Performance Goals**: 95% of ranking runs over at most 500 already-evaluated
candidate articles and normally fewer than 100 active parameters complete within
5 seconds; pure scoring and diversity selection complete within 500 ms in
representative local benchmarks; indexed request, evaluation, and run replay
lookups remain bounded by user and version keys  
**Constraints**: Exact decimal weights in `[-1.00,+1.00]`; relevance in
`[-1.0000,+1.0000]`; final factors in `[0,1]`; coefficient sum exactly `1.00000`;
personal coefficient at least `0.40000`; model output cannot persist directly;
profile updates are atomic and revision-safe; parameter origin remains immutable;
explicit authority is append-only evidence; incomplete evaluations do not replace
valid evidence; rankings use immutable input snapshots and stable ordering;
ranking never fetches news or delivers digests; no secrets, raw prompts, or
unnecessary user/article text in logs  
**Scale/Scope**: Initial deployment up to roughly 10,000 users, normally fewer
than 100 preference parameters per user, candidate pools capped at 500 articles,
and requested selections normally 10–50 articles; `/specify`, personalized
evaluation, ranking, explanation, and diversity are in scope, while aggregation
and digest scheduling/delivery remain out of scope

## Constitution Check

*GATE: Passed before Phase 0 research and re-checked after Phase 1 design.*

- **Personalization — PASS**: `/specify` creates explicit evidence with the
  highest authority, preserves specific intent, and reuses equivalent parameters.
  Personal contributions remain separate from generic importance and strong
  explicit intent receives configurable selection protection.
- **Boundaries — PASS**: `preferences` owns explicit profile changes; `ranking`
  owns user-specific article evaluation, scoring, explanations, and diversity;
  `news` continues to own the general article pool and generic analysis. Telegram
  only maps `/specify` into the application service. Ranking neither fetches news
  nor delivers digests.
- **LLM trust boundary — PASS**: Provider-neutral adapters return untrusted
  mappings. Strict versioned schemas, ownership checks, semantic duplicate checks,
  exact decimal validation, and source-policy validation run before any
  transaction. Model output never writes directly.
- **Determinism and explainability — PASS**: Fixed decimal context, one
  quantization point, immutable `ranking_at`, normalized factors, configuration
  snapshots, canonical input hashes, explicit tie ordering, stable cap relaxation,
  factor rows, parameter contributions, and selection reasons make ranking
  reproducible and auditable.
- **Data and configuration — PASS**: PostgreSQL remains authoritative and migration
  `003` extends preference audit linkage and adds evaluation/ranking evidence.
  Coefficients, freshness, thresholds, retries, candidate limits, diversity caps,
  explicit protection, explanation limits, and retention are validated settings.
- **Reliability and tests — PASS**: Interpretation, classifier, relevance
  evaluator, clock, repository, and ranking ports support test doubles. Planned
  tests cover strict contracts, authority, duplicates, CAS/replay, scoring,
  normalization, missing evidence, explanations, diversity, retention, failure
  isolation, performance, and PostgreSQL concurrency.
- **Simplicity — PASS**: The existing process, shared HTTP client, JobQueue,
  PostgreSQL, and `pg_trgm` suffice. No worker, broker, cache, vector database,
  provider SDK, or additional service is introduced.

## Project Structure

### Documentation (this feature)

```text
specs/003-personalized-ranking/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── telegram-specify.md
│   ├── explicit-preference-changes.schema.json
│   ├── article-preference-evaluation.schema.json
│   ├── ranking-explanation.schema.json
│   └── ranking-interfaces.md
└── tasks.md
```

### Source Code (repository root)

```text
migrations/
└── versions/
    └── 003_create_personalized_ranking.py

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
│   │   └── specify.py
│   └── infrastructure/
│       ├── llm.py
│       ├── models.py
│       └── persistence.py
├── ranking/
│   ├── __init__.py
│   ├── domain.py
│   ├── errors.py
│   ├── ports.py
│   ├── schemas.py
│   ├── services/
│   │   ├── evaluate.py
│   │   ├── score.py
│   │   ├── diversify.py
│   │   ├── rank.py
│   │   └── retention.py
│   └── infrastructure/
│       ├── llm.py
│       ├── models.py
│       └── persistence.py
└── telegram/
    └── specify.py

tests/
├── fixtures/
│   ├── explicit_preference_cases.py
│   ├── ranking_evaluation_cases.py
│   └── ranking_diversity_cases.py
├── unit/preferences/
├── unit/ranking/
├── unit/telegram/
└── integration/ranking/
```

**Structure Decision**: Extend the existing preferences module for `/specify`
because it already owns profile revisions, semantic duplicate handling, source
origins, atomic application, and audit history. Add one `ranking` module for all
user-specific article relevance, scoring, explanation, and diversity behavior.
The ranking repository may read stable identifiers and versioned generic evidence
owned by `news`, but `news` does not import ranking or perform personalized
decisions. Telegram remains a one-command adapter. Shared model transport may be
reused through provider-neutral ports without sharing prompts or domain schemas.

## Phase 0: Research Outcome

Research decisions and rejected alternatives are recorded in
[research.md](research.md). All Technical Context questions are resolved.

## Phase 1: Design Outcome

- Relational entities, constraints, version keys, state transitions, transaction
  boundaries, append-only authority evidence, and retention rules are defined in
  [data-model.md](data-model.md).
- Telegram behavior and strict structured model documents are defined in
  [contracts/](contracts/).
- Exact scoring, normalization, quality gates, deterministic ordering, diversity
  relaxation, idempotency, and repository/application boundaries are defined in
  [contracts/ranking-interfaces.md](contracts/ranking-interfaces.md).
- Setup and acceptance workflow is defined in [quickstart.md](quickstart.md).
- The post-design Constitution Check remains fully passed.

## Complexity Tracking

No constitution violations require justification.
