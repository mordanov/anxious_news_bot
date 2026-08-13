# Feature Specification: Scheduled News Digests

**Feature Branch**: `004-scheduler-digest`  
**Created**: 2026-08-13  
**Status**: Draft  
**Input**: User description: "@requirements/04_scheduler_digest.md"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Receive a Personalized Digest on Schedule (Priority: P1)

As a user with digests enabled, I receive a concise personalized news digest at
the configured local time so that I can stay informed without requesting news
manually.

**Why this priority**: Scheduled delivery is the feature's primary user value.

**Independent Test**: Configure an enabled user with a due schedule, suitable
recent news, preferences, and a timezone; run the due cycle and verify that one
personalized digest is delivered and the successful execution is recorded.

**Acceptance Scenarios**:

1. **Given** an enabled user whose schedule is due in the user's timezone and at
   least the configured number of suitable articles exist, **When** the due
   cycle runs, **Then** the user receives one ranked, diverse digest containing
   no more than the configured number of articles.
2. **Given** an enabled user whose schedule is not due, **When** the due cycle
   runs, **Then** no digest execution or delivery is started for that user.
3. **Given** a user whose digest is disabled, **When** the configured delivery
   time passes, **Then** no digest is delivered.
4. **Given** a user configured for 10 articles but only 3 suitable articles
   exist, **When** the digest executes, **Then** exactly those 3 suitable
   articles are delivered without irrelevant filler.

---

### User Story 2 - Choose Digest Size (Priority: P2)

As a user, I can choose how many articles each scheduled digest may contain so
that the digest matches the amount of news I want to read.

**Why this priority**: Digest size is the only new direct user setting and
controls the length of every scheduled delivery.

**Independent Test**: Submit valid and invalid `/count` commands and verify both
the immediate response and the article limit applied to the next digest.

**Acceptance Scenarios**:

1. **Given** a user with any current digest count, **When** the user sends
   `/count 5`, **Then** the value 5 is persisted and future digests contain at
   most 5 articles.
2. **Given** a user with any current digest count, **When** the user sends
   `/count 20`, **Then** the value 20 is persisted and future digests contain at
   most 20 articles.
3. **Given** a user with a persisted digest count, **When** the user sends a
   value below 5, above 20, non-numeric, or missing, **Then** the value remains
   unchanged and the user receives guidance describing the valid range.

---

### User Story 3 - Receive Reliable, Non-Repetitive Delivery (Priority: P3)

As a user, I receive each scheduled digest at most once and do not repeatedly
see unchanged articles, even when a delivery attempt is retried.

**Why this priority**: Duplicate digests and repetitive articles undermine
trust in scheduled delivery.

**Independent Test**: Retry the same execution after a transient failure and
run later digests containing previously delivered articles; verify at-most-once
delivery for the execution and suppression of unchanged prior articles.

**Acceptance Scenarios**:

1. **Given** a scheduled execution experiences a transient failure before
   completion, **When** it is retried, **Then** the retry retains the same
   execution identity and no more than one completed delivery is produced.
2. **Given** an article was previously delivered to a user and has not
   materially changed, **When** a later digest is assembled, **Then** that
   article is excluded for that user.
3. **Given** a previously delivered story has a material new development,
   **When** a later digest is assembled, **Then** the updated story may be
   selected if it remains suitable and competitive.
4. **Given** one user's execution fails, **When** other users are also due,
   **Then** their executions continue independently.

### Edge Cases

- A user's timezone changes after a future execution was calculated; the next
  due decision uses the current persisted timezone and does not double-send.
- Daylight-saving transitions produce a missing or repeated local clock time;
  the user receives no more than one digest for a scheduled occurrence.
- The digest count changes while an execution is underway; that execution uses
  the count captured when it started, while later executions use the new value.
- No suitable recent articles exist; the execution succeeds with no irrelevant
  digest content sent and records that zero items were selected.
- An article lacks required analysis; it must be analyzed successfully before
  selection or excluded from that execution.
- A delivery outcome is unknown after a communication interruption; a retry
  must reconcile the same execution rather than create a new scheduled run.
- A permanent failure is recorded without repeated automatic retries, while a
  transient failure may be retried according to the configured retry policy.
- An article appears through multiple sources or identifiers; delivery-history
  rules treat recognized versions of the same unchanged story consistently.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST atomically persist one disabled-safe digest
  configuration whenever an application user is created, including enabled
  state, digest count, schedule, timezone, last successful execution, and last
  terminally failed execution.
- **FR-002**: Digest count MUST be an integer from 5 through 20, inclusive.
- **FR-003**: The `/count <value>` command MUST persist a valid digest count for
  the current user and confirm the new value in that user's chosen language.
- **FR-004**: The `/count` command MUST reject missing, non-integer, below-range,
  and above-range values without changing the persisted count.
- **FR-005**: The system MUST identify enabled users whose configured schedule
  is due according to each user's current timezone.
- **FR-006**: Each due user MUST receive an isolated digest execution so that a
  failure for one user does not block or cancel executions for other users.
- **FR-007**: Each execution MUST capture the user's effective preferences,
  digest count, schedule occurrence, and timezone context used for that run.
- **FR-008**: Each execution MUST consider only recent normalized news and MUST
  require suitable article analysis before an article can be ranked.
- **FR-009**: The scheduler MUST delegate personalization, ranking, diversity,
  and article-suitability decisions to their owning business capabilities
  rather than define separate ranking mathematics.
- **FR-010**: The system MUST select no more than the execution's captured
  digest count and MUST return fewer items when fewer suitable articles exist.
- **FR-011**: The system MUST NOT add irrelevant articles merely to reach the
  configured digest count.
- **FR-012**: A digest MUST consist of ordered structured items containing a
  title, summary, source, publication time, and URL.
- **FR-013**: Digest content presented to a user MUST follow the user's existing
  language preference while preserving source identity, publication time, and
  destination URL.
- **FR-014**: Channel-specific rendering MUST remain separate from digest
  selection and construction so another delivery channel can consume the same
  structured digest.
- **FR-015**: The system MUST retain per-user delivery history sufficient to
  identify previously delivered articles or equivalent versions of the same
  story.
- **FR-016**: Previously delivered, materially unchanged articles MUST be
  excluded unless an explicit repetition policy or direct user request permits
  reuse.
- **FR-017**: A previously delivered story MAY be selected when a newer article
  has deterministic persisted evidence of a material update or new development,
  based on either accepted novelty analysis or a versioned same-event normalized
  content comparison that demonstrates material change and is not contradicted
  by duplicate or review evidence.
- **FR-018**: Every scheduled digest execution MUST have a unique, stable
  execution identifier and a distinguishable state for scheduled, retrying,
  completed, and failed processing.
- **FR-019**: Retries of the same scheduled occurrence MUST reuse its execution
  identity and MUST NOT create more than one completed digest delivery.
- **FR-020**: The system MUST record each execution's result, including selected
  item count, completion or failure state, timestamps, attempt history, and a
  safe failure classification when applicable.
- **FR-021**: The system MUST record the user's last successful execution and
  last terminally failed execution without allowing an older execution to
  overwrite newer status; transient attempts that later recover MUST remain in
  attempt history but MUST NOT replace the terminal-failure summary.
- **FR-022**: Transient failures MUST be eligible for bounded retry; permanent
  failures MUST be recorded and excluded from automatic retry.
- **FR-023**: An execution with no suitable articles MUST complete without
  sending irrelevant content and MUST record a zero-item result.
- **FR-024**: The scheduler capability MUST expose business-level operations for
  finding due users, executing a digest, recording success, recording failure,
  and retrying transient failures independently of the timing mechanism.
- **FR-025**: Schedule evaluation MUST prevent more than one scheduled execution
  for the same user and scheduled occurrence, including across repeated local
  times caused by timezone transitions.
- **FR-026**: Digest execution and failure records MUST avoid storing message
  credentials or unrestricted article/user content in diagnostic details.

### Constitution Alignment *(mandatory)*

- **Affected Modules**: Adds digest scheduling and execution orchestration while
  reusing user preferences, news aggregation, article analysis, personal
  ranking, diversity selection, localization, and messaging boundaries.
- **Personalization Impact**: Each execution uses the current user profile and
  the existing personal-ranking capability. Delivery history becomes an
  additional eligibility constraint but does not replace ranking rules.
- **LLM and Determinism**: Any analysis, summaries, or localization supplied by
  a language model must be structured and validated. Due-user selection,
  count enforcement, execution identity, retry state, history exclusion, and
  final ordering remain deterministic for the same captured inputs.
- **Persistence and Configuration**: Requires durable digest configuration,
  execution attempts, outcomes, and per-user delivery history. Count bounds,
  retry limits, freshness windows, and repetition policy are configurable
  within the fixed user-facing rules.
- **Failure Isolation and Testability**: User executions are isolated. Timing,
  ranking, analysis, and delivery boundaries can be replaced with controlled
  test doubles so due schedules, retries, partial news sets, and failures can be
  verified without live external services.

### Key Entities

- **Digest Configuration**: A user's enabled state, selected article count,
  recurring schedule, timezone, last successful execution, and last failure.
- **Scheduled Occurrence**: One expected delivery for one user at a specific
  timezone-aware occurrence, used to prevent duplicate execution.
- **Digest Execution**: A uniquely identified attempt lifecycle for a scheduled
  occurrence, including captured settings, state, selected count, timestamps,
  retries, and outcome.
- **Digest Item**: One ordered selected article with title, summary, source,
  publication time, and URL.
- **Delivery History Entry**: Evidence that an article or story version was
  delivered to a user, including the execution, delivery time, and information
  needed to decide whether a later version is materially new.
- **Execution Failure**: A safe classification and timestamp for an unsuccessful
  attempt, including whether it is transient and retryable.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In acceptance testing, 100% of enabled due users receive no more
  than one digest for each scheduled occurrence in their configured timezone.
- **SC-002**: In acceptance testing, digest sizes of 5 and 20 never produce more
  than 5 and 20 items respectively, and invalid count requests leave the
  previous value unchanged in 100% of cases.
- **SC-003**: When only 3 suitable articles are available for a requested count
  of 10, 100% of tested executions deliver exactly those 3 and no filler.
- **SC-004**: A failure affecting one due user has no effect on the completion
  outcome of any other due user's execution in 100% of isolation tests.
- **SC-005**: Replaying or retrying the same execution any number of times
  results in no more than one completed delivery in 100% of idempotency tests.
- **SC-006**: With 10,000 registered digest configurations and up to 1,000 users
  becoming due in the same scan window, at least 99% of those due occurrences
  are durably claimed within five minutes under healthy database operation.
  “Claimed” means the unique scheduled execution row exists; external ranking,
  model, and delivery completion are not part of this latency target.
- **SC-007**: In a representative history test set, 100% of materially unchanged
  previously delivered articles are excluded unless repetition is explicitly
  permitted, while eligible material updates remain selectable.
- **SC-008**: Every completed non-empty digest contains title, summary, source,
  publication time, and URL for 100% of delivered items.
- **SC-009**: At least 95% of users in usability testing can set a valid digest
  count on their first attempt without additional assistance.

## Assumptions

- Existing user identity, preferences, chosen language, news aggregation,
  analysis, deduplication, event grouping, ranking, diversity, and messaging
  capabilities remain available.
- Initial schedule, timezone, and enabled state can be provisioned through
  existing configuration or operational workflows; new user-facing commands
  for changing these three settings are outside this feature's scope.
- The default digest count for users without a prior selection is 10.
- Shared application-user provisioning is the sole creation path and creates the
  preference profile and disabled-safe digest configuration in the same
  transaction.
- A schedule represents recurring local-time occurrences and only one digest is
  expected for each occurrence.
- Existing news freshness policy defines “recent”; the scheduler does not
  introduce a competing freshness definition.
- A material update requires a later article in the same event plus either
  accepted novelty analysis above policy threshold or a persisted versioned
  comparison showing sufficient normalized-content change. The comparison
  requires bounded non-empty source text and is blocked by duplicate/review
  evidence; simple re-publication, title edits, and source duplication do not
  qualify.
- Direct, on-demand news requests remain separate from scheduled execution and
  may use their existing repetition behavior.
- Automatic retries are bounded and reserved for failures classified as
  transient; exact retry timing is an operational policy decided during
  planning.
- Delivery history is retained for at least as long as an article can remain
  eligible under freshness and repetition policies.
