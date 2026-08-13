from decimal import Decimal

import pytest

from anxious_news_bot.config import Settings


def _base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")


def test_settings_reads_bot_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", " token ")

    assert Settings.from_env().telegram_bot_token == "token"


def test_settings_requires_bot_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN is required"):
        Settings.from_env()


def test_settings_reads_exact_ranking_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _base_env(monkeypatch)
    monkeypatch.setenv("PREFERENCES_MODEL_BASE_URL", "https://model.example/v1")
    monkeypatch.setenv("PREFERENCES_MODEL_API_KEY", "secret")
    monkeypatch.setenv("PREFERENCES_MODEL_NAME", "preferences-model")
    monkeypatch.setenv("RANKING_MODEL_NAME", "ranking-model")

    settings = Settings.from_env()

    assert settings.ranking_model_base_url == "https://model.example/v1"
    assert settings.ranking_model_api_key == "secret"
    assert settings.ranking_model_name == "ranking-model"
    assert settings.ranking_personal_coefficient == Decimal("0.45000")
    assert settings.ranking_importance_coefficient == Decimal("0.20000")
    assert settings.ranking_freshness_coefficient == Decimal("0.15000")
    assert settings.ranking_quality_coefficient == Decimal("0.10000")
    assert settings.ranking_novelty_coefficient == Decimal("0.10000")
    assert settings.ranking_minimum_source_quality == Decimal("0.35000")
    assert settings.ranking_explicit_weight_threshold == Decimal("0.75")
    assert settings.ranking_explicit_relevance_threshold == Decimal("0.6000")


def test_blank_ranking_provider_values_fall_back_to_preferences(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _base_env(monkeypatch)
    monkeypatch.setenv("PREFERENCES_MODEL_BASE_URL", "https://model.example/v1")
    monkeypatch.setenv("PREFERENCES_MODEL_API_KEY", "secret")
    monkeypatch.setenv("PREFERENCES_MODEL_NAME", "preferences-model")
    monkeypatch.setenv("RANKING_MODEL_BASE_URL", "")
    monkeypatch.setenv("RANKING_MODEL_API_KEY", "")
    monkeypatch.setenv("RANKING_MODEL_NAME", "ranking-model")

    settings = Settings.from_env()

    assert settings.ranking_model_base_url == "https://model.example/v1"
    assert settings.ranking_model_api_key == "secret"


def test_settings_reject_invalid_ranking_coefficient_sum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _base_env(monkeypatch)
    monkeypatch.setenv("RANKING_NOVELTY_COEFFICIENT", "0.09000")

    with pytest.raises(
        RuntimeError,
        match=r"RANKING_\*_COEFFICIENT values must sum exactly to 1.00000",
    ):
        Settings.from_env()


def test_settings_reject_personal_ranking_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _base_env(monkeypatch)
    monkeypatch.setenv("RANKING_PERSONAL_COEFFICIENT", "0.39000")
    monkeypatch.setenv("RANKING_IMPORTANCE_COEFFICIENT", "0.26000")

    with pytest.raises(
        RuntimeError,
        match="RANKING_PERSONAL_COEFFICIENT must be at least 0.40000",
    ):
        Settings.from_env()


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        (
            "RANKING_MODEL_NAME",
            "ranking-model",
            "RANKING_MODEL_BASE_URL, RANKING_MODEL_API_KEY, and RANKING_MODEL_NAME must be configured together",
        ),
        (
            "RANKING_MAXIMUM_CANDIDATES",
            "501",
            "RANKING_MAXIMUM_CANDIDATES must be at most 500",
        ),
        (
            "RANKING_PERSONAL_COEFFICIENT",
            "0.45",
            "RANKING_PERSONAL_COEFFICIENT must use exactly 5 decimal places",
        ),
        (
            "PREFERENCES_EXPLICIT_STALE_RETRY_LIMIT",
            "2",
            "PREFERENCES_EXPLICIT_STALE_RETRY_LIMIT must be at most 1",
        ),
    ],
)
def test_settings_fail_closed_for_invalid_ranking_values(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
    message: str,
) -> None:
    _base_env(monkeypatch)
    monkeypatch.setenv(name, value)

    with pytest.raises(RuntimeError, match=message):
        Settings.from_env()
