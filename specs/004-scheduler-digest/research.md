# Research: Scheduled News Digests

## 1. Scheduler and Application Boundary

**Decision**: Keep due-cycle orchestration behind digest application ports and use
the already installed JobQueue only as a repeating timing adapter. Each tick asks
the application service to claim a bounded batch and does not contain due,
ranking, retry, or delivery rules.

**Rationale**: This satisfies the technology-independent scheduler interface,
preserves Telegram as a thin delivery surface, and reuses proven process
lifecycle wiring without another daemon or dependency.

**Alternatives considered**:
- APScheduler: rejected because JobQueue already provides the required trigger
  and a second scheduler adds no business capability.
- Cron or a separate worker: rejected for initial single-process scale and
  because deployment/coordination complexity is not required.
- One JobQueue job per user: rejected because restart rescheduling, 10,000 jobs,
  timezone changes, and duplicate coordination are harder than an indexed due
  scan.

## 2. Timezone-Aware Daily Occurrences

**Decision**: Store a validated IANA timezone, local wall-clock time, and
`next_due_at` in UTC. Identify an occurrence by user plus a canonical key derived
from local date, local time, and timezone. On a repeated DST time, choose the
earlier valid instant; on a missing time, choose the first valid instant after
the gap. Recompute `next_due_at` after each successful occurrence claim and after
configuration changes.

**Rationale**: UTC supports indexed scans, while the local occurrence key ensures
one intended daily delivery across DST folds and overlapping ticks. Explicit gap
and fold policies make tests deterministic.

**Alternatives considered**:
- Fixed UTC schedules: rejected because they do not preserve the user's local
  delivery time across offset changes.
- Persisting cron expressions: rejected because the requested scope needs one
  recurring daily time and cron adds parsing and ambiguous DST semantics.
- Uniqueness only on UTC timestamp: rejected because timezone edits and DST folds
  can represent one local occurrence with different instants.

## 3. Work Claiming and User Isolation

**Decision**: Claim configurations in indexed batches with row locking that skips
already claimed rows, insert one execution under a unique occurrence constraint,
advance `next_due_at` in the same transaction, then process claimed execution IDs
with bounded asynchronous concurrency. Catch and persist failures per execution.

**Rationale**: A short claim transaction prevents duplicate scheduled work across
overlapping ticks and future processes. Processing outside that transaction avoids
long locks, and per-execution exception boundaries satisfy user isolation.

**Alternatives considered**:
- In-memory locks: rejected because they disappear on restart and do not protect
  multiple processes.
- One transaction for the full digest: rejected because model, ranking, and
  messaging calls would hold locks during external I/O.
- Unbounded gather: rejected because a due wave could exhaust database and model
  capacity.

## 4. Retry and At-Most-Once Delivery

**Decision**: Persist a stable execution ID and attempt rows. Retry only failures
classified as transient and only before the configured attempt limit. Render
delivery parts once, hash them, claim each part before send, and persist provider
message IDs after acknowledgement. A part with an ambiguous outcome becomes
`unknown`, is conservatively added to history, and is never automatically resent.
Confirmed earlier parts are skipped when later parts resume.

**Rationale**: Telegram does not provide a client idempotency key. Exactly-once
delivery cannot be guaranteed after an acknowledgement is lost; an at-most-once
policy is the only design that satisfies "do not accidentally duplicate" under
uncertainty. Per-part state also prevents a retry after a later-part failure from
duplicating acknowledged earlier messages.

**Alternatives considered**:
- Blindly resend the whole digest: rejected because it duplicates messages after
  partial or ambiguous success.
- Mark complete before send: rejected because a definite pre-send failure would
  silently lose a safely retryable delivery.
- Rely on execution ID in message text: rejected because Telegram does not dedupe
  equal content or expose idempotent send semantics.

## 5. Delivery History and Material Updates

**Decision**: Persist per-user history for confirmed and uncertain item delivery.
Always exclude the same normalized article. For another article in the same
event/story group, exclude it unless a newer complete analysis has novelty at or
above a configurable material-update threshold and was published after the
previous delivery. Apply this deterministic filter to candidate IDs before
personal evaluation and ranking.

**Rationale**: Existing normalized article IDs, event groups, analyses, publication
times, and novelty scores provide auditable evidence without a new semantic
service. Conservative treatment of uncertain delivery prevents repetition.
Filtering before ranking avoids spending model calls on prohibited candidates and
keeps ranking mathematics unchanged.

**Alternatives considered**:
- URL-only history: rejected because equivalent articles and source duplicates
  can use different URLs.
- Permanent event-group exclusion: rejected because it suppresses legitimate new
  developments.
- Let an LLM decide repetition during every digest: rejected because it is
  nondeterministic, costly, and an inappropriate source of truth.

## 6. Ranking Reuse and Candidate Pool

**Decision**: Refactor `PersonalNewsService` so `/news` and scheduled digests share
one selection pipeline. Add an internal user-ID entry point, an optional generic
candidate filter, and a bounded candidate-limit override. Scheduled digests use a
default pool of 100 (five times the maximum digest size), capped by the existing
ranking maximum; `/news` retains its existing count and candidate limit.

**Rationale**: This reuses generic analysis enforcement, personal evaluation,
deterministic ranking, and diversity. A larger bounded pool allows history and
quality filters to remove candidates without filling with irrelevant articles.

**Alternatives considered**:
- Duplicate ranking orchestration in `digest`: rejected by module boundaries and
  the requirement that scheduler code contain no ranking logic.
- Rank first and remove history afterward: rejected because it may return fewer
  items while suitable lower-ranked candidates were never selected.
- Expand without a cap: rejected because model work and latency must remain
  predictable.

## 7. Structured Localized Digest Content

**Decision**: Compose all selected items in one strict indexed model request,
bounded to 20 inputs. Each output contains only localized title and concise
localized summary; source, publication time, URL, article identity, position, and
score come from deterministic application data. Require exact index coverage and
persist accepted structured items before delivery. Use the normalized summary, or
a bounded source-text excerpt when absent, as grounding.

**Rationale**: The feature requires summaries and the user's language, while the
existing translator only supports ten titles. One validated batch minimizes calls,
prevents order drift, and allows retries to reuse identical accepted content.

**Alternatives considered**:
- Reuse the title-only translator repeatedly: rejected because summaries would
  remain missing and multiple calls can produce partial inconsistent results.
- Compose independently in Telegram: rejected because Telegram must only format
  and deliver structured items.
- Fall back to invented or mixed-language content after model failure: rejected
  because it violates language and trust-boundary expectations; retry or controlled
  failure is safer.

## 8. Persistence Layout and Retention

**Decision**: Add separate configuration, execution, attempt, item, delivery-part,
and history tables in migration `005`. Keep execution/item evidence long enough
for retry and audit; retain compact history for at least the ranking freshness
horizon and repetition policy. Backfill existing users with disabled digest
configuration, count 10, 09:00 local time, and UTC timezone.

**Rationale**: Separate lifecycle rows make state transitions and delivery
acknowledgements enforceable with constraints. Disabled backfill avoids surprising
existing users because schedule/enable commands are outside this feature.

**Alternatives considered**:
- Add all fields to `application_users`: rejected because execution and
  one-to-many delivery evidence do not belong on the identity row.
- Derive delivery history only from logs: rejected because logs are neither
  transactional nor authoritative.
- Enable all users during migration: rejected because timezone and consent are
  not known.

## 9. `/count` Ownership and User Creation

**Decision**: Implement a digest configuration service and thin localized
Telegram adapter. The service accepts only parsed integer values in 5..20,
ensures the existing application user/profile through the preference repository,
then upserts the user's disabled-safe digest configuration in one transaction.

**Rationale**: The command changes digest state, not preferences or ranking. Reuse
of the existing user/profile claim avoids competing identity creation behavior.

**Alternatives considered**:
- Put validation and persistence in the Telegram handler: rejected by the
  constitution and because it prevents adapter-free testing.
- Store count in the preference profile: rejected because it is operational
  digest configuration, not semantic news preference.
- Reject users without prior `/tune`: rejected because `/count` should work as an
  independent command.

