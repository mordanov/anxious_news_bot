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
export NEWS_SCHEDULER_INTERVAL_SECONDS='60'
export NEWS_MAX_CONCURRENCY='5'
export NEWS_FETCH_TIMEOUT_SECONDS='20'
export NEWS_NEAR_DUPLICATE_TITLE_THRESHOLD='0.85'
export NEWS_NEAR_DUPLICATE_CONTENT_THRESHOLD='0.80'
```

Do not commit credentials. Enrichment remains disabled unless a validated provider
adapter is explicitly configured.

## Manage sources

Prepare a catalog conforming to
[`contracts/source-catalog.schema.json`](contracts/source-catalog.schema.json), then
preview and atomically apply it:

```bash
anxious-news-sources validate sources.json
anxious-news-sources apply sources.json
```

Omitted sources remain unchanged; set `"enabled": false` explicitly to disable one.

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
2. Start the application scheduler and allow one scan tick to invoke NewsAggregator.
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
10. Trigger a second tick while a cycle holds the advisory lock and confirm no
    overlapping cycle starts.
11. Validate and apply a catalog that adds, updates, and disables sources; confirm
    dry run does not write and an invalid catalog rolls back every change.

## Expected result

The cycle returns only articles created during that run. Source failures and partial
analysis are visible but isolated, repeated input is idempotent, and the resulting
pool is ready for a future Personal Ranking module.

## Executed acceptance record (2026-08-12)

The walkthrough was executed with the project `.venv` on macOS using Python
3.12.3. Network and enrichment boundaries used fixtures, HTTP mock transports, and
fake enrichers; no live feed, Telegram update, or LLM call was made.

Commands and observed results:

```text
cat > acceptance-source-catalog.json <<'JSON'
{"schema_version":"1.0","sources":[{"id":"5e4ec13c-d4ce-4bb1-8527-87cc911ecaa5","name":"Acceptance Fixture","source_type":"rss","endpoint_url":"https://example.com/acceptance-feed","region":"Antarctica","country_code":null,"language_code":"en","enabled":true,"quality_score":0.8,"polling_interval_seconds":300,"credential_ref":null}]}
JSON
.venv/bin/anxious-news-sources validate acceptance-source-catalog.json
valid
rm acceptance-source-catalog.json

.venv/bin/python - <<'PY'
import importlib.util
import json
from pathlib import Path
path = Path('tests/integration/news/test_duplicate_quality.py')
spec = importlib.util.spec_from_file_location('duplicate_quality', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
print(json.dumps(module.acceptance_metrics(), sort_keys=True))
PY
{"duplicate_consolidation_rate": 1.0, "duplicate_pairs": 72,
 "duplicate_precision": 1.0, "false_merges": 0, "unrelated_pairs": 288,
 "unrelated_separation_rate": 1.0}

.venv/bin/python -m pytest -o addopts='' \
  tests/integration/news/test_duplicate_quality.py \
  tests/unit/news/test_observability.py \
  tests/integration/news/test_cycle_performance.py
5 passed in 0.69s

.venv/bin/python -m pytest -o addopts='' tests/unit/news
78 passed

.venv/bin/python -m pytest -o addopts='' tests/integration/news -ra
14 passed; no skips reported

.venv/bin/python -m compileall -q src tests
exit status 0

.venv/bin/python -m pytest -o addopts=''
96 passed
```

The temporary catalog used by the validation command was removed after the command.
The integration run created migrated ephemeral PostgreSQL storage and exercised
advisory locking, source isolation/idempotency, duplicate decisions, event grouping,
validated analysis persistence, and transactional catalog changes. The focused
acceptance run enforced bounded concurrency, at least 95% ten-minute readiness,
at least 95% duplicate consolidation, at least 99% unrelated separation, and
structured-log redaction. No acceptance test was skipped. A separate PostgreSQL
server-version probe was not recorded because its fallback connection string was
credential-redacted and therefore not parseable; PostgreSQL-backed tests themselves
completed successfully.
