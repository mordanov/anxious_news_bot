# Feature Specification: User Preference Tuning

**Feature Branch**: `002-user-preference-tuning`  
**Created**: 2026-08-13  
**Status**: Draft  
**Input**: User description: `@requirements/02_preferences_tune.md`

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Tune a Personal News Profile (Priority: P1)

As a user, I want to answer a focused questionnaire so that the news service learns
which characteristics make articles more or less interesting to me.

**Why this priority**: Completing a questionnaire and applying its answers is the
minimum end-to-end capability that delivers personalized preference data.

**Independent Test**: Start `/tune` for a user with no prior profile, answer all
questions, and confirm that exactly 10 valid questions with four options each are
presented and that the resulting validated preference changes are applied only
after the tenth answer.

**Acceptance Scenarios**:

1. **Given** a user starts `/tune`, **When** a questionnaire is generated, **Then**
   the user receives exactly 10 short, concrete, single-dimensional questions with
   exactly four distinct answer options each.
2. **Given** an active questionnaire, **When** the user selects an offered option,
   **Then** the answer is retained and the user can continue to the next unanswered
   question.
3. **Given** nine recorded answers, **When** the user submits the tenth answer,
   **Then** the complete questionnaire is interpreted, validated changes are
   applied deterministically, and the user receives a clear completion outcome.
4. **Given** fewer than 10 recorded answers, **When** the session remains
   incomplete, **Then** no questionnaire-derived preference changes are applied.

---

### User Story 2 - Improve Preferences Over Repeated Sessions (Priority: P2)

As a returning user, I want later questionnaires to build on what the service
already knows so that questions remain useful and my profile becomes more precise
instead of being replaced.

**Why this priority**: Adaptive, incremental tuning is the primary mechanism for
improving personalization quality over time.

**Independent Test**: Complete two `/tune` sessions for the same user and confirm
that the second questionnaire uses the current profile and prior responses,
substantially avoids repeated questions, and normally adjusts or refines existing
parameters rather than replacing the profile.

**Acceptance Scenarios**:

1. **Given** a user has prior questionnaires and active preference parameters,
   **When** a new questionnaire is generated, **Then** relevant prior questions,
   answers, and the current profile inform the new questions.
2. **Given** well-explored and unexplored preference dimensions, **When** a new
   questionnaire is generated, **Then** it favors unexplored dimensions, deeper
   investigation of strong interests, or clarification of ambiguous preferences.
3. **Given** new evidence about an existing interest, **When** changes are applied,
   **Then** the existing parameter is incrementally adjusted or refined instead of
   creating an obvious semantic duplicate.
4. **Given** prior questions, **When** a later questionnaire is generated, **Then**
   it contains no substantially repeated question unless repetition is necessary
   to clarify conflicting or ambiguous evidence.

---

### User Story 3 - Preserve a Valid and Auditable Profile (Priority: P3)

As a user or operator, I want preference updates to be validated, atomic, and
traceable so that failed interpretation cannot corrupt the profile and every
successful change can be explained.

**Why this priority**: Preference data directly controls future ranking, so profile
integrity and accountability are required before the data can be trusted.

**Independent Test**: Submit valid, invalid, duplicate, and out-of-range proposed
changes; confirm valid batches create complete history, while any invalid batch
leaves the prior profile unchanged.

**Acceptance Scenarios**:

1. **Given** a proposed change set containing an invalid action, identifier,
   precision, or weight, **When** validation fails, **Then** none of the proposed
   changes are applied and the previous profile remains unchanged.
2. **Given** a valid proposed change set, **When** it is applied, **Then** every
   changed parameter retains its previous state, new state, source, reason,
   applicable questionnaire, and timestamp.
3. **Given** a proposed new parameter that is obviously equivalent to an existing
   user parameter, **When** the change set is validated, **Then** the duplicate
   creation is rejected in favor of reuse or refinement.
4. **Given** the same validated current profile and proposed changes, **When** the
   update is evaluated repeatedly, **Then** it produces the same resulting profile
   and history semantics.

---

### User Story 4 - Retain Explicit User Authority (Priority: P4)

As a user, I want my directly stated preferences to remain distinguishable from
questionnaire findings so that future personalization can give my explicit intent
the appropriate authority.

**Why this priority**: The tuning flow must integrate with the wider preference
model without erasing the origin or meaning of existing user choices.

**Independent Test**: Tune a profile containing explicit, inferred, system, and
questionnaire-derived parameters and confirm each parameter retains its origin and
that questionnaire updates do not silently relabel explicit preferences.

**Acceptance Scenarios**:

1. **Given** a profile containing preferences from multiple origins, **When** a
   questionnaire-derived update is applied, **Then** every parameter retains an
   allowed and accurate origin.
2. **Given** a specific explicit preference and broader questionnaire evidence,
   **When** the profile is updated, **Then** the specific explicit preference is
   not silently replaced, weakened, or generalized.
3. **Given** a questionnaire proposal targets an explicit, inferred, or system
   parameter, **When** the batch is validated, **Then** the target remains
   unchanged and the entire batch is rejected with a controlled outcome.
4. **Given** questionnaire evidence is semantically equivalent to a protected
   parameter, **When** creation is proposed, **Then** no duplicate is created;
   genuinely distinct, narrower evidence may create a separate
   questionnaire-origin parameter.

### Edge Cases

- A user starts `/tune` while already having an incomplete questionnaire.
- The same answer is delivered more than once because of retry or duplicate input.
- A user submits an option that does not belong to the current question.
- Question generation returns fewer or more than 10 questions, an incorrect option
  count, duplicate options, vague wording, disguised yes/no choices, or
  substantially repeated questions.
- Interpretation proposes an unknown parameter identifier, unsupported action,
  missing reason, invalid origin, or semantically duplicate parameter.
- A proposed adjustment would exceed a weight boundary or use precision finer than
  0.01.
- Interpretation or validation fails after all answers have been collected.
- Two update attempts for the same completed questionnaire occur concurrently.
- A parameter proposed for deactivation is already inactive.
- Prior questionnaire context is large enough that only the most relevant history
  can be considered.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST maintain an independent preference profile for each
  user.
- **FR-002**: Each preference parameter MUST retain a stable identifier, user
  identifier, name, description, evaluation instructions, weight, origin, active
  state, creation time, and last-update time.
- **FR-003**: Parameter origin MUST be one of questionnaire, explicit, inference,
  or system, and updates MUST preserve accurate origin semantics.
- **FR-004**: Parameter weights MUST remain between `-1.00` and `+1.00`, inclusive,
  and MUST use increments of `0.01`.
- **FR-005**: A positive weight MUST represent desirable matching content, zero
  MUST represent neutrality, and a negative weight MUST represent an undesirable
  contribution from matching content rather than interest in an opposite topic.
- **FR-006**: Starting `/tune` MUST create or resume one active questionnaire for
  that user without creating concurrent active questionnaires.
- **FR-007**: Every generated questionnaire MUST contain exactly 10 ordered
  questions, and every question MUST contain exactly four distinct ordered answer
  options.
- **FR-008**: Every question MUST be short, concrete, relevant to news ranking,
  focused on one semantic dimension, non-leading, non-vague, and not a disguised
  yes/no question.
- **FR-009**: The system MUST persist each questionnaire, its questions, all four
  options per question, selected answers, lifecycle state, and relevant
  timestamps.
- **FR-010**: The system MUST accept only an option belonging to the user's current
  unanswered question and MUST handle repeated delivery of the same answer without
  recording it twice or advancing twice.
- **FR-011**: A new questionnaire MUST use relevant prior questions, answers, and
  current preference parameters to adapt its subject matter.
- **FR-012**: Adaptive generation MUST favor unexplored dimensions, deeper
  questions about strong interests, and clarification of ambiguous preferences,
  while avoiding substantial repetition unless needed to resolve ambiguity or
  conflicting evidence.
- **FR-013**: Questionnaire interpretation MUST occur only after exactly 10 valid
  answers have been recorded.
- **FR-014**: Interpretation MAY propose increasing or decreasing an existing
  parameter, creating a parameter, deactivating a parameter, or refining its
  description or evaluation instructions.
- **FR-015**: Questionnaire-derived updates MUST normally modify the current
  profile incrementally rather than replace the full profile.
- **FR-016**: Before a new parameter can be created, its intended meaning MUST be
  compared with the user's existing parameters; an equivalent parameter MUST be
  reused or refined, and obvious duplicates MUST be rejected.
- **FR-017**: Generated-question and interpreted-change results MUST conform to
  defined structures and MUST be validated for required fields, exact question
  and option counts, valid parameter identifiers, allowed actions, allowed
  origins, weight range, weight precision, and semantic uniqueness.
- **FR-018**: Generated or interpreted results MUST NOT directly modify persistent
  preference state.
- **FR-019**: Once a complete proposed change set passes validation, the system
  MUST apply it deterministically against the profile state used for
  interpretation.
- **FR-020**: A proposed change set MUST be applied atomically; failure of any
  validation or application rule MUST leave the entire previous profile unchanged.
- **FR-021**: Every applied parameter change MUST record the previous state, new
  state, source, applicable questionnaire identifier, reason, and timestamp.
- **FR-022**: Reprocessing the same completed questionnaire MUST NOT apply its
  changes more than once.
- **FR-023**: Failures in generation, answer handling, interpretation, validation,
  or application MUST produce a controlled user-visible outcome and sufficient
  diagnostic context without exposing other users' preference data or unnecessary
  answer content.
- **FR-024**: Explicit preferences MUST retain greater semantic authority than
  questionnaire-derived, inferred, or system preferences; questionnaire tuning
  MUST NOT silently overwrite, weaken, generalize, or relabel a specific explicit
  preference.
- **FR-025**: This feature MUST NOT fetch or aggregate news, calculate article
  relevance, rank articles, select digest contents, or schedule digest delivery.
- **FR-026**: Terminal questionnaire details and full preference-change history
  MUST have independently configurable retention periods. Retention cleanup MUST
  process bounded batches, MUST NOT remove active questionnaires or current
  preference parameters, and MUST preserve one immutable compact audit record for
  every applied parameter change after detailed retained data expires. Each compact
  record MUST identify the parameter, action, source, questionnaire and update
  batch, timestamp, and hashes of the previous state, new state, and reason.
- **FR-027**: Questionnaire-derived batches MUST create parameters with
  questionnaire origin and MAY adjust, refine, deactivate, or reactivate only
  questionnaire-origin parameters. Explicit, inference, and system parameters
  MUST be read-only to questionnaire batches. Equivalent protected parameters
  MUST block duplicate creation; only a genuinely distinct semantic dimension may
  create a separate questionnaire-origin parameter.

### Questionnaire Action-by-Origin Policy

| Target origin | Create equivalent | Adjust | Refine | Deactivate | Reactivate |
|---|---|---|---|---|---|
| questionnaire | Reuse existing parameter | Allowed | Allowed | Allowed | Allowed |
| explicit | Reject duplicate | Prohibited | Prohibited | Prohibited | Prohibited |
| inference | Reject duplicate | Prohibited | Prohibited | Prohibited | Prohibited |
| system | Reject duplicate | Prohibited | Prohibited | Prohibited | Prohibited |

All create actions set origin to `questionnaire` in deterministic application code.
A create action is allowed beside a protected parameter only when validation finds
a genuinely distinct, usually narrower, semantic dimension with a distinct
semantic key. Answers remain durable questionnaire evidence even when a protected
target causes the proposed batch to be rejected.

### Constitution Alignment *(mandatory)*

- **Affected Modules**: This feature owns user preference profiles, questionnaires,
  validated preference proposals, deterministic updates, and change history.
  Telegram remains a thin interaction adapter; aggregation, article analysis,
  personal ranking, and digest scheduling remain outside the feature boundary.
- **Personalization Impact**: The feature creates and incrementally improves the
  explicit preference data later consumed by personal ranking. Preference origin
  remains visible, specific explicit intent retains greater semantic authority,
  and no article ranking is performed here.
- **LLM and Determinism**: Probabilistic generation and interpretation may propose
  questions and structured parameter changes, but cannot write persistent state.
  Outputs are structurally and semantically validated before deterministic,
  atomic application. Identical accepted inputs and profile state produce the same
  resulting profile.
- **Persistence and Configuration**: User parameters, origins, questionnaire
  content and answers, application status, and full change history are durable.
  Stored-structure changes require controlled migration. Generation limits,
  relevance of retained history, repetition thresholds, validation constraints,
  terminal-questionnaire retention, full change-history retention, cleanup cadence,
  and cleanup batch size are configurable.
- **Failure Isolation and Testability**: A failure affects only the relevant user's
  tuning attempt and leaves the prior profile intact. Question generation,
  questionnaire validation, interpretation validation, duplicate detection,
  deterministic application, and history creation are testable without Telegram
  or a live probabilistic service.

### Key Entities

- **Preference Profile**: The current collection of preference parameters belonging
  to one user.
- **Preference Parameter**: One specific semantic dimension used by later ranking,
  with descriptive instructions, bounded weight, origin, lifecycle state, and
  timestamps.
- **Questionnaire**: A user-specific tuning session containing exactly 10 ordered
  questions, its lifecycle state, generation context, and timestamps.
- **Question**: One concrete semantic inquiry within a questionnaire, including
  exactly four ordered options.
- **Answer**: The user's selected option for one questionnaire question, including
  its recording time.
- **Preference Change Proposal**: A validated candidate action against the current
  profile, including target, proposed values, and reason, but no authority to
  persist itself.
- **Preference Change History**: The audit record for one applied change, linking
  previous and new state to its source and questionnaire where applicable.
- **Compact Preference Change Audit**: The immutable, indefinitely retained
  per-change identity and hash evidence that remains after full history expires.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of successfully generated `/tune` sessions contain exactly 10
  questions with exactly four distinct options per question.
- **SC-002**: At least 95% of generated questions in a reviewed representative set
  pass all brevity, concreteness, single-dimension, neutrality, relevance, and
  non-yes/no quality checks without manual correction.
- **SC-003**: At least 90% of users in usability testing can complete a `/tune`
  session on their first attempt without operator assistance.
- **SC-004**: At least 95% of completed tuning sessions present their completion
  outcome within 10 seconds after the tenth answer, excluding unavailable external
  analysis time that is communicated to the user.
- **SC-005**: In reviewed consecutive questionnaires for the same representative
  users, at least 90% of later questions are not substantial repetitions of prior
  questions.
- **SC-006**: 100% of applied preference weights remain in `[-1.00, +1.00]` and at
  `0.01` precision.
- **SC-007**: Across all invalid-generation and invalid-update test cases, zero
  invalid questions or parameter changes enter accepted persistent state.
- **SC-008**: Across all failed or concurrently repeated update test cases, the
  previous profile remains complete and no completed questionnaire changes the
  profile more than once.
- **SC-009**: During the configured full-history retention period, 100% of applied
  parameter changes can be reconstructed from retained previous state, new state,
  source, reason, questionnaire reference when applicable, and timestamp. After
  expiry, 100% of applied changes remain individually auditable through the compact
  record required by FR-026.
- **SC-010**: In a reviewed semantic-equivalence test set, at least 95% of obvious
  duplicate parameter proposals are rejected or redirected to reuse/refinement,
  with zero duplicate creations for exact semantic matches.
- **SC-011**: Review of questionnaire-derived updates finds zero silent
  replacement, weakening, generalization, or relabeling of specific explicit
  preferences, and zero mutations of explicit, inference, or system parameters.
- **SC-012**: In all retention tests, 100% of active questionnaires and current
  preference parameters remain unchanged; expired detailed records are removed in
  batches no larger than the configured limit, and every applied parameter change
  retains its immutable compact audit record.

## Assumptions

- A Telegram user identity already maps reliably to one application user.
- Each question accepts one answer from its four options; multi-select and free-text
  answers are outside this feature's initial scope.
- If a user starts `/tune` with an incomplete questionnaire, the existing session
  is resumed rather than discarded automatically.
- Questionnaire-derived changes are applied only as one complete batch after all
  10 answers; partial questionnaires do not alter the profile.
- Question and option wording may use the user's interaction language when known.
- Relevance windows for prior questionnaire context and substantial-repetition
  comparison are configurable and calibrated using representative reviewed data.
- Terminal questionnaire details are retained for 365 days by default. Full
  preference-change history is retained indefinitely by default; operators may set
  a positive retention period when policy permits older details to be removed
  while preserving immutable compact evidence for every individual change.
- Direct preference editing, inferred preference collection from behavior,
  article ranking, digest creation, and preference-history user interfaces are
  outside this feature's initial scope.
- The existing user identity, durable storage, structured diagnostics, and
  controlled migration practices remain available from the base application.
