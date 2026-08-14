# Setup and Deployment

## Local prerequisites

- Python 3.11 or newer
- PostgreSQL 16 or newer
- Telegram bot token
- OpenAI-compatible structured-output endpoint for preferences/ranking/digests

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
```

Set at minimum:

```dotenv
TELEGRAM_BOT_TOKEN=replace-me
DATABASE_URL=postgresql+psycopg://localhost/anxious_news
PREFERENCES_MODEL_BASE_URL=https://provider.example/v1
PREFERENCES_MODEL_API_KEY=replace-me
PREFERENCES_MODEL_NAME=model-name
RANKING_MODEL_NAME=model-name
```

Digest composition reuses the ranking provider configuration. Keep `.env`
untracked and never place credentials in source, migration, test, or log data.

## Digest defaults

The complete list is in `.env.example`. Important operational defaults are:

```dotenv
DIGEST_SCAN_INTERVAL_SECONDS=60
DIGEST_CLAIM_BATCH_SIZE=100
DIGEST_MAX_CLAIMS_PER_TICK=1000
DIGEST_CLAIM_TIME_BUDGET_SECONDS=30
DIGEST_USER_CONCURRENCY=5
DIGEST_DEFAULT_COUNT=10
DIGEST_DEFAULT_LOCAL_TIME=09:00
DIGEST_DEFAULT_TIMEZONE=UTC
DIGEST_CANDIDATE_LIMIT=100
DIGEST_MAX_ATTEMPTS=3
DIGEST_RETRY_BASE_SECONDS=60
DIGEST_RETRY_MAX_SECONDS=900
DIGEST_HISTORY_RETENTION_DAYS=30
```

New and migrated users are not enabled automatically.

## PostgreSQL and migration

```bash
createdb anxious_news
DATABASE_URL=postgresql+psycopg://localhost/anxious_news \
  .venv/bin/python -m alembic upgrade head
DATABASE_URL=postgresql+psycopg://localhost/anxious_news \
  .venv/bin/python -m alembic current
```

Expected head:

```text
005_scheduler_digest (head)
```

Before production migration:

1. take and verify a database backup;
2. confirm revisions `001` through `004` are healthy;
3. run the migration against a restored staging copy;
4. verify existing users received one disabled configuration;
5. verify the partial due index and digest constraints;
6. deploy application code only after migration success.

Reviewed rollback:

```bash
DATABASE_URL=... .venv/bin/python -m alembic downgrade \
  004_question_dimension_context
```

Rollback removes digest state. Do not use it after production delivery without a
specific evidence-retention and recovery plan.

## Docker Compose

```bash
cp .env.example .env
# Set TELEGRAM_BOT_TOKEN and provider credentials.
docker-compose config --quiet
docker-compose up --build
```

Compose starts PostgreSQL, creates the application database, upgrades to head,
loads `sources.json`, and starts the bot. Useful checks:

```bash
docker-compose ps
docker-compose logs -f bot
docker-compose exec bot python -m alembic current
docker-compose exec postgres \
  psql -U anxious_news -d anxious_news
```

## Standalone Docker PostgreSQL for tests

When Compose is unavailable:

```bash
docker run --rm -d \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=postgres \
  -p 55432:5432 \
  postgres:16-alpine

export TEST_POSTGRES_ADMIN_URL=\
postgresql+psycopg://postgres:postgres@localhost:55432/postgres
```

Integration fixtures create, migrate, isolate, and drop temporary databases.

## Run

```bash
.venv/bin/anxious-news-bot
```

If console scripts are absent in an existing environment:

```bash
.venv/bin/python -m anxious_news_bot
```

Startup registers aggregation, preference/ranking retention, digest due/retry,
and digest retention jobs.

## Acceptance user

Schedule/timezone/enable commands are outside this feature. After a user has
interacted with the bot, an operator may enable one acceptance user:

```sql
UPDATE digest_configurations
SET enabled = true,
    digest_count = 10,
    schedule_local_time = (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::time(0),
    timezone_name = 'UTC',
    schedule_revision = schedule_revision + 1,
    next_due_at = CURRENT_TIMESTAMP
WHERE user_id = (
    SELECT id
    FROM application_users
    WHERE telegram_user_id = 123456789
);
```

This is an operational acceptance path, not a production end-user interface.

## Validation

```bash
TEST_POSTGRES_ADMIN_URL=... .venv/bin/python -m pytest \
  tests/unit/digest \
  tests/unit/telegram/test_count.py \
  tests/unit/telegram/test_digest.py \
  tests/integration/digest
TEST_POSTGRES_ADMIN_URL=... .venv/bin/python -m pytest
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
DATABASE_URL=... .venv/bin/python -m alembic check
```

## Production checks

- `/count 5` and `/count 20` persist and respond in the selected language.
- Invalid `/count` forms do not mutate the prior value.
- Disabled and not-due users produce no execution.
- A due user receives no more than the captured count.
- A zero-item execution completes without Telegram delivery.
- One failing user does not cancel other users.
- A transient pending part retries; an acknowledged part does not.
- An unknown part remains terminal and is queued for operational reconciliation.
- Logs contain no provider body, prompt, article text, or rendered digest.
