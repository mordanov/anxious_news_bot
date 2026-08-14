# Project Memory

**Updated**: 2026-08-14  
**Current feature**: `004-scheduler-digest`  
**Implementation status**: Complete (T001-T049)

## Product

Anxious News Bot is a PostgreSQL-backed Telegram news application. It aggregates
RSS/Atom feeds, normalizes and deduplicates articles, groups related events,
captures explicit and questionnaire preferences, ranks news deterministically
for each user, and delivers localized on-demand news and scheduled digests.

Supported user languages:

- Russian
- English
- Spanish

User commands:

- `/start` - check bot availability
- `/language` - choose the persisted language
- `/tune` - run a 10-question preference questionnaire
- `/specify <text>` - add or refine an explicit preference
- `/news` - receive the current personalized top 10
- `/count <5..20>` - set the scheduled digest size

Digest enablement, local delivery time, and timezone are operational settings;
user-facing commands for them are not implemented yet.

## Architecture

The application is a Python 3.11 modular monolith:

- `news` owns collection, normalization, provenance, deduplication, event
  grouping, and generic analysis.
- `preferences` owns language, questionnaires, explicit requests, preference
  authority, history, and retention.
- `ranking` owns personal article evaluation, deterministic scoring,
  explainability, eligibility, and diversity.
- `digest` owns configuration, timezone-aware scheduling, execution state,
  content composition, delivery history, retries, material-update evidence, and
  retention.
- `telegram` contains thin command and delivery adapters only.
- `infrastructure/users.py` atomically provisions the application user,
  preference profile, and disabled-safe digest configuration.

PostgreSQL is the source of truth. External model responses use strict structured
schemas and are validated before deterministic application code persists them.
Telegram and model providers are replaceable with test doubles.

See:

- `docs/architecture.md`
- `docs/setup.md`
- `docs/user-guide.md`
- `docs/development.md`

## Scheduled Digest Design

- Existing users are backfilled with disabled digest configuration.
- New users atomically receive disabled-safe preference and digest state.
- Daily schedules use an IANA timezone and explicit DST fold/gap behavior.
- `(user, local occurrence)` uniquely identifies a scheduled execution.
- Due work is claimed in indexed, bounded PostgreSQL batches.
- One user's failure never cancels another user's digest.
- Selection reuses the existing personal ranking and diversity pipeline.
- Delivery history filters candidates before expensive personal evaluation.
- A digest contains 5-20 configured items, or fewer when suitable news is
  insufficient; irrelevant filler is forbidden.
- Titles and summaries are localized in one strict indexed model request.
- Structured item and Telegram message-part snapshots are immutable.
- Each message part is claimed before send and acknowledged with provider
  evidence.
- Confirmed parts are skipped during retries.
- Ambiguous provider outcomes become terminal `delivery_unknown` and are not
  resent automatically.
- Material updates use versioned persisted evidence based on accepted novelty or
  deterministic same-event normalized-content delta with duplicate/review
  vetoes.

## Important Persistence

Alembic revisions:

1. `001_create_news_aggregation`
2. `002_create_user_preferences`
3. `003_create_personalized_ranking`
4. `004_question_dimension_context`
5. `005_scheduler_digest` (head)

Digest persistence covers:

- user digest configuration;
- unique scheduled executions and attempts;
- immutable digest items;
- delivery message parts;
- confirmed and uncertain delivery history;
- versioned material-update evidence.

Migration `005_scheduler_digest` supports fresh upgrade, downgrade to revision
004, and re-upgrade without ORM drift.

## Reliability Decisions

- LLM output never directly mutates state.
- Final ranking and selection are deterministic.
- Explicit preference evidence has the highest semantic authority.
- Retries reuse execution and ranking request identities.
- Unknown Telegram acknowledgement favors avoiding duplicates over automatic
  redelivery.
- Logs exclude credentials, prompts, model output, article text, and rendered
  messages.
- HTTPX INFO logging remains suppressed because Telegram request URLs may contain
  bot credentials.
- Retention never removes active retry or unknown-delivery evidence.

The shutdown scheduler must tolerate jobs already removed by JobQueue. An earlier
`JobLookupError` during shutdown was fixed; subsequent startup and shutdown
completed cleanly.

## Configuration

Core provider variables:

- `TELEGRAM_BOT_TOKEN`
- `DATABASE_URL`
- `PREFERENCES_MODEL_BASE_URL`
- `PREFERENCES_MODEL_API_KEY`
- `PREFERENCES_MODEL_NAME`
- `RANKING_MODEL_BASE_URL`
- `RANKING_MODEL_API_KEY`
- `RANKING_MODEL_NAME`

Ranking provider URL/key fall back to preference provider values. A ranking model
name is still required for ranking and digest content operations.

Key digest defaults:

- scan interval: 60 seconds;
- claim batch: 100;
- maximum claims per tick: 1000;
- claim time budget: 30 seconds;
- user concurrency: 5;
- digest count: 10;
- local time: 09:00;
- timezone: UTC;
- candidate limit: 100;
- attempts: 3;
- retry range: 60-900 seconds;
- history retention: 30 days.

All settings and their environment names are documented in `.env.example`,
`README.md`, and `docs/setup.md`.

## Validation Baseline

Latest completed validation:

- feature suite: 195 passed;
- full pytest with PostgreSQL: 645 passed;
- Ruff lint: passed;
- Ruff format: 332 files formatted;
- Alembic fresh upgrade: passed;
- Alembic downgrade/re-upgrade: passed;
- Alembic drift check: passed;
- Docker Compose configuration: valid;
- performance thresholds: passed;
- bot lifecycle with fake Telegram transport: startup, `/start`, scheduler
  registration, shutdown all passed.

Two SQLAlchemy transaction-deassociation warnings remain in ranking model tests;
they did not fail validation.

## Operating Commands

```bash
.venv/bin/python -m pytest
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/alembic upgrade head
.venv/bin/alembic current
docker compose up --build
docker compose logs -f bot
docker compose exec bot alembic current
docker compose down
```

If the Compose plugin is unavailable, use the environment's `docker-compose`
command or standalone Docker for PostgreSQL validation.

## Current Runtime State

- Implementation is complete.
- No git commit was created by the implementation workflow.
- No production deployment was performed.
- The smoke-test bot and temporary PostgreSQL container were intentionally
  stopped after validation, so the bot is currently unresponsive by design.
- Existing users remain opted out of scheduled delivery until explicitly enabled
  and assigned operational schedule/timezone values.

## Known Limitations and Next Improvements

- Add user-facing enable/disable, time, and timezone commands with consent and
  revision auditing.
- Add operator reconciliation for `delivery_unknown`.
- Add metrics and alerts for claim latency, retries, unknown sends, and stage
  duration.
- Make retention cadence, retention batch size, and stale-send lease explicit
  validated settings.
- Add production provider canaries and real Telegram/model contract smoke tests.
- Load-test multi-process claims and provider rate limiting.

## Detailed Retrospectives

- `docs/summary_spec_3.md` - explicit preferences and personalized ranking
- `docs/summary_spec_4.md` - scheduled digest implementation, omissions,
  strengths, limitations, and improvements

