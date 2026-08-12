# Feature Specification: News Aggregation and Article Analysis

**Feature Branch**: `001-news-aggregation`  
**Created**: 2026-08-12  
**Status**: Draft  
**Input**: User description: `@requirements/01_news_aggregator.md`

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Build a Reliable News Pool (Priority: P1)

As a digest operator, I want enabled news sources collected into one normalized
article pool so that downstream features can use consistent, current news without
depending on each source's format.

**Why this priority**: A reliable normalized pool is the minimum useful output and
the foundation for analysis, ranking, and digest delivery.

**Independent Test**: Configure multiple sources with one unavailable source,
start scheduled collection, and confirm that due sources run repeatedly at their
configured cadence, valid articles from available sources are stored and returned,
and overlapping scheduler ticks do not create a second active cycle.

**Acceptance Scenarios**:

1. **Given** enabled sources in the World, Russia, and Spain groups, **When** a
   collection cycle succeeds, **Then** valid source records are normalized,
   validated, stored, and reported as newly available articles.
2. **Given** one unavailable source and at least one available source, **When** a
   collection cycle runs, **Then** the failed source is recorded and the available
   sources are still processed.
3. **Given** a source record missing a required article field, **When** it is
   processed, **Then** that record is rejected without stopping other records or
   sources.
4. **Given** a collection cycle is already running, **When** another scheduled tick
   occurs, **Then** the tick records an already-running outcome and does not start
   an overlapping cycle.
5. **Given** enabled sources with different polling intervals, **When** the
   scheduler ticks, **Then** only sources due at that time are processed and each
   due source is attempted within one scheduler interval.

---

### User Story 2 - Consolidate Duplicate Coverage (Priority: P2)

As a digest curator, I want repeated and overlapping coverage consolidated so that
the article pool does not present the same URL or news event as unrelated stories.

**Why this priority**: Duplicate control is necessary for a useful pool and prevents
downstream digests from being dominated by repeated coverage.

**Independent Test**: Submit articles containing an identical canonical URL,
near-identical text, and distinct-source reports of the same event; confirm exact
duplicates are stored once and event-related stories are grouped while their
source links remain available. Event grouping uses the same deterministic policy
and configuration for every run and does not require enrichment.

**Acceptance Scenarios**:

1. **Given** two records with the same canonical URL, **When** both are processed,
   **Then** only one normalized article exists for that canonical URL.
2. **Given** articles with near-identical titles or content, **When** they are
   processed, **Then** they are recognized as duplicate coverage according to the
   configured threshold.
3. **Given** distinct source reports about the same underlying event, **When** they
   are within the configured 48-hour candidate window and meet the configured
   evidence threshold, **Then** they share an event group and retain their
   individual source URLs.
4. **Given** an event candidate whose evidence falls in the configured review band,
   **When** it is processed, **Then** it remains a separate article with a
   reviewable proposed-group decision rather than being merged automatically.

---

### User Story 3 - Enrich Articles for Later Ranking (Priority: P3)

As the future personal ranking system, I want general article metadata and a
separate importance assessment so that I can combine news characteristics with
user preferences later without repeating article analysis.

**Why this priority**: Enrichment enables future ranking but is not required to
establish the initial normalized pool.

**Independent Test**: Process representative articles and confirm that validated
topics, locations, entities, event type, importance, novelty, and source quality
are available without any user-specific data or decisions.

**Acceptance Scenarios**:

1. **Given** a valid normalized article, **When** analysis succeeds, **Then** its
   validated general metadata and importance are stored separately from personal
   interest.
2. **Given** partial analysis failure, **When** the article has already passed
   normalization and validation, **Then** the article remains available with its
   successful analysis fields and an explicit incomplete-analysis status.
3. **Given** invalid structured analysis output, **When** it is validated, **Then**
   the invalid fields are rejected and do not overwrite valid article data.

---

### User Story 4 - Extend Source Coverage (Priority: P4)

As a digest operator, I want to add, disable, or adjust sources and regions without
changing aggregation rules so that coverage can evolve operationally.

**Why this priority**: Extensibility supports growth after the core pipeline is
reliable.

**Independent Test**: Validate and transactionally import a source-catalog file
that adds a supported source in a new region, updates an existing source, and
disables another; run collection and confirm only enabled due sources enter the
common pool without changing article definitions or aggregation rules.

**Acceptance Scenarios**:

1. **Given** a newly configured supported source and region, **When** the source is
   enabled, **Then** its valid articles enter the normalized pool.
2. **Given** a disabled source, **When** a collection cycle runs, **Then** the
   source is not contacted or processed.
3. **Given** a valid versioned source-catalog file, **When** an operator performs a
   dry run, **Then** all proposed additions and updates are reported without
   changing stored sources.
4. **Given** a valid versioned source-catalog file, **When** an operator applies it,
   **Then** all listed sources are added or updated in one transaction while
   omitted sources remain unchanged.
5. **Given** any invalid or duplicate source entry, **When** an operator validates
   or applies the catalog, **Then** the command reports actionable validation
   errors and no source changes are committed.

### Edge Cases

- A source returns no records, times out, or returns only malformed records.
- A source returns the same article repeatedly across collection cycles.
- Canonical URLs differ only by tracking parameters, casing, or harmless URL
  variations.
- Publication time is absent, invalid, in the future, or expressed in a different
  time zone.
- Article language or geographic relevance cannot be determined.
- Near-duplicate evidence is inconclusive and must not merge unrelated stories.
- Event-group analysis later changes as more source coverage arrives.
- Enrichment returns unknown categories, out-of-range scores, or only some fields.
- A collection cycle is retried after partial completion.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST support configurable news sources initially grouped
  as World, Russia, and Spain.
- **FR-002**: Each source MUST retain a stable identifier, name, source type,
  location, country or region, language, enabled state, quality metadata, and
  polling configuration.
- **FR-003**: A collection cycle MUST process every enabled source independently and
  MUST NOT process disabled sources.
- **FR-004**: The system MUST convert supported source records into a common article
  representation containing a stable identifier, title, summary, canonical URL,
  source, publication and ingestion times, language, normalized text, geographic
  relevance, topic metadata, and an event-group reference when applicable.
- **FR-005**: The system MUST retain original source data when needed to diagnose
  normalization, validation, or analysis outcomes.
- **FR-006**: The system MUST validate required article data and reject malformed
  records without stopping other records or sources.
- **FR-007**: The system MUST store valid normalized articles and identify which
  articles became newly available during each collection cycle.
- **FR-008**: Reprocessing the same source record or retrying a partially completed
  cycle MUST NOT create duplicate normalized articles.
- **FR-009**: The system MUST prevent more than one normalized article from being
  stored for the same canonical URL.
- **FR-010**: The system MUST identify near-duplicate title or content according to
  configurable comparison thresholds.
- **FR-011**: The system MUST support grouping distinct-source articles that
  represent the same underlying event while retaining every source URL. The
  initial policy MUST be deterministic and provider-independent: compare only
  same-language reports within a configurable 48-hour publication-time window;
  calculate `0.50 × title similarity + 0.30 × content similarity + 0.10 × topic
  overlap + 0.10 × geographic overlap`; require either shared topic/geography or
  title similarity of at least `0.55`; assign the same event at a score of at least
  `0.62`, propose review from `0.52` through `0.6199`, and otherwise keep reports
  distinct. Missing publication time MUST use ingestion time. All values MUST be
  configurable and recorded with the decision.
- **FR-012**: Duplicate and event-group decisions MUST retain enough evidence to be
  reviewed and corrected.
- **FR-013**: The system MUST enrich eligible articles with validated structured
  topics, countries, cities or locations, people, organizations, event type,
  importance, novelty, source quality, and semantic metadata when available.
- **FR-014**: Importance MUST remain independent from personal interest and MUST be
  stored as general article-level metadata.
- **FR-015**: Invalid analysis output MUST NOT directly modify stored article data;
  only fields that satisfy the expected structure and constraints may be applied.
- **FR-016**: Partial enrichment failure MUST preserve the valid normalized article,
  successful enrichment fields, and an explicit record of incomplete analysis.
- **FR-017**: Failure of one source MUST be observable and MUST NOT prevent other
  enabled sources from completing their work.
- **FR-018**: The system MUST allow supported sources and regions to be added or
  reconfigured without changing the common article definition or aggregation
  rules. Operators MUST manage sources through a versioned JSON catalog contract
  with validation-only and transactional apply modes. Apply MUST upsert listed
  sources by stable identifier, leave omitted sources unchanged, support explicit
  enable/disable updates, reject the entire catalog on any invalid or duplicate
  entry, and report a sanitized add/update/unchanged summary.
- **FR-019**: Source retrieval, record conversion, duplicate detection, enrichment,
  and cycle coordination MUST be independently replaceable capabilities.
- **FR-020**: The aggregation feature MUST NOT load user preference profiles,
  determine personal interest, rank articles for a user, or modify preference
  weights.
- **FR-021**: Collection and analysis outcomes MUST record source, article, stage,
  status, and diagnostic context without exposing secrets or unnecessary source
  payload data.
- **FR-022**: The application MUST schedule aggregation at a configurable scan
  interval, process only sources whose individual polling interval is due, and
  attempt each due source within one scan interval. Application startup and
  shutdown MUST start and stop scheduling outside Telegram message handlers.
- **FR-023**: A PostgreSQL advisory lock MUST prevent overlapping collection
  cycles. A tick that cannot acquire the lock MUST return and record an
  `already_running` outcome without starting source work.

### Constitution Alignment *(mandatory)*

- **Affected Modules**: This feature defines the News Aggregator and Article
  Analysis responsibilities. Telegram and future Personal Ranking behavior remain
  outside the feature boundary.
- **Personalization Impact**: The output is a general article pool. No user
  preferences are loaded or changed, and no personalized relevance is calculated.
- **LLM and Determinism**: Semantic enrichment may use probabilistic analysis, but
  all output is structured and validated before application. Normalization,
  required-field validation, canonical URL uniqueness, and storage outcomes are
  deterministic for identical inputs and configuration.
- **Persistence and Configuration**: Sources, normalized articles, retained source
  data, analysis, event groups, and processing outcomes are durable. Source
  settings, polling behavior, duplicate thresholds, and analysis limits are
  configurable and changes to stored structures require controlled migration.
- **Failure Isolation and Testability**: Source and record failures are isolated.
  Retrieval, normalization, duplicate detection, enrichment, and coordination can
  be tested without live sources or live semantic-analysis services.

### Key Entities

- **News Source**: A configurable origin of news, including identity, source type,
  location, regional and language coverage, enabled state, quality metadata, and
  polling behavior.
- **Normalized Article**: The common, validated representation of a source article,
  including content, canonical identity, provenance, timing, language, geography,
  topics, and optional event membership.
- **Article Analysis**: Structured general metadata derived for an article,
  including entities, event type, importance, novelty, source quality, completion
  state, and validation outcome.
- **Event Group**: A set of source articles believed to describe the same underlying
  event, including membership and evidence supporting the grouping.
- **Collection Cycle**: One aggregation run, recording source-level and
  article-level outcomes and the articles newly made available.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In a collection cycle where at least one source succeeds, 100% of
  valid records from successful sources are processed even when another source is
  unavailable.
- **SC-002**: Repeating an identical collection cycle produces zero additional
  stored articles for already processed canonical URLs.
- **SC-003**: In a reviewed duplicate test set, at least 95% of exact and
  near-duplicate pairs are correctly consolidated, while at least 99% of unrelated
  pairs remain separate.
- **SC-004**: 100% of stored articles contain all required normalized fields and
  traceable source provenance.
- **SC-005**: 100% of invalid or partial analysis results leave the normalized
  article available and do not place unvalidated values into accepted metadata.
- **SC-006**: Operators can add and enable a supported source in a new region
  without changing the common article definition or aggregation rules.
- **SC-007**: Auditors can explain every rejection, duplicate decision, event-group
  assignment, and incomplete analysis result using retained processing evidence.
- **SC-008**: Review of aggregation outputs finds zero use of user preference data
  and zero user-specific ranking decisions.
- **SC-009**: At least 95% of successful collection cycles make their newly
  available article set ready for downstream use within 10 minutes of receiving
  the final source response.
- **SC-010**: 100% of due enabled sources are attempted within one configured
  scheduler scan interval, and concurrent scheduler ticks produce no overlapping
  collection cycles.
- **SC-011**: For a valid source catalog, operators can preview and apply add,
  update, enable, and disable changes in one command; for an invalid catalog, zero
  source records are changed.

## Assumptions

- Initial source coverage includes World, Russia, and Spain, but the exact source
  catalog and source-specific credentials are operational configuration.
- Only sources whose formats are supported by an available source capability are
  accepted; adding an entirely new format may require a new replaceable capability
  but does not change aggregation rules or the common article definition.
- Canonical URL identity is established after removing recognized tracking and
  non-content URL variations.
- Duplicate thresholds and semantic analysis limits are configurable and will be
  calibrated against a reviewed representative news set.
- When enrichment is incomplete, downstream consumers can distinguish missing,
  rejected, and successfully produced metadata.
- Personal ranking, digest representative selection, Telegram presentation, and
  user preference management are outside this feature's scope.
