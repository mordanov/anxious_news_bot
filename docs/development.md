# Development Guide

## Module ownership

Keep changes inside the owning boundary:

- `news`: ingestion, normalization, generic analysis, deduplication, events.
- `preferences`: language and semantic preference state.
- `ranking`: personal evaluation, deterministic scoring, diversity.
- `digest`: schedules, occurrence/execution state, history, composition,
  retries, retention.
- `telegram`: command parsing, rendering, and provider adaptation.

Scheduler code must not implement ranking mathematics. Telegram code must not
query news, translate independently, or decide history eligibility.

## Key extension points

Protocols in `digest/ports.py` isolate:

- clock;
- configuration/execution persistence;
- candidate filtering;
- structured composition;
- rendering and delivery.

`PersonalNewsService.select_for_user` is the shared internal ranking path. Keep
`top(telegram_user_id, ...)` backward compatible for `/news`.

To add another delivery channel:

1. consume `StructuredDigest`;
2. implement deterministic `render` and typed `send`;
3. persist stable descriptors before sending;
4. preserve at-most-once unknown-outcome handling;
5. do not move composition or ranking into the channel.

## Persistence rules

- Use short caller-owned transactions around claims and state changes.
- Never hold a database transaction over model, HTTP, or Telegram calls.
- Lock execution/part rows before compare-and-set transitions.
- Keep `(user_id, occurrence_key)` and `(execution_id, ordinal)` identities
  stable.
- Insert digest items as one exact contiguous immutable set.
- Verify part hashes/ranges on every retry.
- Write acknowledgement and delivery history atomically.
- Treat stale `sending` state as unknown unless external evidence proves
  non-acceptance.
- Keep terminal configuration summaries monotonic by completion timestamp.

Migration revision IDs must fit the existing Alembic version column. Import new
ORM modules in `migrations/env.py` so `alembic check` can detect drift.

## Structured-model boundary

Composer inputs contain only bounded title and summary/text grounding. Composer
outputs are untrusted until strict Pydantic validation confirms:

- schema version `1.0`;
- no extra fields;
- exactly one item per expected index;
- indexes `1..N`;
- title and summary length/non-whitespace constraints.

IDs, event groups, source, time, URL, score, count, and state always come from
deterministic application data.

## Tests and TDD

Write the failing test before behavior changes. Use:

- fixed UTC clocks for schedule/retry behavior;
- fakes from `tests/fixtures/digest.py` for isolated services;
- pure unit tests for DST, rendering, schema, material updates, and redaction;
- ephemeral PostgreSQL for constraints, concurrency, claims, idempotency,
  retention, migration, and performance;
- fake model and Telegram transports—never live providers in automated tests.

Feature suite:

```bash
TEST_POSTGRES_ADMIN_URL=... .venv/bin/python -m pytest \
  tests/unit/digest \
  tests/unit/telegram/test_count.py \
  tests/unit/telegram/test_digest.py \
  tests/integration/digest
```

Project checks:

```bash
TEST_POSTGRES_ADMIN_URL=... .venv/bin/python -m pytest
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
DATABASE_URL=... .venv/bin/python -m alembic upgrade head
DATABASE_URL=... .venv/bin/python -m alembic current
DATABASE_URL=... .venv/bin/python -m alembic check
```

Integration tests skip explicitly when the PostgreSQL admin URL is unavailable.
For release validation, skipped integration tests are not an acceptable pass.

## Common change workflows

### Change count rules

The user-facing range is fixed at `5..20`. Update domain validation, settings,
database checks, command guidance, contracts, and boundary tests together.

### Change schedule policy

Update occurrence resolution and fixed-clock DST tests first. Do not rely on
process-local timezone or naive datetimes.

### Change material-update policy

Create a new policy version. Never reinterpret an existing persisted pair/policy
decision in place.

### Change Telegram rendering

Increment the renderer version, retain split-only-between-items behavior, and
verify every message stays below 3900 characters. A persisted descriptor mismatch
must fail closed rather than silently resend changed content.

### Add a migration

1. create the next revision with the current head as `down_revision`;
2. add database constraints and indexes, not only ORM validation;
3. test upgrade/backfill/downgrade/re-upgrade;
4. run `alembic check`;
5. document deployment and rollback impact.

## Review checklist

- No raw prompts, provider bodies, article text, rendered messages, or
  credentials in logs.
- No external call inside a transaction.
- No new unbounded candidate/history query.
- No retry path with a new execution identity or missing recipient context.
- No automatic resend of sent/unknown parts.
- No history filtering after ranking.
- No unrelated `/news` behavior change.
- Tests cover failure isolation and stale/overlapping claims.
