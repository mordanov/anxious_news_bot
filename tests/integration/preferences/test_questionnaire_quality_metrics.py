from difflib import SequenceMatcher

from anxious_news_bot.preferences.services.questionnaire_quality import normalize_text
from tests.fixtures.preference_quality_cases import (
    CONSECUTIVE_DISTINCT_CASES,
    VALID_QUESTION_CASES,
)


def test_reviewed_question_quality_acceptance_is_at_least_95_percent() -> None:
    accepted = sum(
        "news" in normalize_text(question) for question in VALID_QUESTION_CASES
    )
    assert accepted / len(VALID_QUESTION_CASES) >= 0.95


def test_consecutive_substantial_repetition_is_below_five_percent() -> None:
    repeated = sum(
        SequenceMatcher(None, normalize_text(first), normalize_text(second)).ratio()
        >= 0.85
        for first, second in CONSECUTIVE_DISTINCT_CASES
    )
    assert repeated / len(CONSECUTIVE_DISTINCT_CASES) <= 0.05
