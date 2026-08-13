from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from anxious_news_bot.preferences.domain import (
    PreferenceOrigin,
    PreferenceParameter,
    PriorAnswer,
    ProfileSnapshot,
    QuestionnaireContext,
)
from anxious_news_bot.preferences.services.context import AdaptiveContextSelector


def _parameter(key: str, weight: str) -> PreferenceParameter:
    now = datetime.now(UTC)
    user_id = uuid4()
    return PreferenceParameter(
        uuid4(),
        user_id,
        key,
        key,
        key,
        key,
        Decimal(weight),
        PreferenceOrigin.QUESTIONNAIRE,
        True,
        now,
        now,
    )


def test_selects_strong_ambiguous_and_bounded_prior_context() -> None:
    strong = _parameter("strong", "0.90")
    ambiguous = _parameter("ambiguous", "0.10")
    prior = tuple(PriorAnswer(f"q{i}", f"a{i}", f"d{i}") for i in range(5))
    context = QuestionnaireContext(
        ProfileSnapshot(strong.user_id, 1, (strong, ambiguous)),
        "en",
        prior,
    )
    result = AdaptiveContextSelector(history_limit=2).select(context)
    assert result.strong_preferences == (strong,)
    assert result.ambiguous_preferences == (ambiguous,)
    assert result.prior_answers == prior[-2:]
    assert result.explored_dimensions == {"d3", "d4"}
