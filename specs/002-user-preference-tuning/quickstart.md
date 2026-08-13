# Quickstart: User Preference Tuning

This workflow describes expected setup and acceptance checks after implementation.

## Prerequisites

- Python 3.11 or newer
- PostgreSQL 16 or newer with the existing `pg_trgm` extension
- A dedicated development database
- A Telegram bot token for manual interaction
- A configured compatible model endpoint for manual generation/interpretation

Automated tests use fake model ports and do not require live Telegram or model
access.

## Configure

Create the local environment and configure the existing application plus preference
settings:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'

export DATABASE_URL='postgresql+psycopg://localhost/anxious_news'
export TELEGRAM_BOT_TOKEN='replace-with-secret'
export PREFERENCES_MODEL_BASE_URL='https://provider.example/v1'
export PREFERENCES_MODEL_API_KEY='replace-with-secret'
export PREFERENCES_MODEL_NAME='configured-structured-output-model'
export PREFERENCES_MODEL_TIMEOUT_SECONDS='30'
export PREFERENCES_MODEL_RETRY_ATTEMPTS='2'
export PREFERENCES_HISTORY_QUESTION_LIMIT='50'
export PREFERENCES_DUPLICATE_REVIEW_THRESHOLD='0.72'
export PREFERENCES_QUESTIONNAIRE_RETENTION_DAYS='365'
export PREFERENCES_CHANGE_HISTORY_RETENTION_DAYS='0'
export PREFERENCES_RETENTION_SCAN_INTERVAL_SECONDS='86400'
export PREFERENCES_RETENTION_BATCH_SIZE='500'
```

Do not commit credentials. Model configuration is optional for automated tests
because fake ports provide deterministic documents.

## Initialize storage

```bash
alembic upgrade head
```

The migration creates application users, profiles, parameters, questionnaires,
questions, options, answers, update batches, and immutable change history with the
constraints described in [data-model.md](data-model.md).

## Run validation

```bash
pytest tests/unit/preferences tests/integration/preferences tests/unit/telegram
```

Tests use strict fixture documents, fixed clocks and callback tokens, fake model
ports, and ephemeral PostgreSQL. They must not call live Telegram or model
services.

## Acceptance walkthrough

1. Start `/tune` for a new user and confirm exactly 10 persisted questions with four
   distinct options each.
2. Answer nine questions and confirm no preference parameter or history row is
   created.
3. Restart the application, issue `/tune`, and confirm question 10 resumes.
4. Deliver the same callback twice and confirm only one answer exists and the
   questionnaire advances once.
5. Answer question 10 with a valid fake proposal and confirm one profile revision
   increment, all intended parameter changes, and complete before/after history.
6. Run `/tune` again and confirm prior context is supplied and substantial repeated
   questions are rejected.
7. Propose `-1.00`, `0.00`, and `1.00` boundary weights and confirm exact
   two-decimal persistence; reject excess precision, exponent notation, negative
   zero, and out-of-range values.
8. Propose an exact-key, lexical, and paraphrased duplicate and confirm creation is
   rejected or redirected to reuse/refinement.
9. Propose adjusting (including strengthening), refining, deactivating, or
   reactivating explicit, inference, and system parameters; confirm every entire
   batch is rejected and all protected parameters remain unchanged.
10. Inject malformed generation, malformed interpretation, and a database failure
    after each application write; confirm the prior profile remains unchanged.
11. Apply the same questionnaire concurrently twice and confirm it changes the
    profile once.
12. Change the profile revision during interpretation and confirm stale output
    applies nothing and is reinterpreted against the new profile.
13. Submit a foreign-user token, invalid token, stale keyboard, and two raced
    options; confirm no unauthorized or duplicate answer is recorded.
14. Inspect structured logs and confirm they contain no credentials, callback
    tokens, question/answer text, or full profile snapshots.
15. Set short retention periods, create expired applied and failed questionnaires,
    run one cleanup tick, and confirm no more than the configured batch is removed.
16. Confirm active questionnaires and current parameters are unchanged, failed
    expired sessions are removed, applied sessions retain questionnaire/batch
    identities and audit digests, every applied change retains its compact audit
    row, and full history remains when its retention is `0`.
17. Enable positive full-history retention, expire detailed change rows, and
    confirm each removed row still has an immutable compact record with parameter,
    action, source, questionnaire/batch, timestamp, and previous/new/reason hashes.
    Confirm cleanup refuses deletion when a matching compact record is absent.
18. Propose an equivalent create beside a protected parameter and confirm no
    duplicate is created; then propose a genuinely narrower distinct dimension and
    confirm it creates a questionnaire-origin parameter without changing the
    protected parameter.

## Expected result

Users can complete and resume adaptive 10-question sessions. Accepted model output
passes strict structural and semantic validation before one deterministic atomic
update. Invalid, stale, duplicate, replayed, or concurrent input leaves the
previous profile intact, and every applied change is auditable.
