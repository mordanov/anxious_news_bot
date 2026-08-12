# Quickstart: News Aggregation and Article Analysis

This workflow describes the expected setup and acceptance checks after the feature
is implemented.

## Prerequisites

- Python 3.11
- PostgreSQL 16 or newer with permission to enable `pg_trgm`
- A dedicated development database
- At least two feed fixtures or configured sources; no live LLM is required

## Configure

Create the existing local environment and configure these values through environment
variables or the project's settings source:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'

export DATABASE_URL='postgresql+psycopg://user:password@localhost/anxious_news'
export NEWS_MAX_CONCURRENCY='5'
export NEWS_FETCH_TIMEOUT_SECONDS='20'
export NEWS_NEAR_DUPLICATE_TITLE_THRESHOLD='0.85'
export NEWS_NEAR_DUPLICATE_CONTENT_THRESHOLD='0.80'
```

Do not commit credentials. Enrichment remains disabled unless a validated provider
adapter is explicitly configured.

## Initialize storage

```bash
alembic upgrade head
```

The migration must enable `pg_trgm` and create all constraints described in
[data-model.md](data-model.md).

## Run validation

```bash
pytest tests/unit/news tests/integration/news
```

The test suite must use fixture feeds, HTTP mock transports, fake enrichers, and an
ephemeral PostgreSQL database. It must not contact live sources or LLMs.

## Acceptance walkthrough

1. Configure two enabled fixture sources and one source that times out.
2. Run one aggregation cycle through the NewsAggregator application service.
3. Confirm valid records from both available sources are stored and the timed-out
   source has a failed SourceRun without cancelling its siblings.
4. Run the identical cycle again and confirm zero duplicate canonical articles and
   zero newly available articles.
5. Submit near-identical stories and confirm a persisted similarity decision with
   scores, thresholds, and normalization version.
6. Submit two differently worded reports of the same event and confirm source URLs
   remain distinct while event grouping can associate them.
7. Return complete, partial, invalid, and failed fake enrichment results and confirm
   the article always survives while only validated sections become analysis data.
8. Inspect cycle and source diagnostics and confirm they contain no credentials or
   unnecessary raw article content.
9. Confirm no aggregation table, contract, or log contains user preference or
   personalized ranking data.

## Expected result

The cycle returns only articles created during that run. Source failures and partial
analysis are visible but isolated, repeated input is idempotent, and the resulting
pool is ready for a future Personal Ranking module.

