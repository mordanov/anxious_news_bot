# Anxious News Bot

Telegram application with a scheduled, PostgreSQL-backed RSS/Atom aggregation
pipeline plus explicit preference capture and deterministic personalized ranking.
It normalizes articles, consolidates duplicates, groups related events, accepts
validated `/tune` and `/specify` preference updates, and persists explainable
ranking evidence with bounded retention.

## Requirements

- Python 3.11+
- PostgreSQL 16+ with permission to enable `pg_trgm`
- A Telegram bot token from [BotFather](https://t.me/BotFather)

## Install and configure

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
```

Set `TELEGRAM_BOT_TOKEN` and a dedicated PostgreSQL database:

```bash
export TELEGRAM_BOT_TOKEN='...'
export DATABASE_URL='postgresql+psycopg://user:password@localhost/anxious_news'
```

## Run with Docker Compose

Copy the example environment and set a real BotFather token:

```bash
cp .env.example .env
# Edit TELEGRAM_BOT_TOKEN in .env
docker compose up --build
```

Compose starts PostgreSQL, waits for it to become healthy, creates the application
database when it is missing, runs `alembic upgrade head`, transactionally applies
the bundled `sources.json`, and then starts the bot. The image build validates the
catalog before any container starts; invalid source configuration fails the build.
Database data persists in the `postgres-data` volume.
PostgreSQL is intentionally available only inside the Compose network to avoid
conflicting with a local server; use the `docker compose exec postgres psql ...`
command below when you need a database console.

Send `/tune` to create or resume a 10-question preference questionnaire. Each
question has four opaque callback options. The profile is updated atomically only
after all answers pass strict local validation. Configure an OpenAI-compatible
structured-output endpoint with `PREFERENCES_MODEL_BASE_URL`,
`PREFERENCES_MODEL_API_KEY`, and `PREFERENCES_MODEL_NAME`; all three are required
together.

Send `/specify` to add or refine one explicit preference in plain language. The
same provider family is used for strict change proposals and bounded duplicate
review. Raw statements never persist directly to logs, non-explicit origins stay
immutable, and accepted updates append explicit evidence instead of rewriting
history.

Personal ranking reuses the same HTTPS provider credentials by default. Override
them with `RANKING_MODEL_BASE_URL` and `RANKING_MODEL_API_KEY` when you need a
different endpoint or key; `RANKING_MODEL_NAME` is always required for ranking
evaluation. Ranking provider output is schema-validated before persistence and
never writes directly to the database.

Send `/start` to the bot in Telegram to test message handling. `docker exec` opens
an additional process inside the running container; it does not replace Telegram
as the bot's chat interface. Useful operational commands are:

```bash
docker compose logs -f bot
docker compose exec bot sh
docker compose exec bot alembic current
docker compose exec bot anxious-news-sources validate /app/sources.json
docker compose exec postgres psql -U anxious_news -d anxious_news
```

`sources.json` is copied into the image at `/app/sources.json` and applied on every
startup. Applying it repeatedly is safe: listed sources are added or updated and
omitted database sources remain unchanged. After changing the file, rebuild:

```bash
docker compose up --build
```

Stop containers while preserving the database with `docker compose down`. Remove
the test database volume as well with `docker compose down -v`.

Operational settings include:

| Variable | Default | Purpose |
|---|---:|---|
| `NEWS_SCHEDULER_INTERVAL_SECONDS` | `60` | Scheduler scan cadence |
| `NEWS_FETCH_TIMEOUT_SECONDS` | `20` | Per-request timeout |
| `NEWS_FETCH_RETRY_ATTEMPTS` | `3` | Bounded fetch attempts |
| `NEWS_MAX_CONCURRENCY` | `5` | Maximum simultaneous source fetches |
| `NEWS_RAW_PAYLOAD_RETENTION_DAYS` | `7` | Raw provenance retention policy |
| `NEWS_NEAR_DUPLICATE_TITLE_THRESHOLD` | `0.85` | Duplicate title threshold |
| `NEWS_NEAR_DUPLICATE_CONTENT_THRESHOLD` | `0.80` | Duplicate body threshold |
| `NEWS_NEAR_DUPLICATE_REVIEW_THRESHOLD` | `0.72` | Manual-review boundary |
| `NEWS_EVENT_WINDOW_HOURS` | `48` | Same-event candidate window |
| `PREFERENCES_MODEL_TIMEOUT_SECONDS` | `30` | Model request timeout |
| `PREFERENCES_MODEL_RETRY_ATTEMPTS` | `2` | Bounded model attempts |
| `PREFERENCES_HISTORY_QUESTION_LIMIT` | `50` | Prior answers supplied as context |
| `PREFERENCES_REPETITION_THRESHOLD` | `0.85` | Repeated-question rejection threshold |
| `PREFERENCES_QUESTIONNAIRE_RETENTION_DAYS` | `365` | Detailed questionnaire retention |
| `PREFERENCES_CHANGE_HISTORY_RETENTION_DAYS` | `0` | Full history retention; `0` keeps indefinitely |
| `PREFERENCES_RETENTION_SCAN_INTERVAL_SECONDS` | `86400` | Cleanup cadence |
| `PREFERENCES_RETENTION_BATCH_SIZE` | `500` | Maximum rows claimed per cleanup |

Event weights and thresholds are configurable with the `NEWS_EVENT_*` variables
defined in `src/anxious_news_bot/config.py`. Keep credentials out of committed
files and logs.

Ranking and explicit-preference settings include:

| Variable | Default | Purpose |
|---|---:|---|
| `PREFERENCES_EXPLICIT_REQUEST_MAX_LENGTH` | `1000` | `/specify` statement length cap |
| `PREFERENCES_EXPLICIT_HISTORY_LIMIT` | `20` | Prior explicit changes supplied for interpretation |
| `PREFERENCES_EXPLICIT_STALE_RETRY_LIMIT` | `1` | One fresh reinterpretation after a stale profile |
| `RANKING_CONFIGURATION_VERSION` | `1.0` | Versioned ranking math snapshot |
| `RANKING_TIE_POLICY_VERSION` | `1.0` | Versioned stable tie-order policy |
| `RANKING_RETENTION_POLICY_VERSION` | `1.0` | Versioned retention policy snapshot |
| `RANKING_MODEL_BASE_URL` | unset | Optional ranking-provider URL; falls back to preferences URL |
| `RANKING_MODEL_API_KEY` | unset | Optional ranking-provider key; falls back to preferences key |
| `RANKING_MODEL_NAME` | unset | Structured relevance model name |
| `RANKING_MODEL_TIMEOUT_SECONDS` | `30` | Ranking evaluation timeout |
| `RANKING_MODEL_RETRY_ATTEMPTS` | `3` | Ranking transport retry cap |
| `RANKING_MODEL_MAX_RESPONSE_BYTES` | `262144` | Maximum ranking response size |
| `RANKING_PERSONAL_COEFFICIENT` | `0.45000` | Personal-factor coefficient |
| `RANKING_IMPORTANCE_COEFFICIENT` | `0.20000` | Generic importance coefficient |
| `RANKING_FRESHNESS_COEFFICIENT` | `0.15000` | Freshness coefficient |
| `RANKING_QUALITY_COEFFICIENT` | `0.10000` | Source-quality coefficient |
| `RANKING_NOVELTY_COEFFICIENT` | `0.10000` | Novelty coefficient |
| `RANKING_FRESHNESS_HORIZON_SECONDS` | `259200` | Freshness decay horizon |
| `RANKING_FUTURE_TOLERANCE_SECONDS` | `300` | Allowed future publication skew |
| `RANKING_MINIMUM_SOURCE_QUALITY` | `0.35000` | Eligibility threshold for source quality |
| `RANKING_MAXIMUM_CANDIDATES` | `500` | Hard candidate pool cap |
| `RANKING_EVENT_CAP` | `2` | Event diversity limit |
| `RANKING_TOPIC_CAP` | `3` | Topic diversity limit |
| `RANKING_SOURCE_CAP` | `3` | Source diversity limit |
| `RANKING_EXPLICIT_WEIGHT_THRESHOLD` | `0.75` | Explicit-protection weight floor |
| `RANKING_EXPLICIT_RELEVANCE_THRESHOLD` | `0.6000` | Explicit protection/veto relevance threshold |
| `RANKING_EXPLANATION_CONTRIBUTION_LIMIT` | `3` | Top contributions shown in explanations |
| `RANKING_EVALUATION_RETRY_ATTEMPTS` | `3` | Bounded evaluator retry cap |
| `RANKING_RAW_RESPONSE_RETENTION_DAYS` | `30` | Raw statement/response retention window |
| `RANKING_DETAIL_RETENTION_DAYS` | `90` | Detailed evaluation/ranking evidence retention window |
| `RANKING_RETENTION_BATCH_SIZE` | `500` | Rows or detail groups processed per cleanup run |
| `RANKING_RETENTION_SCAN_INTERVAL_SECONDS` | `86400` | Personalized-ranking cleanup cadence |

## Database setup and migrations

Create the database, grant the application role permission to create extensions,
then apply all migrations:

```bash
createdb anxious_news
alembic upgrade head
alembic current
```

The initial migration enables `pg_trgm` and creates the source, cycle, article,
provenance, duplicate-decision, event-group, and analysis tables. Apply migrations
before starting the bot and use `alembic downgrade -1` only with a reviewed backup
and rollback plan.

## Source configuration

Source catalogs follow
`specs/001-news-aggregation/contracts/source-catalog.schema.json`. Validate first,
preview the atomic change plan, then apply:

```bash
anxious-news-sources validate sources.json
anxious-news-sources apply --dry-run sources.json
anxious-news-sources apply sources.json
```

Catalog imports add or update listed sources. Omitted sources remain unchanged;
set `"enabled": false` explicitly to stop polling a source. RSS and Atom adapters
are supported without region-specific coordinator logic.

## Run and operate cycles

```bash
anxious-news-bot
```

Application startup creates the database/client lifecycle and schedules aggregation
at `NEWS_SCHEDULER_INTERVAL_SECONDS`. Each tick polls only enabled due sources,
uses bounded concurrency, and acquires a PostgreSQL advisory lock so overlapping
cycles return `already_running`. One source failure is recorded without cancelling
sibling sources. Repeated canonical input is idempotent, and a cycle exposes only
articles newly created during that cycle.

Structured news diagnostics contain cycle/source/article identifiers, stage,
status, bounded counts, and sanitized error context. Credentials, secret URL
components, and raw article payloads are redacted.

Preference diagnostics contain only stage, status, identifiers, bounded counts,
and error categories. Question text, answers, callback tokens, credentials, and
profile snapshots are never logged. Expired verbose preference history is deleted
only when a matching immutable compact audit row exists for every change; compact
identity and state/reason hashes remain indefinitely.

## Personalized ranking and explicit preferences

`/specify` and ranking stay downstream from ingestion: they never fetch, poll,
normalize, group, or deliver news. The personalized pipeline only consumes
already-normalized articles plus complete generic analyses.

### Deterministic scoring

Ranking uses fixed Decimal arithmetic, versioned configuration, and one stable tie
order. For active non-zero weights:

```text
contribution_i = weight_i * relevance_i
personal_signed = sum(contribution_i) / sum(abs(weight_i))
personal_factor = (personal_signed + 1) / 2
final_score =
  cP * personal_factor +
  cI * importance +
  cF * freshness +
  cQ * source_quality +
  cN * novelty
```

Factors, contributions, personal values, and final scores are persisted at eight
decimal places. The five coefficients must sum exactly to `1.00000`, and the
personal coefficient must remain at least `0.40000`.

Stable ordering is versioned by `RANKING_TIE_POLICY_VERSION` and resolves ties as:

```text
final_score DESC
personal_signed DESC
importance DESC
published_at DESC NULLS LAST
article_id ASC
```

### Eligibility, diversity, and explanations

- Ranking excludes articles with missing or incomplete generic analysis,
  incomplete personal evidence, low source quality, invalid or future
  publication timestamps, stale duplicate outcomes, or strong explicit vetoes.
- Diversity is deterministic and greedy. Explicitly protected matches receive
  first access to event/topic/source cap capacity, then relaxation proceeds in a
  stable configured order without bypassing eligibility.
- Explanations include factor values, final score, eligibility and selection
  reasons, and the strongest configured signed parameter contributions. Prompt
  text and chain-of-thought never persist or render.

### Privacy and retention

- Raw `/specify` text and raw model responses default to 30 days.
- Detailed evaluation attempts, accepted relevance rows, ranking records, and
  contribution rows default to 90 days.
- Cleanup is bounded, excludes active work, preserves current reusable accepted
  evaluations, and refuses ranking-detail deletion if matching compact ranking
  audit rows are missing.
- Compact preference audit and ranking audit hashes survive verbose cleanup so
  retained references remain reconstructable.

## Enrichment opt-in

Enrichment is disabled unless an `ArticleEnricher` adapter is explicitly supplied
when constructing `DefaultNewsAggregator`. Provider output must pass the strict
Pydantic schemas before persistence. Partial or failed enrichment never rolls back
a valid article, and this module accepts no user preference or personalized ranking
data.

## Validation

Use the project virtual environment:

```bash
.venv/bin/python -m compileall -q src tests
.venv/bin/python -m pytest tests/unit/news
.venv/bin/python -m pytest tests/integration/news
.venv/bin/python -m pytest
```

Integration tests create a temporary PostgreSQL database through
`TEST_POSTGRES_ADMIN_URL` (default:
`postgresql+psycopg://postgres:postgres@localhost:5432/postgres`). PostgreSQL tests
are reported as skipped when that admin connection is unavailable; fixture-based
quality, performance, feed, and enrichment tests require no live source or LLM.
