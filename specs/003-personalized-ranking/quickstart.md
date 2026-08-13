# Quickstart: Explicit Preferences and Personalized Ranking

## Prerequisites

- Python 3.11 or newer
- PostgreSQL 16 or newer with the existing project migrations
- Existing normalized articles, generic analyses, users, and preference profiles
- A Telegram bot token for manual `/specify` interaction
- A compatible structured-output model endpoint for manual interpretation and
  article relevance evaluation

Automated tests use deterministic ports and do not require live Telegram, news
sources, or model services.

## Configure

Install the existing project and set base application configuration:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'

export DATABASE_URL='postgresql+psycopg://localhost/anxious_news'
export TELEGRAM_BOT_TOKEN='replace-with-secret'
export PREFERENCES_MODEL_BASE_URL='https://provider.example/v1'
export PREFERENCES_MODEL_API_KEY='replace-with-secret'
export PREFERENCES_MODEL_NAME='configured-structured-output-model'
export RANKING_MODEL_NAME='configured-relevance-model'
export RANKING_MODEL_TIMEOUT_SECONDS='30'
```

Ranking settings use validated exact decimal strings. Planned defaults:

```bash
export RANKING_CONFIGURATION_VERSION='1.0'
export RANKING_PERSONAL_COEFFICIENT='0.45000'
export RANKING_IMPORTANCE_COEFFICIENT='0.20000'
export RANKING_FRESHNESS_COEFFICIENT='0.15000'
export RANKING_QUALITY_COEFFICIENT='0.10000'
export RANKING_NOVELTY_COEFFICIENT='0.10000'
export RANKING_FRESHNESS_HORIZON_SECONDS='259200'
export RANKING_FUTURE_TOLERANCE_SECONDS='300'
export RANKING_MINIMUM_SOURCE_QUALITY='0.35000'
export RANKING_MAXIMUM_CANDIDATES='500'
export RANKING_EVENT_CAP='2'
export RANKING_TOPIC_CAP='3'
export RANKING_SOURCE_CAP='3'
export RANKING_EXPLICIT_WEIGHT_THRESHOLD='0.75'
export RANKING_EXPLICIT_RELEVANCE_THRESHOLD='0.6000'
export RANKING_EXPLANATION_CONTRIBUTION_LIMIT='3'
export RANKING_EVALUATION_RETRY_ATTEMPTS='3'
export RANKING_RAW_RESPONSE_RETENTION_DAYS='30'
export RANKING_DETAIL_RETENTION_DAYS='90'
export RANKING_RETENTION_BATCH_SIZE='500'
```

The five coefficients must sum exactly to `1.00000`; the personal coefficient must
be at least `0.40000`. Invalid settings stop ranking startup rather than being
silently corrected. Do not commit credentials.

## Initialize storage

```bash
alembic upgrade head
alembic current
```

Migration `003` adds explicit request/evidence linkage, evaluation runs and
attempts, parameter relevance, configuration snapshots, ranking runs, factor and
contribution evidence, selection outcomes, and compact ranking audit.

## Run validation

```bash
pytest tests/unit/preferences tests/unit/ranking tests/unit/telegram
pytest tests/integration/ranking
pytest
ruff format --check src tests migrations
ruff check src tests migrations
bandit --quiet --recursive src
pip-audit . --strict --progress-spinner off
```

PostgreSQL integration tests use the existing temporary-database fixture. Contract
tests validate every model document locally before persistence.

## Acceptance walkthrough

1. Submit `/specify Новости города Кирова` for a user with only a broad Russia
   preference; confirm a specific Kirov parameter is created and the broad
   parameter is not the only changed concept.
2. Repeat a semantically equivalent request against active and inactive
   parameters; confirm reuse/refinement/reactivation without duplicate creation.
3. Target questionnaire, inference, and system-origin parameters with explicit
   statements; confirm immutable creation origin, new explicit evidence, explicit
   history source, and effective explicit authority.
4. Replay the same Telegram update and race two applications; confirm one profile
   revision increment and one applied batch.
5. Change the profile during interpretation; confirm stale output applies nothing
   and one fresh interpretation uses the new revision.
6. Submit malformed, unknown-target, unrelated-explicit-target, excess-precision,
   negative-zero, and out-of-range proposals; confirm the profile remains
   unchanged.
7. Evaluate matching, neutral, and contradicting articles against all active
   parameters; confirm canonical relevance in `[-1.0000,+1.0000]` and exact
   parameter coverage.
8. Inject transport and invalid-output failures; confirm bounded retries,
   incomplete status, preserved previous valid evaluation, and later
   reprocessing.
9. Verify personal score for positive, negative, zero, cancelling, no-active, and
   all-zero profiles against hand-calculated decimal fixtures.
10. Verify importance, freshness, quality, novelty, mapped personal factor,
    coefficients, and final score reconstruct exactly from stored evidence.
11. Rank the same immutable snapshot 100 times; confirm identical scores,
    explanations, exclusions, ties, and ordering.
12. Test missing analysis, invalid/future/obsolete publication times, low source
    quality, duplicate outcomes, and incomplete personal evidence; confirm
    deterministic eligibility reasons.
13. Select from repeated events, topics, and sources; confirm protected explicit
    matches receive first cap capacity, caps are respected, relaxation order is
    stable, and shortages are recorded.
14. Change a profile, generic analysis, event assignment, duplicate decision, or
    configuration before completion; confirm the run becomes stale rather than
    mixing versions.
15. Inspect explanations and verify factor values, final score, top signed
    contributions, weights, relevance, authority, and selection reason without
    prompts or chain-of-thought.
16. Run bounded retention with expired raw requests, attempts, and ranking detail;
    confirm active work and current profile/evaluation data survive and compact
    preference/ranking audit remains for retained references.
17. Review structured logs and confirm no credentials, raw explicit statements,
    article text, prompts, model responses, or profile snapshots appear.
18. Verify ranking paths perform no source fetch and trigger no digest delivery.

## Expected result

Users can state specific explicit preferences that safely override weaker evidence
without losing provenance. Validated semantic relevance produces exact,
deterministic, explainable personal scores. Quality and diversity rules select a
useful varied result while protecting strong explicit intent, and every retained
outcome can be replayed or audited from versioned evidence.
