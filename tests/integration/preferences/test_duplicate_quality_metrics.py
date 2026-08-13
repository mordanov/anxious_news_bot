from anxious_news_bot.preferences.services.duplicates import normalize_semantic_key
from tests.fixtures.preference_duplicate_cases import OBVIOUS_EQUIVALENT_KEYS


def test_obvious_exact_equivalence_recall_is_at_least_95_percent() -> None:
    matched = sum(
        normalize_semantic_key(key) == normalize_semantic_key(label)
        for key, label in OBVIOUS_EQUIVALENT_KEYS
    )
    assert matched / len(OBVIOUS_EQUIVALENT_KEYS) >= 0.95
