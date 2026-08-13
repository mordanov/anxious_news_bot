from anxious_news_bot.preferences.domain import PriorAnswer
from anxious_news_bot.preferences.services.repetition import (
    SubstantialRepetitionDetector,
)


def test_normalized_paraphrase_is_repetition() -> None:
    detector = SubstantialRepetitionDetector(threshold=0.80)
    prior = PriorAnswer(
        "Which LOCAL stories do you prefer?",
        "Investigations",
        "local_news",
    )
    assert detector.is_repetition(
        "Which local stories do you prefer?", "another_dimension", prior
    )


def test_ambiguity_clarification_is_allowed() -> None:
    detector = SubstantialRepetitionDetector()
    prior = PriorAnswer("How local should news be?", "Unsure", "local_news")
    assert not detector.is_repetition("How local should news be?", "local_news", prior)


def test_renamed_semantic_dimension_is_repetition() -> None:
    detector = SubstantialRepetitionDetector()
    prior = PriorAnswer(
        "How often should updates arrive?",
        "Once a day",
        "news_update_urgency",
    )
    assert detector.is_repetition(
        "Choose your preferred alert speed.",
        "breaking_news",
        prior,
    )
