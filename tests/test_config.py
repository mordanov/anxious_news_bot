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


def test_settings_reads_validated_digest_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _base_env(monkeypatch)

    settings = Settings.from_env()

    assert settings.digest_default_count == 10
    assert settings.digest_default_local_time == "09:00"
    assert settings.digest_default_timezone == "UTC"
    assert settings.digest_candidate_limit == 100
    assert settings.digest_material_update_novelty_threshold == Decimal("0.7000")
    assert settings.digest_material_update_max_content_similarity == Decimal("0.60000")


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("DIGEST_SCAN_INTERVAL_SECONDS", "0", "must be at least 1"),
        ("DIGEST_CLAIM_BATCH_SIZE", "0", "must be at least 1"),
        ("DIGEST_MAX_CLAIMS_PER_TICK", "0", "must be at least 1"),
        ("DIGEST_CLAIM_TIME_BUDGET_SECONDS", "0", "must be at least 1"),
        ("DIGEST_USER_CONCURRENCY", "0", "must be at least 1"),
        ("DIGEST_DEFAULT_COUNT", "4", "must be at least 5"),
        ("DIGEST_DEFAULT_COUNT", "21", "must be at most 20"),
        ("DIGEST_CANDIDATE_LIMIT", "19", "must be at least 20"),
        ("DIGEST_MAX_ATTEMPTS", "0", "must be at least 1"),
        ("DIGEST_RETRY_BASE_SECONDS", "0", "must be at least 1"),
        (
            "DIGEST_MATERIAL_UPDATE_NOVELTY_THRESHOLD",
            "0.700",
            "must use exactly 4 decimal places",
        ),
        (
            "DIGEST_MATERIAL_UPDATE_MAX_CONTENT_SIMILARITY",
            "0.6000",
            "must use exactly 5 decimal places",
        ),
        (
            "DIGEST_MATERIAL_UPDATE_MIN_TEXT_CHARS",
            "0",
            "must be at least 1",
        ),
        ("DIGEST_HISTORY_RETENTION_DAYS", "0", "must be at least 1"),
        ("DIGEST_CONTENT_MAX_INPUT_CHARS", "99", "must be at least 100"),
    ],
)
def test_settings_fail_closed_for_invalid_digest_values(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
    message: str,
) -> None:
    _base_env(monkeypatch)
    monkeypatch.setenv(name, value)

    with pytest.raises(RuntimeError, match=message):
        Settings.from_env()


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        (
            "DIGEST_DEFAULT_LOCAL_TIME",
            "9:00",
            "DIGEST_DEFAULT_LOCAL_TIME",
        ),
        (
            "DIGEST_DEFAULT_LOCAL_TIME",
            "09:00:00",
            "DIGEST_DEFAULT_LOCAL_TIME",
        ),
        (
            "DIGEST_DEFAULT_TIMEZONE",
            "UTC+02",
            "DIGEST_DEFAULT_TIMEZONE",
        ),
        (
            "DIGEST_MATERIAL_UPDATE_POLICY_VERSION",
            "   ",
            "DIGEST_MATERIAL_UPDATE_POLICY_VERSION",
        ),
        ("DIGEST_RENDERER_VERSION", "   ", "DIGEST_RENDERER_VERSION"),
    ],
)
def test_settings_reject_invalid_digest_text_settings(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
    message: str,
) -> None:
    _base_env(monkeypatch)
    monkeypatch.setenv(name, value)

    with pytest.raises((RuntimeError, ValueError), match=message):
        Settings.from_env()


def test_settings_reject_digest_claim_maximum_below_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _base_env(monkeypatch)
    monkeypatch.setenv("DIGEST_CLAIM_BATCH_SIZE", "101")
    monkeypatch.setenv("DIGEST_MAX_CLAIMS_PER_TICK", "100")

    with pytest.raises(RuntimeError, match="must not be below"):
        Settings.from_env()


def test_settings_reject_digest_retry_maximum_below_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _base_env(monkeypatch)
    monkeypatch.setenv("DIGEST_RETRY_BASE_SECONDS", "901")
    monkeypatch.setenv("DIGEST_RETRY_MAX_SECONDS", "900")

    with pytest.raises(RuntimeError, match="must not be below"):
        Settings.from_env()


def test_settings_reject_digest_candidate_limit_above_ranking_maximum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _base_env(monkeypatch)
    monkeypatch.setenv("RANKING_MAXIMUM_CANDIDATES", "50")
    monkeypatch.setenv("DIGEST_CANDIDATE_LIMIT", "51")

    with pytest.raises(RuntimeError, match="DIGEST_CANDIDATE_LIMIT"):
        Settings.from_env()


def test_settings_requires_history_days_to_cover_partial_freshness_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _base_env(monkeypatch)
    monkeypatch.setenv("RANKING_FRESHNESS_HORIZON_SECONDS", "259201")
    monkeypatch.setenv("DIGEST_HISTORY_RETENTION_DAYS", "3")

    with pytest.raises(RuntimeError, match="freshness horizon"):
        Settings.from_env()
