# Anxious News Bot

Telegram application with a scheduled, PostgreSQL-backed RSS/Atom aggregation
pipeline. It normalizes articles, consolidates duplicates, groups related events,
and can optionally persist strictly validated provider-independent enrichment.

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

Event weights and thresholds are configurable with the `NEWS_EVENT_*` variables
defined in `src/anxious_news_bot/config.py`. Keep credentials out of committed
files and logs.

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
