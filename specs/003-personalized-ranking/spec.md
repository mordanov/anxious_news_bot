# Feature Specification: Explicit Preferences and Personalized Ranking

**Feature Branch**: `003-personalized-ranking`  
**Created**: 2026-08-13  
**Status**: Draft  
**Input**: User description: `@requirements/03_ranking_and_specify.md`

## User Scenarios & Testing *(mandatory)*

### User Story 1 - State an Explicit Preference (Priority: P1)

A user sends `/specify` followed by a free-form statement describing news they
want more or less of. The system interprets the statement against the user's
current profile and relevant history, proposes an incremental change, validates
it, and applies it as explicit user intent. Specific intent remains specific:
requesting news about Kirov creates or strengthens a Kirov preference rather than
merely increasing a broad Russia preference.

**Why this priority**: Directly expressed intent has the greatest authority and is
the clearest way for a user to improve personalization.

**Independent Test**: Submit a specific preference statement to a profile
containing broad, related, equivalent, and questionnaire-derived parameters.
Verify that exactly one valid incremental update is applied, the most specific
equivalent parameter is reused when appropriate, its origin reflects explicit
intent, and a complete audit record is created.

**Acceptance Scenarios**:

1. **Given** a user with no equivalent preference, **When** the user specifies a
   concrete local-news interest, **Then** a specific active explicit parameter is
   created with a bounded weight and an auditable reason.
2. **Given** an equivalent existing parameter, **When** the user expresses
   stronger interest in it, **Then** that parameter is reused and strengthened
   rather than duplicated.
3. **Given** a broad preference and a narrower explicit request, **When** the
   request is applied, **Then** the narrower intent is represented separately or
   by refining the appropriate parameter without collapsing it into the broad
   category.
4. **Given** a valid existing profile, **When** interpretation or validation of a
   `/specify` request fails, **Then** the profile remains unchanged and the user
   receives a controlled failure outcome.

---

### User Story 2 - Evaluate Articles Against Preferences (Priority: P2)

For each candidate article, the system evaluates its semantic relationship to
each active preference parameter for a user. Every relationship receives a
bounded score from strong contradiction through neutrality to strong relevance.
Only complete, validated evaluations become eligible for ranking.

**Why this priority**: Personalized ranking cannot faithfully represent user
intent without a reliable article-to-preference signal.

**Independent Test**: Evaluate representative matching, unrelated, and
contradictory articles against positive, negative, and zero-weight preferences.
Verify valid bounded scores are retained, malformed results are rejected, and
previous valid evaluations survive a failed reevaluation.

**Acceptance Scenarios**:

1. **Given** an active preference and clearly matching content, **When** the
   article is evaluated, **Then** the relevance score is positive.
2. **Given** an active preference and content that strongly contradicts it,
   **When** the article is evaluated, **Then** the relevance score is negative.
3. **Given** malformed or incomplete evaluation output, **When** validation
   fails after configured attempts, **Then** the evaluation is marked incomplete,
   previous valid evidence remains intact, and later reprocessing is possible.
4. **Given** two users with different profiles, **When** the same article is
   evaluated, **Then** each user's evidence is isolated and refers only to that
   user's active parameters.

---

### User Story 3 - Receive Deterministic Explainable Ranking (Priority: P3)

A user receives articles ordered by a deterministic score that combines personal
preference contributions with normalized generic factors such as importance,
freshness, source quality, and novelty. The personal score remains conceptually
separate from generic importance, and every ranked result can explain how its
score was formed.

**Why this priority**: This converts preference and article evidence into the
product's core user value while preserving trust and debuggability.

**Independent Test**: Rank a fixed article set twice with identical preferences,
evaluations, generic factors, and configuration. Verify byte-for-byte equivalent
ordering and explanations, correct positive, negative, and zero contributions,
and a stable tie resolution.

**Acceptance Scenarios**:

1. **Given** a positive-weight preference and positive relevance, **When** the
   personal score is calculated, **Then** the contribution is positive.
2. **Given** a negative-weight preference and positive relevance, **When** the
   personal score is calculated, **Then** the contribution is negative.
3. **Given** a zero-weight preference, **When** ranking is calculated, **Then**
   its contribution is exactly zero regardless of relevance.
4. **Given** identical inputs and configuration, **When** ranking is repeated,
   **Then** article order, factor scores, contributions, and final scores are
   identical.
5. **Given** a ranked article, **When** its explanation is inspected, **Then** it
   identifies the personal score, normalized generic factors, top contributing
   parameters, each displayed weight and relevance score, each contribution, and
   the final score.

---

### User Story 4 - Preserve Quality and Diversity (Priority: P4)

After scoring, the system selects a varied set that avoids repeated
representatives of one event and excessive concentration from one topic or source.
Very low-quality, obsolete, or duplicate content may be filtered regardless of
preference, while diversity does not silently suppress exceptionally strong
explicit intent.

**Why this priority**: A ranked list that is mathematically relevant but repetitive
or low quality is not useful to the user.

**Independent Test**: Select from a scored pool containing event duplicates,
single-topic and single-source clusters, low-quality items, and articles strongly
matching explicit preferences. Verify configured quality filters and diversity
limits apply deterministically and every displacement is explainable.

**Acceptance Scenarios**:

1. **Given** multiple representatives of the same event, **When** diversity is
   applied, **Then** the configured event-representation limit is respected.
2. **Given** a result set concentrated on one topic or source, **When** enough
   suitable alternatives exist, **Then** configured concentration limits are
   respected.
3. **Given** an article with exceptionally strong explicit relevance, **When**
   diversity would otherwise displace it, **Then** it remains selected unless a
   configured and recorded override reason applies.
4. **Given** an obsolete, duplicate, or very low-quality article, **When** minimum
   eligibility rules reject it, **Then** personal relevance does not force it
   into the selected results.

### Edge Cases

- `/specify` contains no text, only whitespace, unsupported content, or exceeds
  the accepted input length.
- An explicit request conflicts with an existing explicit preference or asks to
  weaken, deactivate, broaden, or narrow prior intent.
- The same explicit request is repeated or submitted concurrently.
- A proposed new preference is an exact, lexical, or semantic duplicate of an
  active or inactive parameter.
- A profile changes after interpretation but before the proposed update is
  applied.
- An article has no active preference evaluations, no generic analysis, or only
  incomplete evaluation evidence.
- Relevance is exactly `-1`, `0`, or `+1`; a preference weight is exactly its
  lower bound, zero, or upper bound.
- Personal contributions cancel to zero, generic factors tie, or several
  articles receive the same final score.
- Freshness inputs are in the future, missing, or beyond the configured obsolete
  threshold.
- The candidate pool cannot satisfy every diversity limit or contains only one
  event, topic, or source.
- Configuration is invalid, coefficients do not form an accepted combination, or
  a ranking configuration changes while a run is in progress.
- Reevaluation fails after a previous valid result exists, or ranking is retried
  after a partial prior attempt.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST accept `/specify` followed by a non-empty free-form
  explicit preference statement associated with the requesting user.
- **FR-002**: The system MUST reject missing, blank, and over-limit statements
  without changing the user's profile and MUST provide a controlled user-visible
  outcome.
- **FR-003**: Interpretation of an explicit statement MUST consider the statement,
  the user's current preference parameters, and bounded relevant preference
  history.
- **FR-004**: Interpretation MAY propose strengthening, weakening, creating,
  deactivating, reactivating, or refining a preference parameter, but MUST NOT
  directly modify persistent state.
- **FR-005**: Every proposal MUST use a defined structure and pass validation for
  target ownership, supported action, origin authority, semantic specificity,
  weight range and precision, required reason, and profile version before it can
  be applied.
- **FR-006**: Before creating a parameter, the system MUST compare the proposed
  meaning with the user's active and inactive parameters; an equivalent parameter
  MUST be reused, refined, or reactivated rather than duplicated.
- **FR-007**: Specific explicit intent MUST create, strengthen, refine, or
  reactivate the corresponding specific preference and MUST NOT be represented
  only by changing a broader category.
- **FR-008**: An accepted `/specify` update MUST assign explicit authority to the
  resulting evidence. When a non-explicit parameter is reused, the resulting
  parameter MUST reflect that the user has now stated the intent explicitly.
- **FR-009**: Explicit updates MAY modify or supersede questionnaire-derived,
  inferred, or system preferences when semantically appropriate, but MUST NOT
  silently weaken, broaden, deactivate, or relabel unrelated explicit preferences.
- **FR-010**: A valid proposal MUST be applied incrementally, deterministically,
  atomically, and against the same profile version used for interpretation.
- **FR-011**: Repeated or concurrent processing of the same accepted explicit
  request MUST NOT apply the same profile change more than once.
- **FR-012**: Every applied explicit change MUST record the previous state, new
  state, action, explicit source, user request reference, reason, and timestamp,
  while preserving the project's immutable compact per-change audit evidence.
- **FR-013**: For every article eligible for personalization and every active
  parameter in the target user's profile, the system MUST support a semantic
  relevance score in the inclusive range `[-1, +1]`.
- **FR-014**: A relevance score of `+1` MUST represent a very strong match, `0`
  MUST represent unrelated or neutral content, and `-1` MUST represent strong
  contradiction.
- **FR-015**: Article evaluation results MUST use a defined structure and be
  validated for article identity, user and parameter ownership, active parameter
  version, completeness, numeric range and precision, and evaluation version
  before acceptance.
- **FR-016**: Accepted article evaluations MUST preserve enough identity and
  version information to determine which article analysis and preference state
  produced them.
- **FR-017**: Evaluation failure MUST be retried according to configuration;
  after exhaustion it MUST be marked incomplete, MUST NOT replace previous valid
  evidence with invalid data, MUST affect only the relevant article-user
  evaluation, and MUST allow later reprocessing.
- **FR-018**: The personal preference score MUST be calculated from the sum of
  each active preference weight multiplied by that parameter's accepted article
  relevance score.
- **FR-019**: Personal score normalization, when applied, MUST be deterministic,
  bounded to a documented predictable range, and MUST preserve score ordering for
  otherwise identical inputs.
- **FR-020**: The final score MUST combine separately normalized personal
  relevance, article importance, freshness, source quality, and novelty or
  duplicate-penalty factors using a versioned set of configurable coefficients.
- **FR-021**: Personal relevance MUST remain a separately visible factor and
  generic importance MUST NOT automatically dominate it under valid
  configuration.
- **FR-022**: The system MUST define configurable minimum eligibility rules that
  may exclude very low-quality, obsolete, or duplicate articles regardless of
  personal relevance.
- **FR-023**: Ranking MUST be deterministic: identical accepted evaluations,
  profile state, candidate articles, factor inputs, and configuration MUST produce
  identical scores, explanations, selection, ordering, and tie resolution.
- **FR-024**: Ranking MUST use only accepted evidence and MUST define controlled,
  deterministic behavior for missing or incomplete optional factors without
  treating unavailable evidence as a successful evaluation.
- **FR-025**: Each ranking record MUST identify the user, article, ranking
  configuration version, input versions, personal score, each normalized generic
  factor, final score, eligibility outcome, and deterministic position or
  exclusion reason.
- **FR-026**: Each ranking explanation MUST include the top contributing
  parameters and, for each displayed parameter, its identifier, origin, weight,
  relevance score, signed contribution, and explanation ordering.
- **FR-027**: After scoring, the system MUST apply deterministic,
  configuration-driven limits for representatives of one event and concentration
  by topic and source.
- **FR-028**: Diversity selection MUST NOT displace content with exceptionally
  strong explicit relevance unless a configured eligibility or diversity
  override applies; every such displacement MUST retain an explainable reason.
- **FR-029**: When the candidate pool cannot satisfy every diversity limit, the
  system MUST return the best deterministic eligible selection available and
  record which limits could not be satisfied.
- **FR-030**: Ranking coefficients, factor normalization rules, eligibility
  thresholds, freshness behavior, evaluation retry limits, diversity limits,
  explicit-preference protection thresholds, contribution display limits, and
  tie-breaking policy MUST be configurable and validated before use.
- **FR-031**: Invalid ranking configuration MUST prevent a new ranking run from
  being accepted and MUST NOT corrupt previously valid ranking or preference data.
- **FR-032**: Failures for one user's explicit update, evaluation, or ranking MUST
  NOT prevent other users' independent work from completing.
- **FR-033**: Diagnostic records MUST identify stage, status, relevant safe
  identifiers, versions, bounded counts, and error categories without exposing
  credentials or unnecessary user statement, profile, or article content.
- **FR-034**: This feature MUST consume normalized and analyzed articles from the
  general news pool and MUST NOT fetch, poll, normalize, or aggregate news.
- **FR-035**: This feature MUST NOT schedule or deliver digests; it MUST provide
  ranked, diversified, explainable results for a separate delivery capability.
- **FR-036**: Retention of detailed evaluation and ranking explanation evidence
  MUST be configurable while preserving sufficient durable identity, version,
  score, and audit evidence to explain every retained delivered ranking reference.

### Constitution Alignment *(mandatory)*

- **Affected Modules**: User preferences owns `/specify` interpretation and
  deterministic profile updates; personal ranking owns user-specific semantic
  article-to-parameter evaluation, scoring, explanations, and diversity
  selection. Telegram remains a thin command adapter. News aggregation and
  generic article analysis provide only the general article pool and generic
  evidence, and digest delivery consumes ranking output without controlling
  ranking logic.
- **Personalization Impact**: Explicit statements have the highest semantic
  authority. Specific intent remains specific, equivalent parameters are reused,
  and ranking combines signed parameter contributions without allowing generic
  importance to erase personal relevance.
- **LLM and Determinism**: Probabilistic interpretation and semantic evaluation may
  propose structured data only. All outputs are validated before persistence.
  Profile application, score mathematics, normalization, filtering, diversity,
  ties, and final ordering are deterministic and versioned.
- **Persistence and Configuration**: Explicit requests, validated update batches,
  preference history, article evaluation evidence, ranking inputs, factor scores,
  explanations, exclusions, configuration versions, and compact audit evidence
  are durable where needed for reconstruction. Structure changes require
  controlled migration, and all coefficients, thresholds, limits, retries,
  freshness rules, and retention periods are configurable.
- **Failure Isolation and Testability**: A failed interpretation leaves the prior
  profile unchanged; a failed evaluation preserves prior valid evidence and can be
  retried; a failed user ranking does not affect others. Preference policy,
  validation, ranking mathematics, normalization, explanations, filtering,
  diversity, and determinism are testable without Telegram, network access, or a
  live probabilistic service.

### Key Entities

- **Explicit Preference Request**: One user's free-form statement, its lifecycle,
  profile version, interpretation outcome, idempotency identity, and timestamps.
- **Preference Change Proposal**: A structured but untrusted set of incremental
  actions derived from an explicit request, including targets, proposed values,
  reasons, and expected profile version.
- **Preference Parameter**: A user-owned semantic ranking dimension with stable
  identity, description, evaluation instructions, bounded weight, immutable
  origin evidence, active state, and timestamps.
- **Preference Change History**: Full before-and-after evidence for an applied
  explicit update, linked to its request and update batch.
- **Article Preference Evaluation**: Versioned evidence connecting one article,
  one user, and one active parameter to a bounded semantic relevance score and
  validation status.
- **Ranking Configuration**: A versioned, validated set of coefficients,
  normalization rules, eligibility thresholds, freshness behavior, diversity
  limits, explanation limits, and deterministic tie policy.
- **Article Ranking Record**: One user's deterministic score and eligibility
  outcome for one article under a specific profile, analysis, and configuration
  version.
- **Parameter Contribution**: The weight, relevance, signed contribution, origin,
  and display order of one parameter within an article's personal score.
- **Diversity Selection Record**: The final position or exclusion of a ranked
  article plus event, topic, source, eligibility, and override reasons.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In 100% of valid `/specify` acceptance cases, a specific explicit
  statement creates, strengthens, refines, or reactivates the corresponding
  specific preference rather than changing only a broader category.
- **SC-002**: In a reviewed equivalence set, at least 95% of semantically duplicate
  explicit requests reuse, refine, or reactivate an existing parameter, with zero
  duplicate creations for exact semantic matches.
- **SC-003**: Across invalid, stale, repeated, concurrent, and failed explicit
  update tests, 100% leave the prior profile complete and no accepted request
  changes the profile more than once.
- **SC-004**: In a reviewed article-evaluation set, at least 95% of clear matches,
  neutral examples, and clear contradictions receive the expected score direction,
  and 100% of accepted scores remain within `[-1, +1]`.
- **SC-005**: Across malformed and failed article-evaluation tests, zero invalid
  evidence enters accepted state, 100% of prior valid evidence remains intact, and
  every exhausted failure remains eligible for later reprocessing.
- **SC-006**: For 100% of mathematical test cases, positive preferences produce
  positive contributions for matching content, negative preferences produce
  negative contributions for matching content, and zero-weight preferences
  contribute exactly zero.
- **SC-007**: Repeating ranking and diversity selection 100 times with identical
  inputs produces identical scores, explanations, exclusions, ordering, and tie
  resolution in every run.
- **SC-008**: For 100% of retained ranking records, reviewers can reconstruct the
  final score from the personal contribution total, normalized generic factors,
  coefficients, eligibility rules, configuration version, and recorded diversity
  decisions.
- **SC-009**: In at least 95% of representative candidate sets with sufficient
  alternatives, selected results satisfy all configured event, topic, and source
  diversity limits.
- **SC-010**: In 100% of explicit-priority selection tests, exceptionally strong
  explicit relevance survives diversity unless a configured override applies,
  and every override has a recorded reason.
- **SC-011**: At least 95% of eligible ranking runs over a representative
  configured candidate set complete within 5 seconds after all required article
  evidence is available.
- **SC-012**: In usability review, at least 90% of users can state an explicit
  preference with `/specify` and correctly understand whether it was accepted on
  their first attempt.
- **SC-013**: Review of module-boundary tests finds zero news-fetch operations
  initiated by explicit preference, evaluation, ranking, or diversity workflows.
- **SC-014**: Across multi-user failure tests, 100% of unaffected users' explicit
  updates and rankings complete independently.

## Assumptions

- Telegram identity already maps reliably to one application user and the existing
  preference profile is the authoritative user-specific input.
- Existing preference weights use the established inclusive `[-1.00, +1.00]`
  range and `0.01` precision.
- Explicit preference origin is durable evidence of user authority. If an existing
  non-explicit parameter becomes the target of a valid explicit statement, the
  resulting state preserves provenance while reflecting explicit authority.
- Explicit statements are interpreted as preference changes, not one-time search
  queries or requests to fetch an article immediately.
- Relevant preference history is bounded and retained according to existing
  preference audit policy.
- Articles have already been fetched, normalized, deduplicated, grouped, and
  generically analyzed before this feature considers them.
- Generic importance, freshness, source quality, and novelty inputs are supplied
  by existing or separately planned analysis capabilities; this feature validates
  and combines them but does not fetch source data.
- Missing optional ranking factors use an explicit configured neutral or exclusion
  policy; they are never silently treated as successfully analyzed values.
- Selection size and digest delivery cadence belong to the separate digest
  capability. This feature ranks and diversifies a supplied candidate pool.
- A stable final tie policy is required; the exact policy is configuration-driven
  and documented during planning.
- Detailed evaluation and ranking evidence may expire according to configuration,
  but retained delivery references remain explainable through durable compact
  identity, version, factor, and score evidence.
