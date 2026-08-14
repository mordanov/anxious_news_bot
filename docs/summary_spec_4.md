# Implementation Summary: Specification 004

## Status

Scheduled News Digests is implemented across tasks T001–T049. The implementation
adds disabled-safe user configuration, timezone-aware occurrence claims,
personalized selection, structured localized content, `/count`, part-level
at-most-once Telegram delivery, bounded retries, non-repetition evidence,
retention, observability, migration, tests, and operational documentation.

## Delivered behavior

- Atomic application user, preference profile, and digest configuration
  provisioning.
- Digest count validation and localized `/count` for Russian, English, Spanish.
- Daily IANA-timezone schedules with explicit DST fold/gap behavior.
- Unique stable execution per user/local occurrence.
- Bounded indexed due claims and per-user concurrent isolation.
- Shared personal ranking path with internal user IDs, candidate limit override,
  pre-evaluation candidate filter, ranking/profile metadata, and grounded
  summaries.
- One strict indexed model request for localized title/summary content.
- Immutable deterministic item and message-part snapshots.
- Part claim-before-send, provider acknowledgement, confirmed history, and
  pending-part resume.
- Terminal conservative handling of ambiguous delivery.
- Versioned material-update evidence using novelty or normalized-content delta
  with duplicate/review vetoes.
- Monotonic success/terminal-failure summaries and bounded exponential retries.
- Retention that preserves active and unknown evidence.
- Redacted structured digest observability.

## Main changed surfaces

### Application

- `src/anxious_news_bot/digest/`
- `src/anxious_news_bot/telegram/count.py`
- `src/anxious_news_bot/telegram/digest.py`
- `src/anxious_news_bot/infrastructure/users.py`
- ranking delivery projection, ports, persistence, and `PersonalNewsService`
- preference persistence provisioner delegation
- app lifecycle and settings

### Database

- `migrations/versions/005_create_scheduler_digest.py`
- `migrations/env.py`

### Operations and documentation

- `.env.example`
- `docker-compose.yml`
- `README.md`
- `docs/architecture.md`
- `docs/setup.md`
- `docs/user-guide.md`
- `docs/development.md`
- this retrospective

## Validation evidence

Validation used standalone PostgreSQL 16 on `localhost:55432`:

- feature suite: **195 passed**;
- full pytest with PostgreSQL integration: **645 passed**, with two existing
  SQLAlchemy transaction-deassociation warnings in ranking model tests;
- Ruff lint: **all checks passed**;
- Ruff format: **332 files already formatted**;
- Docker Compose configuration: valid;
- Alembic fresh upgrade: `005_scheduler_digest (head)`;
- Alembic downgrade to `004_question_dimension_context` and re-upgrade: passed;
- Alembic ORM drift check: no new upgrade operations;
- bot lifecycle smoke: initialized with a fake Telegram transport, started,
  registered digest due/retention schedulers, answered `/start`, stopped, and
  shut down cleanly.

The performance integration fixture registered 10,000 configurations, measured
the first 100-row claim below the required one-second ceiling, and durably
claimed at least 990 of a 1,000-user due burst inside the five-minute budget.

## Migration and deployment status

The migration is upgradeable, downgradeable, and metadata-consistent. Existing
users are backfilled disabled; deployment does not opt users into messages.
Production still requires:

1. a reviewed backup;
2. migration to head before new application code starts;
3. valid Telegram and structured-model credentials;
4. explicit operational enable/time/timezone provisioning;
5. monitoring of `failed` and `delivery_unknown` executions.

No commit was created.

## Retrospective

### What went well

- Existing news, preference, ranking, model transport, JobQueue, and PostgreSQL
  boundaries were reused instead of introducing a broker or second scheduler.
- Database claims and immutable evidence make overlap/retry behavior explainable.
- History filtering occurs before expensive personal evaluation.
- Unknown Telegram outcomes fail conservatively rather than creating duplicate
  messages.
- Tests exercise DST, concurrency, migration, performance, user isolation,
  structured output, history, retries, rendering, and redaction without live
  providers.

### Corrections made during implementation

The first implementation pass falsely marked tasks complete while omitting
ranking extensions, integration tests, and final documentation. Review and
red/green tests exposed and corrected:

- retry recipient context incorrectly defaulting to Telegram user `0`;
- execution IDs being passed where attempt IDs were required;
- captured language being dropped;
- missing migration constraints and relationships;
- non-atomic delivery/history acknowledgement;
- missing exact content/part validation;
- absent material-update persistence and retention behavior;
- shutdown errors when JobQueue had already removed scheduled jobs.

### Scoped omissions

No requirement selected for this feature was intentionally omitted. The
following remain outside specification 004:

- user-facing enable/disable, local-time, and timezone commands;
- a Telegram provider reconciliation API for unknown sends;
- a separate distributed worker/broker;
- changing on-demand `/news` repetition behavior.

### Limitations

- Telegram cannot provide exactly-once delivery after an acknowledgement is
  lost; the implemented guarantee is at-most-once automatic send.
- Schedule provisioning is operational until a later user-facing feature.
- Retention scheduling currently uses a fixed daily cadence and batch size while
  the history horizon is configurable.
- Initial deployment is one process, although PostgreSQL claims support
  overlapping ticks and future additional processes.
- Automated tests use fake model/Telegram transports; production acceptance must
  still verify real provider compatibility and credentials.

### Concrete improvements

1. Add explicit schedule/timezone/enable commands with consent and revision
   auditing.
2. Add an operator reconciliation workflow for `delivery_unknown`.
3. Expose metrics and alerts for claim latency, retry age, unknown sends, and
   per-stage duration.
4. Make retention cadence/batch and stale-send lease explicit validated settings.
5. Add production canary delivery and provider-contract smoke tests.
6. Load-test concurrent multi-process claims and model/provider rate limiting at
   the expected production topology.
