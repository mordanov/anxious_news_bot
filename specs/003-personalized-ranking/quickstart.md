# Quickstart: Explicit Preferences and Personalized Ranking

## Prerequisites

- Python 3.11 or newer
- PostgreSQL 16 or newer with the existing project migrations
- Existing normalized articles, generic analyses, users, and preference profiles
- A Telegram bot token for manual `/specify` interaction
- A compatible structured-output model endpoint for manual interpretation and
  article relevance evaluation

Automated tests use deterministic ports and do not require live Telegram, news
sources, or model services.

## Configure

Install the existing project and set base application configuration:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'

export DATABASE_URL='postgresql+psycopg://localhost/anxious_news'
export TELEGRAM_BOT_TOKEN='replace-with-secret'
export PREFERENCES_MODEL_BASE_URL='https://provider.example/v1'
export PREFERENCES_MODEL_API_KEY='replace-with-secret'
export PREFERENCES_MODEL_NAME='configured-structured-output-model'
export PREFERENCES_MODEL_MAX_RESPONSE_BYTES='262144'
export PREFERENCES_EXPLICIT_REQUEST_MAX_LENGTH='1000'
export PREFERENCES_EXPLICIT_HISTORY_LIMIT='20'
export PREFERENCES_EXPLICIT_STALE_RETRY_LIMIT='1'
export RANKING_MODEL_BASE_URL='https://provider.example/v1'
export RANKING_MODEL_API_KEY='replace-with-secret'
export RANKING_MODEL_NAME='configured-relevance-model'
export RANKING_MODEL_TIMEOUT_SECONDS='30'
export RANKING_MODEL_RETRY_ATTEMPTS='3'
export RANKING_MODEL_MAX_RESPONSE_BYTES='262144'
```

Ranking settings use validated exact decimal strings. Planned defaults:

```bash
export RANKING_CONFIGURATION_VERSION='1.0'
export RANKING_TIE_POLICY_VERSION='1.0'
export RANKING_RETENTION_POLICY_VERSION='1.0'
export RANKING_PERSONAL_COEFFICIENT='0.45000'
export RANKING_IMPORTANCE_COEFFICIENT='0.20000'
export RANKING_FRESHNESS_COEFFICIENT='0.15000'
export RANKING_QUALITY_COEFFICIENT='0.10000'
export RANKING_NOVELTY_COEFFICIENT='0.10000'
export RANKING_FRESHNESS_HORIZON_SECONDS='259200'
export RANKING_FUTURE_TOLERANCE_SECONDS='300'
export RANKING_MINIMUM_SOURCE_QUALITY='0.35000'
export RANKING_MAXIMUM_CANDIDATES='500'
export RANKING_EVENT_CAP='2'
export RANKING_TOPIC_CAP='3'
export RANKING_SOURCE_CAP='3'
export RANKING_EXPLICIT_WEIGHT_THRESHOLD='0.75'
export RANKING_EXPLICIT_RELEVANCE_THRESHOLD='0.6000'
export RANKING_EXPLANATION_CONTRIBUTION_LIMIT='3'
export RANKING_EVALUATION_RETRY_ATTEMPTS='3'
export RANKING_RAW_RESPONSE_RETENTION_DAYS='30'
export RANKING_DETAIL_RETENTION_DAYS='90'
export RANKING_RETENTION_BATCH_SIZE='500'
export RANKING_RETENTION_SCAN_INTERVAL_SECONDS='86400'
```

The five coefficients must sum exactly to `1.00000`; the personal coefficient must
be at least `0.40000`. Ranking ties resolve by
`final_score DESC`, `personal_signed DESC`, `importance DESC`,
`published_at DESC NULLS LAST`, `article_id ASC`. Invalid settings stop ranking
startup rather than being silently corrected. `RANKING_MODEL_BASE_URL` and
`RANKING_MODEL_API_KEY` may be omitted only when the preferences provider values
are configured and intentionally reused. Do not commit credentials.

## Initialize storage

```bash
alembic upgrade head
alembic current
```

Migration `003` adds explicit request/evidence linkage, evaluation runs and
attempts, parameter relevance, configuration snapshots, ranking runs, factor and
contribution evidence, selection outcomes, and compact ranking audit.

## Run validation

```bash
python -m pytest tests/unit/preferences tests/unit/ranking tests/unit/telegram
python -m pytest tests/integration/ranking
python -m pytest
python -m ruff format --check src tests docker
python -m ruff check src tests docker
python -m bandit --quiet --recursive src docker
python -m pip_audit . --strict --progress-spinner off
```

PostgreSQL integration tests use the existing temporary-database fixture. Contract
tests validate every model document locally before persistence.

Ranking uses fixed Decimal arithmetic, versioned coefficient snapshots, bounded
eligibility filters, deterministic diversity relaxation, explanation ordinals by
absolute signed contribution, and bounded privacy retention. Detailed evidence is
retained only while needed for reconstruction and is compacted without exposing
raw prompts, raw model responses, article text, or profile snapshots in logs.

## Acceptance walkthrough

1. Submit `/specify Новости города Кирова` for a user with only a broad Russia
   preference; confirm a specific Kirov parameter is created and the broad
   parameter is not the only changed concept.
2. Repeat a semantically equivalent request against active and inactive
   parameters; confirm reuse/refinement/reactivation without duplicate creation.
3. Target questionnaire, inference, and system-origin parameters with explicit
   statements; confirm immutable creation origin, new explicit evidence, explicit
   history source, and effective explicit authority.
4. Replay the same Telegram update and race two applications; confirm one profile
   revision increment and one applied batch.
5. Change the profile during interpretation; confirm stale output applies nothing
   and one fresh interpretation uses the new revision.
6. Submit malformed, unknown-target, unrelated-explicit-target, excess-precision,
   negative-zero, and out-of-range proposals; confirm the profile remains
   unchanged.
7. Evaluate matching, neutral, and contradicting articles against all active
   parameters; confirm canonical relevance in `[-1.0000,+1.0000]` and exact
   parameter coverage.
8. Inject transport and invalid-output failures; confirm bounded retries,
   incomplete status, preserved previous valid evaluation, and later
   reprocessing.
9. Verify personal score for positive, negative, zero, cancelling, no-active, and
   all-zero profiles against hand-calculated decimal fixtures.
10. Verify importance, freshness, quality, novelty, mapped personal factor,
    coefficients, and final score reconstruct exactly from stored evidence.
11. Rank the same immutable snapshot 100 times; confirm identical scores,
    explanations, exclusions, ties, and ordering.
12. Test missing analysis, invalid/future/obsolete publication times, low source
    quality, duplicate outcomes, and incomplete personal evidence; confirm
    deterministic eligibility reasons.
13. Select from repeated events, topics, and sources; confirm protected explicit
    matches receive first cap capacity, caps are respected, relaxation order is
    stable, and shortages are recorded.
14. Change a profile, generic analysis, event assignment, duplicate decision, or
    configuration before completion; confirm the run becomes stale rather than
    mixing versions.
15. Inspect explanations and verify factor values, final score, top signed
    contributions, weights, relevance, authority, and selection reason without
    prompts or chain-of-thought.
16. Run bounded retention with expired raw requests, attempts, and ranking detail;
    confirm active work and current profile/evaluation data survive and compact
    preference/ranking audit remains for retained references.
17. Review structured logs and confirm no credentials, raw explicit statements,
    article text, prompts, model responses, or profile snapshots appear.
18. Verify ranking paths perform no source fetch and trigger no digest delivery.

## Verified acceptance commands

1. `/specify` Kirov specificity and Telegram hand-off
   Command: `.venv/bin/python -m pytest tests/unit/telegram/test_specify.py::test_extracts_text_update_identity_and_language_before_calling_service tests/integration/ranking/test_explicit_quality_metrics.py::test_reviewed_specificity_cases_meet_sc001_threshold`
   Outcome: `2 passed in 0.37s`
2. Semantic duplicate reuse/refine/reactivate
   Command: `.venv/bin/python -m pytest tests/unit/preferences/test_specify.py::test_duplicate_resolution_reuses_existing_parameter_before_apply tests/integration/ranking/test_explicit_quality_metrics.py::test_reviewed_equivalence_cases_meet_sc002_threshold`
   Outcome: `2 passed in 0.14s`
3. Explicit authority across questionnaire, inference, and system origins
   Command: `.venv/bin/python -m pytest tests/unit/preferences/test_explicit_authority.py::test_explicit_batches_may_target_any_origin_when_semantically_related tests/unit/preferences/test_explicit_authority.py::test_effective_authority_prefers_explicit_evidence_and_falls_back_to_origin tests/integration/ranking/test_explicit_preferences.py::test_concurrent_replay_applies_once_and_preserves_origin_history_audit_and_evidence`
   Outcome: `18 passed in 1.07s`
4. Idempotent replay under concurrent application
   Command: `.venv/bin/python -m pytest tests/integration/ranking/test_explicit_preferences.py::test_concurrent_replay_applies_once_and_preserves_origin_history_audit_and_evidence`
   Outcome: `1 passed in 0.94s`
5. One fresh reinterpretation after a stale profile change
   Command: `.venv/bin/python -m pytest tests/unit/preferences/test_specify.py::test_reinterprets_once_after_stale_profile_conflict`
   Outcome: `1 passed in 0.14s`
6. Malformed, unknown-target, precision, negative-zero, range, and unrelated-target rejection
   Command: `.venv/bin/python -m pytest tests/unit/preferences/test_specify.py::test_validation_failure_becomes_invalid_state tests/unit/preferences/test_explicit_authority.py::test_broad_only_target_is_rejected_for_narrower_statement tests/unit/preferences/test_explicit_authority.py::test_unrelated_explicit_parameter_is_protected tests/unit/preferences/test_explicit_authority.py::test_invalid_explicit_change_rejects_whole_batch tests/unit/preferences/test_explicit_schemas.py::test_rejects_negative_zero_precision_and_range_violations tests/unit/preferences/test_explicit_schemas.py::test_rejects_malformed_change_types`
   Outcome: `12 passed in 0.15s`
7. Matching, neutral, and contradicting evaluation coverage
   Command: `.venv/bin/python -m pytest tests/unit/ranking/test_evaluation_quality.py::test_reviewed_direction_metrics_match_expected_alignment tests/integration/ranking/test_evaluations.py::test_accept_evaluation_rejects_incomplete_coverage_and_wrong_user_parameters`
   Outcome: `2 passed in 0.99s`
8. Retry, invalid-output, preserved prior evidence, and later reprocessing
   Command: `.venv/bin/python -m pytest tests/unit/ranking/test_evaluate.py::test_transient_failures_retry_before_accepting tests/unit/ranking/test_evaluate.py::test_invalid_output_is_terminal_and_marks_evaluation_incomplete tests/unit/ranking/test_evaluate.py::test_failed_reprocessing_preserves_prior_valid_evidence_and_allows_later_success`
   Outcome: `3 passed in 0.14s`
9. Positive, negative, zero, cancelling, no-active, and all-zero personal scoring
   Command: `.venv/bin/python -m pytest tests/unit/ranking/test_score.py::test_contribution_uses_exact_decimal_for_positive_negative_zero_and_boundaries tests/unit/ranking/test_score.py::test_score_uses_weighted_mean_normalization_and_cancelling_contributions tests/unit/ranking/test_score.py::test_score_distinguishes_no_active_and_all_zero_profiles`
   Outcome: `3 passed in 0.07s`
10. Stored-factor and score reconstruction
    Command: `.venv/bin/python -m pytest tests/integration/ranking/test_explainability.py::test_retained_ranking_records_reconstruct_scores_explanations_and_hashes`
    Outcome: `1 passed in 1.08s`
11. One-hundred-run byte stability for scores, explanations, exclusions, ties, and ordering
    Command: `.venv/bin/python -m pytest tests/integration/ranking/test_determinism.py::test_ranking_replays_byte_stably_for_one_hundred_identical_runs`
    Outcome: `1 passed in 4.35s`
12. Eligibility reasons for missing analysis, publication rules, source quality, duplicates, and incomplete personal evidence
    Command: `.venv/bin/python -m pytest tests/unit/ranking/test_eligibility.py::test_determine_eligibility_handles_incomplete_generic_and_personal_evidence tests/unit/ranking/test_eligibility.py::test_determine_eligibility_enforces_source_quality_and_publication_rules tests/unit/ranking/test_eligibility.py::test_determine_eligibility_rejects_duplicates_and_explicit_vetoes tests/unit/ranking/test_eligibility.py::test_determine_eligibility_uses_deterministic_reason_precedence`
    Outcome: `4 passed in 0.07s`
13. Protected explicit diversity, cap enforcement, stable relaxation, and shortages
    Command: `.venv/bin/python -m pytest tests/unit/ranking/test_diversify.py::test_selector_gives_protected_records_first_access_and_preserves_input_order tests/unit/ranking/test_diversify.py::test_selector_restarts_from_original_groups_for_relaxation_vectors tests/unit/ranking/test_diversify.py::test_selector_returns_shortage_when_pool_is_exhausted_without_bypassing_quality tests/integration/ranking/test_diversity.py::test_diversity_persists_cap_vectors_reasons_positions_and_selection_hashes`
    Outcome: `4 passed in 1.09s`
14. Stale evaluation and ranking snapshots never mix versions
    Command: `.venv/bin/python -m pytest tests/unit/ranking/test_evaluate.py::test_stale_inputs_mark_run_stale_after_a_valid_attempt tests/integration/ranking/test_ranking.py::test_input_version_recheck_marks_runs_stale_without_persisting_records tests/integration/ranking/test_ranking.py::test_configuration_versions_are_immutable_once_referenced`
    Outcome: `3 passed in 1.21s`
15. Explanation factors, signed contributions, authority, and prompt-free output
    Command: `.venv/bin/python -m pytest tests/unit/ranking/test_explanations.py::test_explainer_returns_schema_factors_selection_and_top_absolute_contributions tests/unit/ranking/test_explanations.py::test_explainer_breaks_contribution_ties_by_parameter_id_and_preserves_authority tests/unit/ranking/test_explanations.py::test_explainer_keeps_bounded_names_and_excludes_prompt_or_chain_of_thought_fields`
    Outcome: `3 passed in 0.14s`
16. Bounded retention with active exclusions and audit survival
    Command: `.venv/bin/python -m pytest tests/integration/ranking/test_retention.py::test_cleanup_clears_expired_raw_text_and_raw_responses_without_touching_active_work tests/integration/ranking/test_retention.py::test_cleanup_deletes_only_expired_noncurrent_evaluation_details tests/integration/ranking/test_retention.py::test_cleanup_compacts_expired_ranking_details_in_bounded_batches_and_preserves_audit tests/integration/ranking/test_retention.py::test_cleanup_refuses_ranking_detail_deletion_without_compact_audit`
    Outcome: `4 passed in 1.78s`
17. Structured-log redaction for statements, article text, prompts, responses, and profile snapshots
    Command: `.venv/bin/python -m pytest tests/unit/ranking/test_observability.py tests/unit/telegram/test_specify.py::test_logs_exclude_raw_statement_text`
    Outcome: `4 passed in 0.44s`
18. Ranking, evaluation, and `/specify` boundaries never fetch or deliver news
    Command: `.venv/bin/python -m pytest tests/unit/ranking/test_boundaries.py::test_personalization_paths_never_fetch_news_aggregate_or_schedule_jobs`
    Outcome: `3 passed in 0.36s`

## Expected result

Users can state specific explicit preferences that safely override weaker evidence
without losing provenance. Validated semantic relevance produces exact,
deterministic, explainable personal scores. Quality and diversity rules select a
useful varied result while protecting strong explicit intent, and every retained
outcome can be replayed or audited from versioned evidence.
