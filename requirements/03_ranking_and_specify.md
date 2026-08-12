# Feature Specification: Explicit Preferences and Personal Ranking

## Goal

Implement explicit user preference specification through `/specify` and a deterministic, explainable personalized ranking engine.

This module consumes general news produced by the News Aggregator. It must not be responsible for fetching news.

# Part 1 — /specify

## 1. Command

The application receives free-form text, for example:

`/specify Новости города Кирова`

The text is an explicit user preference statement.

## 2. Interpretation

The LLM receives:

- user request;
- current preference parameters;
- relevant preference history.

It may propose:

- strengthen existing parameter;
- weaken existing parameter;
- create new parameter;
- deactivate obsolete/conflicting parameter;
- refine a broad parameter into a more specific one.

## 3. Explicit Preference Priority

Explicit preferences have stronger authority than questionnaire-derived or weakly inferred preferences.

`/specify Новости города Кирова` should preferably create/strengthen a specific Kirov preference rather than only increasing `Russia news`.

## 4. Parameter Reuse

The LLM must compare the requested preference with existing parameters before creating a new one.

Avoid semantic duplicates.

## 5. Update Flow

User text -> LLM proposal -> validation -> deterministic update -> preference history.

No direct LLM database writes.

# Part 2 — Article-to-Preference Evaluation

For each article and active user parameter, calculate a semantic relevance score:

`r_i(a) ∈ [-1, +1]`

Interpretation:

- `+1`: very strong match;
- `0`: unrelated/neutral;
- `-1`: strongly contradicts the preference.

The LLM may generate `r_i(a)`.

The application validates and stores the structured result.

# Part 3 — Mathematical Ranking

For user `u` and article `a`:

`w_i` = user's preference weight.

`r_i(a)` = article relevance to parameter `i`.

Personal preference score:

`P(a,u) = Σ(w_i × r_i(a))`

Normalize the result if necessary so its range is predictable.

This is the primary personalization signal.

## 6. Generic Ranking Factors

The final ranking also considers:

- personal relevance;
- article importance;
- freshness;
- source quality;
- novelty/duplicate penalty.

Each factor must be normalized.

Use configurable coefficients.

The ranking engine must keep personal relevance conceptually separate from generic importance.

## 7. Personalization Principle

Generic importance must not automatically dominate personal relevance.

An extremely important article can be irrelevant to a user.

A moderately important article can be highly valuable to a specific user.

Very low-quality, obsolete or duplicate articles may still be filtered regardless of preference.

## 8. Diversity

After scoring, apply diversity-aware selection.

Avoid:

- multiple representatives of the same event;
- excessive concentration on one topic;
- excessive concentration on one source.

Do not allow diversity to override very strong explicit user preferences without a configurable reason.

## 9. Ranking Explanation

Persist or return enough information to explain:

- final score;
- personal score;
- importance;
- freshness;
- quality;
- novelty;
- top contributing parameters;
- each parameter's weight;
- each parameter's relevance score;
- each contribution.

## 10. Determinism

The final mathematical ranking stage must be deterministic.

Given identical article analysis, user preferences and configuration, the same ranking must be produced.

LLM randomness must not be part of the final deterministic calculation.

## 11. LLM Failure

If article evaluation fails:

- retry according to configuration;
- otherwise mark the evaluation incomplete;
- do not corrupt previous valid data;
- allow later reprocessing.

## 12. Acceptance Criteria

- Positive preference produces positive contribution for matching content.
- Negative preference penalizes matching content.
- Zero-weight preference contributes zero.
- `/specify` creates or strengthens the appropriate specific preference.
- Final ranking is explainable.
- Ranking is deterministic.
- Ranking module does not fetch news.
