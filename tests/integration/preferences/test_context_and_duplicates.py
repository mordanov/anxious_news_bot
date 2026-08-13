from datetime import UTC, datetime

from tests.integration.preferences.helpers import completed_answers, create_proposal


async def test_history_context_is_bounded_and_isolated_per_user(
    preference_repository,
) -> None:
    _, state, _ = await completed_answers(preference_repository, 100)
    await preference_repository.load_interpretation_input(state.questionnaire_id)
    await preference_repository.apply_changes(
        state.questionnaire_id,
        create_proposal(state.questionnaire_id),
        datetime.now(UTC),
    )
    context, _ = await preference_repository.start_or_resume(100, "en")
    other_context, _ = await preference_repository.start_or_resume(200, "ru")
    candidates = await preference_repository.duplicate_candidates(
        context.profile.user_id,
        "different_key",
        "Local News",
    )
    assert len(context.prior_answers) == 10
    assert len(context.dimension_context) == 10
    assert all(item.exposure_count == 1 for item in context.dimension_context)
    assert context.profile.parameters[0].semantic_key == "local_news"
    assert other_context.prior_answers == ()
    assert other_context.profile.parameters == ()
    assert other_context.language_code == "ru"
    assert candidates.parameters[0].semantic_key == "local_news"
