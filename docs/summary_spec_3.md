# Specification 3 Implementation Summary

Feature `003-personalized-ranking` adds explicit preference statements and a
deterministic, explainable personalized-ranking pipeline to the Telegram news
bot. All 68 implementation tasks are complete.

## Delivered functionality

### Explicit preferences with `/specify`

- Added a thin Telegram `/specify <statement>` command.
- Interprets bounded free-form statements through a structured-output model.
- Validates every proposed change locally before persistence.
- Supports create, adjust, refine, deactivate, and reactivate actions.
- Reuses equivalent active or inactive parameters instead of creating semantic
  duplicates.
- Preserves immutable parameter creation origin while adding append-only explicit
  authority evidence.
- Applies each validated change batch atomically with profile revision
  compare-and-swap.
- Handles retries, stale profiles, repeated Telegram updates, concurrent requests,
  invalid output, and controlled user-visible failures.
- Keeps existing `/tune` questionnaire behavior and authority rules intact.

### Article-to-preference evaluation

- Added versioned semantic relevance evaluation for every active user preference.
- Relevance is an exact decimal in `[-1.0000, +1.0000]`.
- Requires complete, user-owned parameter coverage before accepting evidence.
- Rejects malformed, incomplete, unknown, duplicate, stale, or out-of-range
  model output.
- Uses bounded transient retries and preserves previous valid evidence when a
  reevaluation fails.
- Isolates evaluation state and failures by user, article, profile revision,
  analysis version, parameter-set hash, schema version, and model version.

### Deterministic scoring and explanations

Personal contributions use exact `Decimal` arithmetic:

```text
contribution_i  = weight_i * relevance_i
personal_signed = sum(contribution_i) / sum(abs(weight_i))
personal_factor = (personal_signed + 1) / 2
```

The final score combines:

- personal relevance;
- article importance;
- freshness;
- source quality;
- novelty.

The default coefficients are `0.45`, `0.20`, `0.15`, `0.10`, and `0.10`.
Configuration validation requires an exact total of `1.00000` and a personal
coefficient of at least `0.40000`.

Ranking snapshots retain factor values, signed parameter contributions,
configuration and input versions, eligibility outcomes, exclusion reasons, and
stable explanation order. Identical inputs produce identical scores,
explanations, exclusions, selections, and ordering.

Stable ties resolve by:

```text
final_score DESC
personal_signed DESC
importance DESC
published_at DESC NULLS LAST
article_id ASC
```

### Eligibility and diversity

- Excludes incomplete generic or personal evidence.
- Enforces publication validity, freshness horizon, source-quality threshold,
  duplicate decisions, and explicit vetoes.
- Applies deterministic event, topic, and source caps after scoring.
- Gives strongly aligned explicit preferences first access to diversity capacity
  without bypassing eligibility or quality rules.
- Restarts selection from the original ordered candidates for each configured
  cap-relaxation pass.
- Records cap vectors, relaxations, shortages, final positions, and all selection
  or displacement reasons.

## Persistence and migration

Migration `003_create_personalized_ranking.py` adds:

- explicit preference requests and authority evidence;
- source-aware preference batch, history, and compact-audit linkage;
- evaluation runs, attempts, and per-parameter relevance;
- immutable ranking-configuration snapshots;
- ranking runs, article records, factors, contributions, and selection outcomes;
- compact ranking audit evidence and append-only protections;
- constraints, indexes, idempotency keys, version checks, and legacy evidence
  backfill.

PostgreSQL remains the authoritative data store. External model calls occur
outside database write transactions, while accepted profile and ranking changes
are persisted atomically.

## Privacy, retention, and observability

- Structured logs contain safe identifiers, versions, stages, statuses, bounded
  counts, and error categories.
- Credentials, raw statements, article content, prompts, raw model responses,
  profile snapshots, and chain-of-thought are excluded from logs.
- Raw statement/model data and detailed ranking evidence use configurable
  retention periods.
- Cleanup runs in bounded, overlap-safe batches and excludes active work.
- Compact per-change and ranking audit evidence survives detail compaction.
- Retained delivery references continue to have reconstructable identity,
  version, factor, score, and selection evidence.

## Configuration and operations

Configuration was added for:

- explicit request length, history bounds, stale retries, and model response size;
- ranking model endpoint, credentials, name, timeout, retries, and response size;
- coefficient and policy versions;
- scoring coefficients and freshness behavior;
- eligibility thresholds and candidate limits;
- event, topic, and source diversity caps;
- explicit protection and veto thresholds;
- explanation contribution limits;
- retention periods, batch size, and cleanup cadence.

Invalid exact-decimal combinations fail closed rather than being silently
corrected. Ranking can reuse the preferences provider endpoint and key, but it
requires its own configured model name.

Operational documentation and examples were updated in `README.md`,
`.env.example`, `docker-compose.yml`, and the feature quickstart.

## Main implementation areas

- `src/anxious_news_bot/preferences/`: explicit interpretation, authority,
  validation, application, evidence, and persistence.
- `src/anxious_news_bot/ranking/`: evaluation, eligibility, scoring,
  explanations, diversity, retention, model adapter, and PostgreSQL repository.
- `src/anxious_news_bot/telegram/specify.py`: thin Telegram command adapter.
- `src/anxious_news_bot/infrastructure/structured_model.py`: reusable bounded
  structured-model transport.
- `src/anxious_news_bot/app.py`: service composition, command registration, and
  retention scheduling.
- `migrations/versions/003_create_personalized_ranking.py`: database evolution.

## Validation result

- 68 of 68 feature tasks completed.
- 380 automated tests passed.
- Ruff formatting and linting passed.
- Bandit passed.
- `pip-audit` found no known vulnerabilities.
- Alembic metadata and `003 -> 002 -> 003` migration checks passed.
- Docker Compose configuration, build, and startup checks passed.
