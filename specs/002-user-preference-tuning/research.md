# Research: User Preference Tuning

## Model boundary and structured output

**Decision**: Define separate async ports for questionnaire generation,
questionnaire interpretation, and optional semantic-equivalence classification.
Ports return untrusted mappings. Application services validate those mappings
against frozen, strict, versioned Pydantic models before using them. Use the
existing shared HTTPX client in a provider adapter with configurable endpoint,
model, timeouts, retry limits, and response-size bounds.

**Rationale**: Application contracts remain provider-neutral and easy to fake.
Native structured-output support can improve compliance but does not replace local
validation. Keeping repositories out of model ports makes direct model persistence
impossible.

**Alternatives considered**: A provider SDK would couple application behavior and
tests to one vendor. Free-form JSON or coercive parsing cannot enforce exact
question counts, option counts, actions, identifiers, or bounded fields.

References: [Pydantic JSON Schema](https://docs.pydantic.dev/latest/concepts/json_schema/),
[Pydantic strict mode](https://docs.pydantic.dev/latest/concepts/strict_mode/),
[HTTPX timeouts](https://www.python-httpx.org/advanced/timeouts/).

## Questionnaire quality and adaptation

**Decision**: Give the generator a bounded context containing the current profile,
strong and ambiguous parameters, and the most relevant prior questions and
answers. Require exactly 10 questions with four options in the schema, then apply
deterministic normalization, ordinal, option uniqueness, length, disguised-yes/no,
and substantial-repetition checks. Keep semantic qualities such as neutrality and
single-dimensional wording behind an independently replaceable validator.

**Rationale**: Structural checks catch hard violations consistently, while bounded
historical context encourages exploration without unbounded prompts. Separating
generation from validation provides a controlled failure rather than accepting
low-quality questions.

**Alternatives considered**: Supplying the entire history grows without bound and
exposes unnecessary answer data. Trusting only the generator cannot guarantee the
constitution's exact counts or quality rules. Automatically repairing invalid
questions would introduce a second opaque mutation path.

## Exact weights and deterministic updates

**Decision**: Exchange weights as canonical two-decimal strings, parse directly to
`Decimal`, reject negative zero, exponents, extra precision, non-finite values, and
out-of-range values, and persist them as `NUMERIC(3,2)` with a range constraint.
Change proposals use absolute target weights rather than deltas. Application code
sets questionnaire origin and timestamps rather than trusting generated values.

**Rationale**: Decimal strings avoid binary floating-point drift. Absolute targets
make replay and audit semantics unambiguous. Database constraints provide defense
in depth, while pre-persistence validation avoids PostgreSQL silently rounding an
invalid scale.

**Alternatives considered**: Floats cannot reliably preserve 0.01 precision.
Integer hundredths are valid but diverge from the published decimal domain
contract. Silent clamping or rounding hides invalid generated output.

References: [Python decimal](https://docs.python.org/3.11/library/decimal.html),
[PostgreSQL numeric](https://www.postgresql.org/docs/16/datatype-numeric.html).

## Atomicity, idempotency, and concurrency

**Decision**: Store a monotonically increasing profile revision. Interpretation
echoes the questionnaire and base revision; the application verifies both. Apply
one validated batch in one transaction by uniquely claiming the questionnaire,
compare-and-swapping the expected profile revision, writing parameter changes and
complete history, and marking the questionnaire applied. A stale revision triggers
fresh interpretation rather than applying against a changed profile.

**Rationale**: The transaction guarantees all-or-nothing updates. The unique
questionnaire batch and revision comparison prevent duplicate application and lost
updates across callbacks, retries, or concurrent processes under PostgreSQL's
default isolation.

**Alternatives considered**: Process-local locks do not survive restarts or
multiple instances. Pessimistically locking a user while waiting for model output
would hold a transaction across network I/O. Entity-level ORM versioning is less
clear for one multi-row update batch.

References: [PostgreSQL transaction isolation](https://www.postgresql.org/docs/16/transaction-iso.html),
[PostgreSQL INSERT conflicts](https://www.postgresql.org/docs/16/sql-insert.html),
[SQLAlchemy versioning](https://docs.sqlalchemy.org/en/20/orm/versioning.html).

## Preference semantic reuse

**Decision**: Derive a normalized semantic key from the proposed dimension,
subject, scope, and qualifiers; enforce uniqueness per user across active and
inactive parameters. Compare creation proposals with the user's small full catalog
using normalized exact keys and existing `pg_trgm` similarity. Borderline
proposals may use the read-only equivalence-classifier port, with a strict
equivalent/distinct result and retained evidence. Equivalent creation is rejected
in favor of an explicit refine, adjust, or reactivate action.

**Rationale**: Layered conservative checks prevent obvious vocabulary variants
without adding infrastructure. The existing database already enables `pg_trgm`,
and a user profile is small enough for bounded candidate comparison.

**Alternatives considered**: A vector database violates the simplicity gate at
this scale. Embeddings add model lifecycle, privacy, and calibration work without a
demonstrated need. Trigrams alone miss differently worded concepts, so they are a
candidate signal rather than sole authority.

Reference: [PostgreSQL pg_trgm](https://www.postgresql.org/docs/16/pgtrgm.html).

## Telegram callbacks and durable resume

**Decision**: Put only a short opaque random token in callback data and retain its
hash with the offered option. On callback, acknowledge promptly, treat data as
hostile, verify ownership and current-question state, and insert under a unique
question-answer constraint. Duplicate or stale callbacks return the persisted
current state without advancing twice. `/tune` resumes the first unanswered
question from PostgreSQL; in-memory conversation state is not authoritative.

**Rationale**: Telegram callback payloads are size-limited and user-controlled.
Durable tokens avoid exposing authoritative identifiers, support restart/resume,
and make retries idempotent.

**Alternatives considered**: Encoding raw questionnaire and option identifiers
exposes internal structure and still requires ownership validation. In-memory
callback or conversation state is lost on restart and cannot arbitrate concurrent
delivery.

References: [InlineKeyboardButton](https://docs.python-telegram-bot.org/en/v21.6/telegram.inlinekeyboardbutton.html),
[CallbackQuery](https://docs.python-telegram-bot.org/en/v21.6/telegram.callbackquery.html).

## Failure handling and testing

**Decision**: Classify generation, invalid output, interpretation, stale profile,
duplicate proposal, persistence, and ownership failures. Show controlled retry or
resume messages while logging only identifiers, stage, code, and sanitized
context. Use fake ports, fixed clocks/tokens, HTTPX MockTransport, and PostgreSQL
integration tests. Do not contact live Telegram or model services in automated
tests.

**Rationale**: Failures remain isolated to one user's session, profile state stays
unchanged, and tests can deterministically cover malformed output, callback races,
transaction rollback, and replay.

**Alternatives considered**: Broad exception swallowing produces success-shaped
failures. Live integration tests are nondeterministic and risk exposing user data
or credentials.

## Retention and audit linkage

**Decision**: Configure terminal questionnaire-detail retention separately from
full preference-change-history retention. Default questionnaire retention to 365
days and full history to indefinite (`0`). Run bounded recurring cleanup outside
Telegram handlers. Applied questionnaire and batch shells retain identities,
outcome, proposal hash, profile revisions, timestamps, change count, and a
deterministic history digest after detailed data expires. In addition, application
creates one immutable compact audit row per change containing parameter/action
identity, provenance, timestamp, and hashes of previous state, new state, and
reason; these rows never expire.

**Rationale**: Independent periods support privacy and storage policy without
making active tuning unreliable or erasing evidence that an update occurred.
Bounded batches prevent cleanup from monopolizing PostgreSQL, and retained hashes
and identifiers preserve auditability for every individual change.

**Alternatives considered**: Unbounded deletion creates long transactions.
Deleting applied questionnaires, batches, or compact per-change audit rows destroys
traceability. Retaining every answer and full before/after snapshot forever
prevents operators from enforcing a data-minimization policy.

## Origin authority policy

**Decision**: Treat parameter origin as immutable. A questionnaire batch may create
questionnaire-origin parameters and mutate only existing questionnaire-origin
parameters. Explicit, inference, and system parameters are read-only. An equivalent
protected parameter blocks duplicate creation; distinct narrower evidence may
create a separate questionnaire-origin parameter with its own semantic key.

**Rationale**: This gives explicit intent unambiguous authority, prevents generated
output from relabeling provenance, and keeps questionnaire evidence independently
auditable. The policy is deterministic and does not require judging whether a
generated adjustment is a “safe” strengthening.

**Alternatives considered**: Allowing questionnaire evidence to strengthen an
explicit weight still mutates a user-authoritative statement without direct
consent. Allowing refine/deactivate based on direction or confidence creates an
ambiguous policy and non-repeatable edge cases. Creating an equivalent parameter
would violate semantic deduplication.
