<!--
Sync Impact Report
- Version change: template (unversioned) -> 1.0.0
- Modified principles:
  - Template Principle 1 -> I. Personalized Relevance and User Authority
  - Template Principle 2 -> II. Modular Monolith with Adapter Boundaries
  - Template Principle 3 -> III. Validated LLM Boundary and Auditable State
  - Template Principle 4 -> IV. Deterministic, Explainable Ranking
  - Template Principle 5 -> V. Testable, Observable, and Simple by Default
- Added sections:
  - Product and Data Constraints
  - Development Workflow and Quality Gates
- Removed sections: none
- Templates requiring updates:
  - ✅ updated: .specify/templates/plan-template.md
  - ✅ updated: .specify/templates/spec-template.md
  - ✅ updated: .specify/templates/tasks-template.md
  - ✅ reviewed: .specify/templates/commands/ (directory not present)
- Runtime guidance reviewed:
  - ✅ requirements/constitution.md (source requirements)
  - ✅ README.md, docs/quickstart.md, AGENTS.md, CLAUDE.md (not present)
- Follow-up TODOs: none
-->
# Personalized News Telegram Bot Constitution

## Core Principles

### I. Personalized Relevance and User Authority

The product MUST optimize for news that is interesting and important to each
particular user, not merely popular or recent. Each user MUST have an independent
preference profile. Explicit user preferences MUST have greater semantic authority
than questionnaire-derived, inferred, or system preferences. Specific intent MUST
create or strengthen the corresponding specific preference rather than being
collapsed into a broader category.

Rationale: personalization quality and faithful treatment of user intent are the
product's primary value.

### II. Modular Monolith with Adapter Boundaries

The system MUST begin as a modular monolith with explicit modules for news
aggregation, article analysis, user preferences, personal ranking, digest
scheduling, and Telegram integration. Telegram handlers MUST remain thin adapters
and MUST NOT contain ranking, preference calculation, LLM prompts, scheduling, or
business-critical persistence logic. News aggregation MUST build a general article
pool; only personal ranking may determine relevance for a user. Microservices,
message brokers, vector databases, and comparable infrastructure MUST NOT be added
without a documented concrete requirement and rejection of a simpler alternative.

Rationale: explicit boundaries preserve testability and prevent interface or
infrastructure concerns from controlling the domain.

### III. Validated LLM Boundary and Auditable State

An LLM MUST NOT be a source of truth or directly mutate persistent state. Every LLM
result MUST use a structured schema and pass validation, normalization, and
application constraints before deterministic application code may persist it.
Preference tuning MUST normally propose incremental changes to the current profile,
and every applied change MUST be auditable. Before creating a preference parameter,
the system MUST compare it with the user's active parameters and reuse or refine a
semantically equivalent parameter.

Preference parameters MUST have a stable identifier, user identifier, name,
description, evaluation instructions, weight, origin, active flag, and timestamps.
Weights MUST remain within `[-1.00, +1.00]` at `0.01` precision.

Rationale: validation and deterministic updates prevent probabilistic output from
corrupting durable user state.

### IV. Deterministic, Explainable Ranking

LLMs MAY calculate semantic article-to-parameter relevance, but application code
MUST calculate the final ranking deterministically. Identical inputs and ranking
configuration MUST produce identical results. Ranking records MUST retain enough
information to explain preference weights, per-parameter relevance and
contributions, importance, freshness, source quality, novelty or duplicate
penalties, and the final score.

The news pipeline MUST preserve distinct fetch, normalize, validate, deduplicate,
enrich, analyze, rank, diversify, and digest responsibilities.

Rationale: reproducible and inspectable ranking is required to debug personalization
and maintain user trust.

### V. Testable, Observable, and Simple by Default

Business logic MUST be testable without Telegram, network access, or a real LLM;
external services MUST be replaceable by test doubles. Tests MUST cover affected
preference updates, semantic deduplication, weight boundaries and rounding,
questionnaire validation, ranking mathematics and determinism, article
deduplication, digest selection, and scheduler isolation and idempotency.

The system MUST use structured logging without secrets or unnecessary sensitive
user data. One source failure MUST NOT stop other sources, one user's failure MUST
NOT stop other users' digests, and LLM failures MUST expose a controlled degraded
outcome. Implementations MUST favor explicit interfaces and direct domain or
application modules over premature abstraction or distributed scaling.

Rationale: isolation, observability, and focused tests make a simple architecture
reliable under external failures.

## Product and Data Constraints

- `/tune` MUST generate exactly 10 questions with exactly four options each.
  Questions MUST use prior questions, answers, and current preferences to discover
  useful, specific ranking dimensions. Each question MUST be short, concrete,
  single-dimensional, non-leading, and neither vague nor a disguised yes/no choice.
- PostgreSQL MUST be the source of truth, and schema changes MUST use migrations.
  Persistence MUST cover applicable users, preferences and history, questionnaires
  and answers, sources, normalized articles, analyses, event or duplicate groups,
  ranking evidence, digest configuration, and execution or delivery history.
- Configurable behavior MUST be represented as configuration rather than magic
  numbers, including digest limits, scheduling, ranking coefficients, freshness,
  deduplication thresholds, LLM model, sources, and retention periods.
- Preference descriptions and evaluation instructions MUST distinguish genuinely
  different semantic dimensions and prevent obvious vocabulary variants from
  proliferating as separate parameters.

## Development Workflow and Quality Gates

Every feature specification MUST identify affected modules, preference or ranking
behavior, LLM trust boundaries, persistence changes, failure isolation, and
measurable acceptance scenarios where applicable. Every implementation plan MUST
pass the Constitution Check before research and again after design.

Plans MUST preserve module boundaries, deterministic state and ranking paths,
explainability data, migration discipline, configurable behavior, and failure
isolation. Any constitution exception MUST be recorded in Complexity Tracking with
the concrete need and the simpler alternative that was rejected.

Tasks MUST include the smallest tests that demonstrate affected business rules and
determinism. Reviews MUST reject direct LLM persistence, business logic in Telegram
handlers, personalized decisions in aggregation, unconfigured behavior constants,
or infrastructure without a demonstrated requirement.

## Governance

This constitution supersedes conflicting project practices and implementation
convenience. Amendments require a documented proposal, a Sync Impact Report,
updates to dependent templates or runtime guidance, and explicit project-owner
approval. Changes that alter existing principles incompatibly require a MAJOR
version bump; new principles or materially expanded obligations require MINOR; and
clarifications or non-semantic refinements require PATCH.

Every feature plan and review MUST verify compliance. Reviewers MUST require
Complexity Tracking for justified exceptions and MUST block unexplained violations.
The source requirements remain in `requirements/constitution.md`; this constitution
is the authoritative operational form.

**Version**: 1.0.0 | **Ratified**: 2026-08-12 | **Last Amended**: 2026-08-12
