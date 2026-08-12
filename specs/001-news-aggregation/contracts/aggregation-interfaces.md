# Contract: News Aggregation Interfaces

These application contracts define behavior, not infrastructure. Implementations
may be replaced without changing the coordinator or domain values.

## Shared values

### RawArticle

Contains source identity, optional external identity, original URL, title, summary
or content, optional publication time, optional language, and bounded original
payload. It is not trusted or persistent article state.

### NormalizedArticleCandidate

Contains validated title, summary, canonical and original URLs, UTC publication and
ingestion times, language, normalized text, geographic metadata, topic metadata,
source provenance, canonicalization version, and payload hash.

### NewlyAvailableArticles

Contains collection-cycle identity and only article identities created during that
cycle. Existing exact duplicates are not returned as new.

## NewsSource / NewsFetcher

`fetch(source, conditional_headers) -> FetchResult`

- MUST fetch only the supplied source.
- MUST use configured timeout and retry policy.
- MUST return response records plus new ETag/Last-Modified values, a not-modified
  outcome, or a typed source failure.
- MUST NOT persist records or process another source.
- Cancellation MUST propagate; expected source failures MUST be classifiable.

## ArticleNormalizer

`normalize(source, raw_article, observed_at) -> NormalizationResult`

- MUST be deterministic for identical input, time, and policy configuration.
- MUST canonicalize URLs with a versioned policy and validate required fields.
- MUST return a candidate or typed rejection with sanitized diagnostic context.
- MUST NOT access user data, persistence, network services, or enrichment.

## ArticleDeduplicator

`classify(candidate, candidates) -> DeduplicationResult`

- MUST identify exact canonical identity before near-duplicate comparison.
- MUST use versioned normalized values and configured thresholds.
- MUST distinguish `duplicate`, `review`, and `distinct`.
- MUST include scores, thresholds, algorithm version, and bounded evidence.
- MUST NOT decide personal relevance.

`group_event(article, candidates) -> EventGroupingResult`

- MUST remain separate from textual duplicate classification.
- MUST consider only distinct-source, same-language candidates in the configured
  time window, falling back from publication time to ingestion time.
- MUST calculate the configured weighted title, content, topic-overlap, and
  geographic-overlap score and enforce the configured anchor condition.
- MUST distinguish automatic assignment, review proposal, and distinct outcomes.
- MUST NOT require enrichment or an external semantic provider.
- MUST retain evidence for group assignment or reassignment.

## ArticleEnricher

`enrich(article) -> EnrichmentResult`

- MAY return complete, partial, invalid, or failed outcomes.
- MUST return data conforming to
  [enrichment-result.schema.json](enrichment-result.schema.json).
- MUST NOT persist data or mutate the supplied article.
- MUST NOT receive user profiles or preference state.

The application validates the result again at the boundary and maps only validated
sections into ArticleAnalysis.

## NewsRepository

The repository contract provides:

- list enabled sources due for polling;
- create and finalize collection cycles and source runs;
- update conditional-fetch metadata;
- record accepted, rejected, and duplicate source records;
- atomically insert or resolve an article by canonical URL;
- retrieve bounded near-duplicate candidates;
- record deduplication decisions and event-group changes;
- store validated analysis versions;
- return article identities created by a cycle.

Every source unit of work MUST use an independent transaction. Canonical URL
uniqueness and source-record idempotency MUST be database-enforced.

## NewsAggregator

`run_cycle() -> AggregationResult`

1. Acquire the configured cycle lock or return `already_running`.
2. Create a CollectionCycle.
3. Load enabled, due sources.
4. Process sources concurrently under the configured limit.
5. For each source, fetch, parse, normalize, validate, deduplicate, persist, and
   optionally enrich each accepted article in an isolated unit of work.
6. Record every source outcome without allowing expected failure to cancel siblings.
7. Finalize the cycle as completed, completed with errors, or failed.
8. Return only articles created during the cycle.

The coordinator MUST NOT import Telegram handlers, Personal Ranking, user
preferences, or a concrete LLM provider.

## AggregationScheduler

`start()` registers one repeating application job at the configured scan interval;
`stop()` removes it during graceful shutdown.

- Each tick MUST invoke only `NewsAggregator.run_cycle()`.
- The scheduler MUST NOT contain fetching, normalization, persistence, enrichment,
  or Telegram message-handler logic.
- An `already_running` result is a normal observable outcome and MUST NOT be retried
  inside the same tick.
- Due-source selection remains the repository/coordinator's responsibility.

## SourceCatalogService

`validate(catalog) -> CatalogValidationResult` validates the complete document
against [source-catalog.schema.json](source-catalog.schema.json), supported adapter
types, duplicate identifiers, endpoint conflicts, and domain constraints without
writing.

`apply(catalog) -> CatalogApplyResult` repeats validation and atomically upserts all
listed sources by stable identifier. Omitted sources remain unchanged. The result
contains sanitized added, updated, and unchanged identifiers.

The CLI exposes `anxious-news-sources validate FILE` and
`anxious-news-sources apply FILE`. Validation or persistence failure returns a
non-zero status; apply MUST commit all entries or none.

## Error taxonomy

- `SourceUnavailable`: connection, timeout, or exhausted transient response.
- `SourceRejected`: unsupported or permanently invalid source response.
- `RecordRejected`: malformed or missing required record data.
- `DuplicateResolved`: record linked to an existing canonical article.
- `EnrichmentInvalid`: structured output failed boundary validation.
- `EnrichmentFailed`: analyzer failed without invalidating the article.
- `PersistenceConflict`: unexpected conflict not resolved by idempotency rules.

Errors exposed in logs or persisted diagnostics contain classification and bounded
context only; secrets and unnecessary raw content are excluded.
