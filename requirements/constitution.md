# Project Constitution — Personalized News Telegram Bot

## 1. Purpose

The project is a personalized news aggregation application.

The application collects news from multiple sources and produces a personalized ranked news digest for each user.

The core product principle is:

> Optimize for "interesting and important to this particular user", not simply "most popular" or "most recent".

The Telegram bot is an interface to the application. Core business logic must remain independent from Telegram.

## 2. Architecture

### 2.1 Modular monolith

Start as a modular monolith. Do not introduce microservices, message brokers, vector databases, or other infrastructure without a concrete requirement.

Logical modules:

- News Aggregator
- Article Analysis
- User Preference System
- Personal Ranking Engine
- Digest Scheduler
- Telegram Adapter

News Aggregator and Personal Ranking are separate application modules.

### 2.2 Telegram independence

Telegram handlers are thin adapters. They may receive commands, call application services, format results and send messages.

They must not contain ranking, preference calculation, LLM prompts, scheduling or business-critical database logic.

### 2.3 LLM is not the source of truth

LLM may generate questions, interpret answers, propose preference changes, analyze articles and produce semantic scores.

LLM output must never directly modify persistent state.

All LLM output must:

1. use a structured schema;
2. be validated;
3. be normalized;
4. satisfy application constraints;
5. only then be persisted.

### 2.4 Deterministic preference state

Each user has an independent collection of preference parameters.

A parameter has at least:

- stable identifier;
- user identifier;
- name;
- description;
- evaluation instructions;
- weight;
- origin;
- active flag;
- timestamps.

Weight is in `[-1.00, +1.00]` with step `0.01`.

Positive means interest, negative means avoidance, zero means neutral.

### 2.5 Parameter vocabulary and semantic deduplication

Parameters are user-specific, but semantically equivalent parameters must not proliferate.

Before creating a new parameter, the LLM must receive the current user's active parameters and attempt to reuse or refine an existing parameter.

The system must detect or prevent obvious semantic duplicates such as:

- `space`
- `space_news`
- `space_exploration`
- `cosmic_news`

when they represent the same preference dimension.

Parameters must contain enough description and evaluation instructions to distinguish genuinely different dimensions.

### 2.6 Explicit preferences have highest authority

Preferences originate from:

- questionnaire;
- explicit user specification;
- LLM inference;
- system.

Explicit user preferences have higher semantic authority than weakly inferred preferences.

For example, `/specify Новости города Кирова` should create or strengthen a specific Kirov preference rather than merely increasing a generic Russia preference.

### 2.7 Incremental preference updates

Preference tuning must normally produce proposed changes rather than replacing the entire preference profile.

Flow:

current state -> LLM proposes changes -> validation -> deterministic update -> new state.

Every change must be auditable.

### 2.8 Adaptive questionnaire

`/tune` produces exactly 10 questions, each with exactly four options.

Questions should be adaptive: previous questions, answers and current preference parameters should be used to discover new or more specific preference dimensions rather than repeatedly asking the same generic questions.

Good questions are:

- short;
- concrete;
- focused on one semantic dimension;
- useful for ranking;
- not leading;
- not vague;
- not double-barreled.

Avoid weak yes/no-style questions disguised as four options.

### 2.9 News Aggregator vs Personal Ranking

News Aggregator is responsible for obtaining and preparing a general pool of news.

It must not decide what is personally interesting to a particular user.

Personal Ranking receives normalized/enriched articles and a user's preference state and produces a personalized ranking.

This separation must remain explicit in the architecture.

### 2.10 Explainable ranking

The ranking engine must retain enough information to explain a result:

- preference parameters;
- weights;
- article relevance per parameter;
- contribution per parameter;
- article importance;
- freshness;
- source quality;
- novelty/duplicate penalty;
- final score.

### 2.11 Deterministic mathematical ranking

LLM may provide semantic article-to-parameter relevance scores, but the final ranking must be calculated deterministically by application code.

Given identical inputs and ranking configuration, deterministic ranking must produce identical results.

### 2.12 News pipeline

Conceptually:

fetch -> normalize -> validate -> deduplicate -> enrich -> analyze -> rank -> diversify -> digest.

Each stage has one clear responsibility.

### 2.13 Persistence

PostgreSQL is the source of truth.

Persist, as appropriate:

- users;
- user preferences;
- preference history;
- questionnaires;
- answers;
- news sources;
- normalized articles;
- article analysis;
- event/duplicate groups;
- ranking information;
- digest configuration;
- digest execution/delivery history.

Use migrations.

### 2.14 Testing

Business logic must be testable without Telegram, network access or a real LLM.

At minimum test:

- preference updates;
- parameter semantic deduplication;
- weight boundaries and rounding;
- questionnaire validation;
- ranking mathematics;
- ranking determinism;
- article deduplication;
- digest selection;
- scheduler isolation and idempotency.

External services must be replaceable/mocked.

### 2.15 Observability and failure isolation

Use structured logging.

A failure in one news source must not stop other sources.

A failure for one user must not prevent other users' digests.

LLM failures must degrade gracefully.

Do not log secrets or unnecessary sensitive user data.

### 2.16 Configuration

Configurable behavior must not be hidden in magic numbers.

Examples:

- digest count limits;
- scheduler settings;
- ranking coefficients;
- freshness parameters;
- deduplication thresholds;
- LLM model;
- source configuration;
- retention periods.

### 2.17 Simplicity

Prefer clear domain/application modules and explicit interfaces over premature abstraction.

Do not optimize for distributed scale before there is evidence that it is required.
