# Quickstart: Scheduled News Digests

## Prerequisites

- Python 3.11 or newer
- PostgreSQL 16 or newer
- Existing project dependencies installed
- Telegram bot token configured
- Preference and ranking model endpoint, key, and model configured
- Migrations `001` through `004` already applicable

Scheduled content composition reuses the ranking model transport configuration.
No additional provider dependency or key is introduced.

## Configuration

Existing configuration remains required. Add validated digest settings:

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
DIGEST_MATERIAL_UPDATE_POLICY_VERSION=1.0
DIGEST_MATERIAL_UPDATE_NOVELTY_THRESHOLD=0.7000
DIGEST_MATERIAL_UPDATE_MAX_CONTENT_SIMILARITY=0.60000
DIGEST_MATERIAL_UPDATE_MIN_TEXT_CHARS=200
DIGEST_HISTORY_RETENTION_DAYS=30
DIGEST_CONTENT_MAX_INPUT_CHARS=2000
DIGEST_RENDERER_VERSION=1.0
```

Validation rules:

- default count is `5..20`;
- timezone must be a real IANA timezone;
- local time is `HH:MM`;
- candidate limit is at least 20 and at most the ranking maximum of 500;
- concurrency, batch, per-tick maximum, claim-time budget, interval, and
  attempts are positive and bounded;
- per-tick maximum is not below the claim batch size;
- retry maximum is not below retry base;
- material-update threshold is `0.0000..1.0000`;
- material-update policy version is non-empty, content similarity uses exactly
  five decimal places in `0.00000..1.00000`, and minimum text length is positive;
- history retention cannot be shorter than the configured ranking freshness
  horizon in whole days.

## Migrate

```bash
.venv/bin/alembic upgrade head
```

Migration `005_create_scheduler_digest` creates the digest schema and inserts one
disabled-safe configuration for every existing application user:

- enabled: false
- count: 10
- local time: 09:00
- timezone: UTC
- next due: null

After migration, the shared user provisioner atomically creates the application
user, preference profile, and the same disabled-safe digest configuration for
every new user, regardless of whether their first command is `/language`,
`/tune`, `/specify`, or `/count`.

## Run

```bash
.venv/bin/anxious-news-bot
```

At startup the application registers one digest timing adapter alongside existing
aggregation and retention jobs. The adapter scans for due and retryable work; it
does not create one in-memory job per user.

## Configure an Acceptance User

User-facing schedule, timezone, and enable commands are intentionally outside
this feature. For local acceptance testing, provision these values through the
operational database workflow after the user has interacted with the bot:

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

Replace the Telegram user ID. Do not use direct database changes as an end-user
interface in production; this is only the scoped operational acceptance path.

## Acceptance Scenarios

### `/count` boundaries

1. Send `/count 5`; expect localized confirmation and persisted count 5.
2. Run a due digest; verify at most 5 items.
3. Send `/count 20`; expect localized confirmation and persisted count 20.
4. Send `/count 4`, `/count 21`, `/count abc`, and `/count`; expect localized
   guidance and no state change.

### Insufficient suitable news

1. Configure count 10.
2. Make exactly three recent analyzed articles eligible after history and ranking
   quality rules.
3. Run the due execution.
4. Verify the structured digest and Telegram delivery contain exactly three
   articles and no filler.

### User isolation

1. Make users A and B due in the same scan.
2. Configure the composer or delivery fake to fail for A only.
3. Run one due cycle.
4. Verify A records its typed failure and B completes normally.

### Stable occurrence and timezone

1. Set a non-UTC IANA timezone and a due local time.
2. Run overlapping scans.
3. Verify exactly one execution exists for the local occurrence.
4. Repeat with a DST fold and gap fixture; verify the documented earlier-fold and
   first-valid-after-gap policies and one execution per local date/time.

### Retry and delivery idempotency

1. Cause a transient composition failure before items persist.
2. Advance the fixed clock to `next_retry_at`; rerun.
3. Verify the same execution and ranking request ID are reused.
4. Deliver part 1 successfully, then fail part 2 definitively and transiently.
5. Retry; verify part 1 is skipped and only part 2 is sent.
6. Simulate an ambiguous result for a sending part.
7. Verify execution becomes `delivery_unknown`, uncertain history is inserted,
   and subsequent retry scans never resend the part.

### Delivery history

1. Complete a digest containing article X.
2. Include X and another unchanged article in X's event group in the next
   candidate set.
3. Verify both are excluded before personal evaluation.
4. Add a later article in the event group with complete analysis novelty at or
   above the configured threshold.
5. Verify the new development remains eligible and can be ranked.
6. Repeat with conservative baseline novelty, sufficiently different normalized
   content, and no duplicate/review pair decision.
7. Verify versioned `content_delta` evidence is persisted and the article remains
   eligible; then add a review decision and verify it is excluded.

### Structured content

1. Compose 20 ranked items in Russian, English, and Spanish fixtures.
2. Verify exact indexes 1..20, localized non-empty title/summary, original order,
   and deterministic source/time/URL preservation.
3. Return a duplicate, missing, extra, or out-of-range index from the fake model.
4. Verify no partial digest items persist and the execution follows retry policy.

## Validation

Run the smallest feature suite first:

```bash
.venv/bin/python -m pytest \
  tests/unit/digest \
  tests/unit/telegram/test_count.py \
  tests/unit/telegram/test_digest.py \
  tests/integration/digest
```

Then run project checks:

```bash
.venv/bin/python -m pytest
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

Inspect migration state:

```bash
.venv/bin/alembic current
```

Expected head: `005_create_scheduler_digest`.

## Safe Observability

Structured digest logs include only bounded operational fields:

- execution ID and occurrence key hash;
- user ID hash, never raw Telegram user ID;
- phase, status, attempt, and safe reason code;
- selected item and delivery-part counts;
- duration and retry scheduling;
- language code and configuration versions.

Logs exclude Telegram tokens, provider URLs containing credentials, prompts,
answers, model output, article text, rendered messages, and provider response
bodies.
