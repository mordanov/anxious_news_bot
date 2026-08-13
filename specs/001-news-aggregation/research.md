# Research: News Aggregation and Article Analysis

## Persistence and migrations

**Decision**: Use SQLAlchemy 2.x asynchronous sessions with Psycopg 3 and Alembic.
Use one session/transaction per independently processed source and database
constraints or upserts for idempotency.

**Rationale**: The feature has related durable entities, transaction boundaries,
and concurrent source work. SQLAlchemy provides mature mapping and async units of
work, Psycopg supports native async PostgreSQL access, and Alembic provides
incremental schema migrations. Separate sessions avoid unsafe concurrent session
sharing.

**Alternatives considered**: Direct Psycopg would require more mapping and
transaction boilerplate. `asyncpg` remains lower level and still needs migration
management. A framework ORM would add an unrelated application framework.

References: [SQLAlchemy asyncio](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html),
[Psycopg async](https://www.psycopg.org/psycopg3/docs/advanced/async.html),
[Alembic asyncio](https://alembic.sqlalchemy.org/en/latest/cookbook.html#using-asyncio-with-alembic).

## Source retrieval and parsing

**Decision**: Reuse one injected `httpx.AsyncClient` with explicit connect, read,
write, and pool timeouts. Parse RSS/Atom response bytes with feedparser. Preserve
ETag and Last-Modified values and treat HTTP 304 as a successful no-change result.

**Rationale**: HTTPX supports async connection pooling and replaceable mock
transports. Feedparser handles common syndication variants and exposes malformed
feed diagnostics without requiring every imperfect feed to be rejected.

**Alternatives considered**: `aiohttp` duplicates HTTP capabilities without a
demonstrated need. Source-specific HTTP logic in the coordinator would prevent
adapter replacement.

References: [HTTPX async](https://www.python-httpx.org/async/),
[HTTPX timeouts](https://www.python-httpx.org/advanced/timeouts/),
[feedparser](https://feedparser.readthedocs.io/en/latest/introduction/).

## Canonical URL identity

**Decision**: Implement a pure, versioned canonicalization policy with
`urllib.parse`: allow configured HTTP(S) URLs, resolve relative links, normalize
scheme/host/default ports/fragments and safe path encoding, remove an explicit
tracking-parameter list, and deterministically order retained query pairs. Store
the original URL, canonical URL, and policy version.

**Rationale**: Conservative RFC-safe normalization is deterministic and avoids
merging distinct server resources. A unique canonical URL constraint closes
concurrent check-then-insert races.

**Alternatives considered**: Removing all query parameters, forcing HTTPS, or
changing trailing slashes can collapse distinct resources. Redirect resolution is
retained separately because it requires network state.

References: [urllib.parse](https://docs.python.org/3.11/library/urllib.parse.html),
[RFC 3986 normalization](https://datatracker.ietf.org/doc/html/rfc3986#section-6.2.2),
[PostgreSQL unique constraints](https://www.postgresql.org/docs/current/ddl-constraints.html#DDL-CONSTRAINTS-UNIQUE-CONSTRAINTS).

## Near duplicates and event grouping

**Decision**: Enable PostgreSQL `pg_trgm`. Generate candidates within language and
publication-time windows, compare normalized title and bounded content, and persist
scores, thresholds, normalization version, and the resulting
duplicate/review/distinct decision.

Keep event grouping separate from duplicate classification but make its initial
policy deterministic and enrichment-independent. Compare distinct-source,
same-language reports within 48 hours, using ingestion time when publication time
is missing. Calculate a weighted score from title similarity (0.50), content
similarity (0.30), normalized topic overlap (0.10), and normalized geographic
overlap (0.10). Require either shared topic/geography or title similarity of at
least 0.55. Scores at or above 0.62 join the event, scores from 0.52 through 0.6199
produce a review proposal, and lower scores remain distinct. Persist every signal,
weight, threshold, window, and algorithm version. These defaults are configuration
and must be calibrated against the labeled corpus.

**Rationale**: Trigram similarity is deterministic, multilingual, indexable, and
requires no vector store. Separating textual duplication from event equivalence
prevents differently worded event reports from being treated as exact copies. The
weighted evidence policy makes US2 repeatable before any optional enrichment;
validated enrichment may later propose an auditable reassignment but is not an
input to the initial decision.

**Alternatives considered**: In-memory RapidFuzz is suitable for small batches but
does not solve indexed candidate retrieval. MinHash and embeddings add tuning or
infrastructure before scale requires them.

Reference: [PostgreSQL pg_trgm](https://www.postgresql.org/docs/current/pgtrgm.html).

## Structured enrichment

**Decision**: Define strict, versioned Pydantic 2 models with bounded values,
enums, and `extra="forbid"`. Validate independently useful analysis sections and
map only valid sections into domain values. Keep the provider behind an optional
enricher port and store complete, partial, invalid, failed, or not-attempted status.

**Rationale**: Structured validation prevents probabilistic output from becoming
state directly while allowing partial enrichment to preserve valid work. No
provider SDK is needed until a provider is selected.

**Alternatives considered**: Free-form JSON or permissive coercion cannot guarantee
the article model's constraints. Discarding the article on enrichment failure
violates graceful degradation.

References: [Pydantic models](https://docs.pydantic.dev/latest/concepts/models/),
[strict mode](https://docs.pydantic.dev/latest/concepts/strict_mode/).

## Retry, concurrency, and scheduling

**Decision**: Apply bounded Tenacity retries with exponential backoff and jitter to
idempotent source GETs for connection failures, selected timeouts, 408, 429, and
transient 5xx responses. Honor Retry-After. Run source tasks under a configurable
semaphore; each task records and contains expected failures. Use an in-process
scheduler only when periodic execution is added and guard overlapping cycles with
an application-scoped PostgreSQL advisory lock. Enable the existing Telegram
application's JobQueue integration as the in-process clock: a startup-registered
repeating callback invokes only the NewsAggregator application service, and
shutdown removes the job cleanly. The scheduler scan interval is independent from
each source's polling interval; every tick queries only enabled due sources.

**Rationale**: Bounded retries handle transient source faults without hanging a
cycle. Isolated tasks and transactions preserve sibling progress. The existing
process and PostgreSQL are enough for initial scheduling and locking.

**Alternatives considered**: Unbounded retries compromise cycle completion.
Celery, Redis, Kafka, or a separate worker add operational complexity without a
current scale or availability requirement.

References: [Tenacity](https://tenacity.readthedocs.io/en/latest/),
[HTTPX transports](https://www.python-httpx.org/advanced/transports/),
[PostgreSQL advisory locks](https://www.postgresql.org/docs/current/explicit-locking.html#ADVISORY-LOCKS).

## Operator source management

**Decision**: Provide a versioned JSON source-catalog schema and a local CLI with
`validate` and `apply` modes. Validation parses the entire file strictly and
detects duplicate stable identifiers or endpoint conflicts. Apply performs one
database transaction that upserts every listed source, including explicit
enable/disable changes; omitted sources remain unchanged. Output is a sanitized
add/update/unchanged summary.

**Rationale**: A file contract is reviewable, repeatable, automation-friendly, and
does not require adding an administration web service or placing operational
management in Telegram handlers. All-or-nothing application prevents a partially
updated catalog.

**Alternatives considered**: Direct database edits bypass validation. Telegram
administration commands mix operational control into the adapter. A web admin UI
is unnecessary for the initial source count.

## Testing strategy

**Decision**: Use pytest and pytest-asyncio with injected adapters, HTTPX
MockTransport, fixed clocks, fixture feeds, and deterministic fake enrichers.
Exercise migrations, uniqueness, upserts, and trigram queries against ephemeral
PostgreSQL rather than substituting SQLite.

**Rationale**: Most business rules remain fast and offline, while PostgreSQL-only
semantics are verified where they actually run.

**Alternatives considered**: Live source or LLM tests are nondeterministic.
SQLite cannot validate PostgreSQL JSON, advisory lock, trigram, or upsert behavior.
