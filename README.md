# Anxious News Bot

Telegram application with a scheduled, PostgreSQL-backed RSS/Atom aggregation
pipeline plus explicit preference capture and deterministic personalized ranking.
It normalizes articles, consolidates duplicates, groups related events, accepts
validated `/tune`, `/specify`, and `/count` updates, delivers timezone-aware
personalized digests, and persists explainable ranking and at-most-once delivery
evidence with bounded retention.

## Requirements

- Python 3.11+
- PostgreSQL 16+ with permission to enable `pg_trgm`
- A Telegram bot token from [BotFather](https://t.me/BotFather)

## Documentation

- [Architecture and lifecycle](docs/architecture.md)
- [Local and production setup](docs/setup.md)
- [User workflows](docs/user-guide.md)
- [Contributor development guide](docs/development.md)
- [Specification 004 implementation summary](docs/summary_spec_4.md)

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
together. New questionnaires select from a controlled semantic-dimension catalog
and record a durable per-user exposure count for every generated dimension.
Unseen dimensions are exhausted first; afterward, least-used and least-recently
used dimensions rotate in, so renamed questions and retention cleanup cannot
bypass the history check.

Send `/news` to evaluate a bounded pool of recent articles against the current
user's active preferences and return the top 10 after deterministic scoring,
quality eligibility, and diversity selection. Articles without generic analysis
receive a conservative deterministic baseline before personal evaluation. The
selected headlines are translated in one structured LLM request into the language
chosen with `/language`; article URLs and source metadata remain unchanged.

Send `/count <value>` to set the maximum scheduled digest size. Values `5`
through `20` are accepted; missing, extra, non-decimal, or out-of-range arguments
leave the stored value unchanged and return localized guidance. New users always
receive a disabled-safe digest configuration. Schedule enablement, local time,
and timezone are intentionally operational settings in this release and are not
changed by `/count`.

The digest scanner claims due local occurrences in bounded PostgreSQL batches,
reuses the existing personal ranking/diversity pipeline, filters confirmed or
uncertain delivery history before evaluation, and sends immutable structured
items through Telegram. Retries keep the same execution and ranking request IDs.
Acknowledged message parts are skipped; an ambiguous provider outcome becomes
terminal `delivery_unknown` evidence and is never resent automatically.

Send `/language` to choose `Русский`, `English`, or `Español` for the current
user. The selection persists across restarts. Changing it closes any unfinished
questionnaire so the next `/tune` uses the model to generate every question and
option in the newly selected language.

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

## Shared infrastructure deployment

Production runs as the `anxious-news-bot` worker in the shared `web-folders`
Compose stack. It uses the stack's `recipes-db` PostgreSQL service and has no
HTTP endpoint, nginx route, DNS record, or TLS certificate. On every container
start, the shared service runs `alembic upgrade head`, applies
`/app/sources.json`, and then starts Telegram polling.

`.github/workflows/build-deploy.yml` builds and deploys the Python 3.13 image
only after the existing `CI` workflow succeeds on `main`. Configure
`VPS_HOST`, `VPS_USER`, and `VPS_SSH_KEY` as GitHub Actions secrets. Configure
the `ANXIOUS_NEWS_BOT_*` database, Telegram, and model-provider variables in the
VPS `web-folders/.env`; never store their production values in this repository.

Operational settings include:

| Variable | Default | Purpose |
|---|---:|---|
| `NEWS_SCHEDULER_INTERVAL_SECONDS` | `300` | Scheduler scan cadence |
| `TELEGRAM_CONNECT_TIMEOUT_SECONDS` | `30` | Telegram API connection timeout |
| `TELEGRAM_READ_TIMEOUT_SECONDS` | `30` | Telegram API response timeout |
| `TELEGRAM_WRITE_TIMEOUT_SECONDS` | `30` | Telegram API request timeout |
| `TELEGRAM_POOL_TIMEOUT_SECONDS` | `10` | Telegram HTTP connection-pool timeout |
| `NEWS_FETCH_TIMEOUT_SECONDS` | `20` | Per-request timeout |
| `NEWS_FETCH_RETRY_ATTEMPTS` | `3` | Bounded fetch attempts |
| `NEWS_MAX_CONCURRENCY` | `5` | Maximum simultaneous source fetches |
| `NEWS_COMMAND_CANDIDATE_LIMIT` | `30` | Recent articles considered by `/news` |
| `NEWS_COMMAND_EVALUATION_CONCURRENCY` | `5` | Parallel personal evaluations for `/news` |
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

### Diagnosing news shortages

The application emits structured count-only diagnostics without article text:

- `runtime_configuration` shows the effective VPS settings after environment
  resolution.
- `news_cycle_started`, `news_source_completed`, and `news_cycle_completed`
  show due sources and fetched, accepted, rejected, and newly created counts.
- `personal_news_candidates_prepared` and
  `personal_news_evaluations_completed` show candidate and evaluation counts.
- `ranking_eligibility_summary` groups exclusions by reason, including
  `explicit_veto`, missing analysis, source quality, freshness, and duplicates.
  It also includes bounded article/parameter IDs and numeric alignment for
  explicit vetoes, plus bounded article IDs and coverage counts for incomplete
  personal evaluations; preference text and article text are never logged.
- `personal_news_selection_completed` shows the final requested, ranked, and
  deliverable counts.

For one `/news` request, filter the VPS logs by its `telegram-news:<update-id>`
request ID and correlate it with the latest aggregation cycle:

```bash
docker compose logs anxious-news-bot \
  | grep -E 'runtime_configuration|news_(cycle|source)|personal_news|ranking_eligibility_summary|diversity_'
```

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

Scheduled digest settings include:

| Variable | Default | Purpose |
|---|---:|---|
| `DIGEST_SCAN_INTERVAL_SECONDS` | `60` | Due/retry scan cadence |
| `DIGEST_CLAIM_BATCH_SIZE` | `100` | Configurations claimed per indexed query |
| `DIGEST_MAX_CLAIMS_PER_TICK` | `1000` | Durable occurrence claims per scan |
| `DIGEST_CLAIM_TIME_BUDGET_SECONDS` | `30` | Claim-work budget per scan |
| `DIGEST_USER_CONCURRENCY` | `5` | Concurrent isolated user executions |
| `DIGEST_DEFAULT_COUNT` | `10` | Disabled-safe initial item limit |
| `DIGEST_DEFAULT_LOCAL_TIME` | `09:00` | Disabled-safe local wall-clock time |
| `DIGEST_DEFAULT_TIMEZONE` | `UTC` | Disabled-safe IANA timezone |
| `DIGEST_CANDIDATE_LIMIT` | `100` | Bounded pre-history candidate pool |
| `DIGEST_MAX_ATTEMPTS` | `3` | Total attempts for one occurrence |
| `DIGEST_RETRY_BASE_SECONDS` | `60` | Initial exponential retry delay |
| `DIGEST_RETRY_MAX_SECONDS` | `900` | Retry delay ceiling |
| `DIGEST_MATERIAL_UPDATE_POLICY_VERSION` | `1.0` | Immutable evidence policy key |
| `DIGEST_MATERIAL_UPDATE_NOVELTY_THRESHOLD` | `0.7000` | Accepted novelty threshold |
| `DIGEST_MATERIAL_UPDATE_MAX_CONTENT_SIMILARITY` | `0.60000` | Content-delta ceiling |
| `DIGEST_MATERIAL_UPDATE_MIN_TEXT_CHARS` | `200` | Minimum comparison text |
| `DIGEST_HISTORY_RETENTION_DAYS` | `30` | Confirmed delivery-history horizon |
| `DIGEST_CONTENT_MAX_INPUT_CHARS` | `2000` | Per-item composition grounding cap |
| `DIGEST_RENDERER_VERSION` | `1.0` | Deterministic rendering policy version |

## Database setup and migrations

Create the database, grant the application role permission to create extensions,
then apply all migrations:

```bash
createdb anxious_news
alembic upgrade head
alembic current
```

The initial migration enables `pg_trgm`. Revision `005_scheduler_digest` creates
configuration, execution, attempt, item, delivery-part, history, and immutable
material-update evidence tables. It backfills every existing user with disabled
delivery, count `10`, local time `09:00`, timezone `UTC`, and no next-due instant.
Apply migrations before starting the bot and use `alembic downgrade -1` only with
a reviewed backup and rollback plan.

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

The same application process registers one digest timing adapter and one bounded
retention job. It does not create one in-memory job per user. To enable an
acceptance user until schedule-management commands exist, follow
`specs/004-scheduler-digest/quickstart.md`; do not expose direct SQL as an end-user
interface. Treat `delivery_unknown` as reconciliation-required and never reset an
unknown part to pending without verified provider evidence.

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
.venv/bin/python -m pytest tests/unit/digest tests/integration/digest
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/alembic upgrade head
.venv/bin/alembic current
```

Integration tests create a temporary PostgreSQL database through
`TEST_POSTGRES_ADMIN_URL` (default:
`postgresql+psycopg://postgres:postgres@localhost:5432/postgres`). PostgreSQL tests
are reported as skipped when that admin connection is unavailable; fixture-based
quality, performance, feed, and enrichment tests require no live source or LLM.
