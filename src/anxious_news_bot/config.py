from __future__ import annotations

import math
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit


def _text(name: str, default: str = "", *, required: bool = False) -> str:
    value = os.getenv(name, default).strip()
    if required and not value:
        raise RuntimeError(f"{name} is required")
    return value


def _integer(
    name: str,
    default: int,
    *,
    minimum: int = 1,
    maximum: int | None = None,
) -> int:
    raw = _text(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if value < minimum:
        raise RuntimeError(f"{name} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise RuntimeError(f"{name} must be at most {maximum}")
    return value


def _number(
    name: str,
    default: float,
    *,
    minimum: float = 0.0,
    maximum: float | None = None,
    inclusive_minimum: bool = True,
) -> float:
    raw = _text(name, str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a number") from exc
    minimum_invalid = value < minimum if inclusive_minimum else value <= minimum
    if not math.isfinite(value) or minimum_invalid:
        qualifier = "at least" if inclusive_minimum else "greater than"
        raise RuntimeError(f"{name} must be {qualifier} {minimum}")
    if maximum is not None and value > maximum:
        raise RuntimeError(f"{name} must be at most {maximum}")
    return value


def _threshold(name: str, default: float) -> float:
    return _number(name, default, minimum=0.0, maximum=1.0)


def _decimal(
    name: str,
    default: str,
    *,
    minimum: str,
    maximum: str | None = None,
    places: int | None = None,
) -> Decimal:
    raw = _text(name, default)
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise RuntimeError(f"{name} must be a decimal") from exc
    if not value.is_finite():
        raise RuntimeError(f"{name} must be finite")
    lower = Decimal(minimum)
    if value < lower:
        raise RuntimeError(f"{name} must be at least {minimum}")
    if maximum is not None and value > Decimal(maximum):
        raise RuntimeError(f"{name} must be at most {maximum}")
    if places is not None and value.as_tuple().exponent != -places:
        raise RuntimeError(f"{name} must use exactly {places} decimal places")
    return value


def _database_url() -> str:
    value = _text(
        "DATABASE_URL",
        "postgresql+psycopg://localhost/anxious_news",
    )
    parsed = urlsplit(value.replace("postgresql+psycopg://", "postgresql://", 1))
    if parsed.scheme not in {"postgresql", "postgres"} or not parsed.path.strip("/"):
        raise RuntimeError("DATABASE_URL must identify a PostgreSQL database")
    if value.startswith("postgres://"):
        return f"postgresql+psycopg://{value.removeprefix('postgres://')}"
    if value.startswith("postgresql://"):
        return f"postgresql+psycopg://{value.removeprefix('postgresql://')}"
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    telegram_bot_token: str
    telegram_connect_timeout_seconds: float = 30.0
    telegram_read_timeout_seconds: float = 30.0
    telegram_write_timeout_seconds: float = 30.0
    telegram_pool_timeout_seconds: float = 10.0
    database_url: str = "postgresql+psycopg://localhost/anxious_news"
    news_scheduler_interval_seconds: int = 300
    news_fetch_timeout_seconds: float = 20.0
    news_fetch_retry_attempts: int = 3
    news_max_concurrency: int = 5
    news_command_candidate_limit: int = 30
    news_command_evaluation_concurrency: int = 5
    news_url_policy_version: str = "1.0"
    news_tracking_parameters: tuple[str, ...] = (
        "fbclid",
        "gclid",
        "mc_cid",
        "mc_eid",
        "utm_campaign",
        "utm_content",
        "utm_medium",
        "utm_source",
        "utm_term",
    )
    news_raw_payload_retention_days: int = 7
    news_near_duplicate_title_threshold: float = 0.85
    news_near_duplicate_content_threshold: float = 0.80
    news_near_duplicate_review_threshold: float = 0.72
    news_event_window_hours: int = 48
    news_event_title_weight: float = 0.50
    news_event_content_weight: float = 0.30
    news_event_topic_weight: float = 0.10
    news_event_geography_weight: float = 0.10
    news_event_anchor_threshold: float = 0.55
    news_event_assignment_threshold: float = 0.62
    news_event_review_threshold: float = 0.52
    preferences_model_base_url: str = ""
    preferences_model_api_key: str = ""
    preferences_model_name: str = ""
    preferences_model_timeout_seconds: float = 30.0
    preferences_model_retry_attempts: int = 2
    preferences_model_max_response_bytes: int = 262_144
    preferences_questionnaire_generation_attempts: int = 3
    preferences_interpretation_attempts: int = 2
    preferences_history_question_limit: int = 50
    preferences_explicit_request_max_length: int = 1000
    preferences_explicit_history_limit: int = 20
    preferences_explicit_stale_retry_limit: int = 1
    preferences_duplicate_review_threshold: float = 0.72
    preferences_repetition_threshold: float = 0.85
    preferences_questionnaire_retention_days: int = 365
    preferences_change_history_retention_days: int = 0
    preferences_retention_scan_interval_seconds: int = 86_400
    preferences_retention_batch_size: int = 500
    ranking_model_base_url: str = ""
    ranking_model_api_key: str = ""
    ranking_model_name: str = ""
    ranking_model_timeout_seconds: float = 30.0
    ranking_model_retry_attempts: int = 3
    ranking_model_max_response_bytes: int = 262_144
    ranking_configuration_version: str = "1.0"
    ranking_tie_policy_version: str = "1.0"
    ranking_retention_policy_version: str = "1.0"
    ranking_personal_coefficient: Decimal = Decimal("0.45000")
    ranking_importance_coefficient: Decimal = Decimal("0.20000")
    ranking_freshness_coefficient: Decimal = Decimal("0.15000")
    ranking_quality_coefficient: Decimal = Decimal("0.10000")
    ranking_novelty_coefficient: Decimal = Decimal("0.10000")
    ranking_freshness_horizon_seconds: int = 259_200
    ranking_future_tolerance_seconds: int = 300
    ranking_minimum_source_quality: Decimal = Decimal("0.35000")
    ranking_maximum_candidates: int = 500
    ranking_event_cap: int = 2
    ranking_topic_cap: int = 3
    ranking_source_cap: int = 3
    ranking_explicit_weight_threshold: Decimal = Decimal("0.75")
    ranking_explicit_relevance_threshold: Decimal = Decimal("0.6000")
    ranking_explanation_contribution_limit: int = 3
    ranking_evaluation_retry_attempts: int = 3
    ranking_raw_response_retention_days: int = 30
    ranking_detail_retention_days: int = 90
    ranking_retention_batch_size: int = 500
    ranking_retention_scan_interval_seconds: int = 86_400
    digest_scan_interval_seconds: int = 60
    digest_claim_batch_size: int = 100
    digest_max_claims_per_tick: int = 1000
    digest_claim_time_budget_seconds: int = 30
    digest_user_concurrency: int = 5
    digest_default_count: int = 10
    digest_default_local_time: str = "09:00"
    digest_default_timezone: str = "UTC"
    digest_candidate_limit: int = 100
    digest_max_attempts: int = 3
    digest_retry_base_seconds: int = 60
    digest_retry_max_seconds: int = 900
    digest_material_update_policy_version: str = "1.0"
    digest_material_update_novelty_threshold: Decimal = Decimal("0.7000")
    digest_material_update_max_content_similarity: Decimal = Decimal("0.60000")
    digest_material_update_min_text_chars: int = 200
    digest_history_retention_days: int = 30
    digest_content_max_input_chars: int = 2000
    digest_renderer_version: str = "1.0"

    @classmethod
    def from_env(cls) -> Settings:
        tracking_parameters = tuple(
            sorted(
                {
                    item.strip().lower()
                    for item in _text(
                        "NEWS_TRACKING_PARAMETERS",
                        "fbclid,gclid,mc_cid,mc_eid,utm_campaign,utm_content,"
                        "utm_medium,utm_source,utm_term",
                    ).split(",")
                    if item.strip()
                }
            )
        )
        if not tracking_parameters:
            raise RuntimeError("NEWS_TRACKING_PARAMETERS must not be empty")

        preferences_model_base_url = _text("PREFERENCES_MODEL_BASE_URL")
        preferences_model_api_key = _text("PREFERENCES_MODEL_API_KEY")
        preferences_model_name = _text("PREFERENCES_MODEL_NAME")
        ranking_model_base_url = (
            _text("RANKING_MODEL_BASE_URL") or preferences_model_base_url
        )
        ranking_model_api_key = (
            _text("RANKING_MODEL_API_KEY") or preferences_model_api_key
        )

        settings = cls(
            telegram_bot_token=_text("TELEGRAM_BOT_TOKEN", required=True),
            telegram_connect_timeout_seconds=_number(
                "TELEGRAM_CONNECT_TIMEOUT_SECONDS", 30.0, minimum=0.0,
                inclusive_minimum=False,
            ),
            telegram_read_timeout_seconds=_number(
                "TELEGRAM_READ_TIMEOUT_SECONDS", 30.0, minimum=0.0,
                inclusive_minimum=False,
            ),
            telegram_write_timeout_seconds=_number(
                "TELEGRAM_WRITE_TIMEOUT_SECONDS", 30.0, minimum=0.0,
                inclusive_minimum=False,
            ),
            telegram_pool_timeout_seconds=_number(
                "TELEGRAM_POOL_TIMEOUT_SECONDS", 10.0, minimum=0.0,
                inclusive_minimum=False,
            ),
            database_url=_database_url(),
            news_scheduler_interval_seconds=_integer(
                "NEWS_SCHEDULER_INTERVAL_SECONDS", 300
            ),
            news_fetch_timeout_seconds=_number(
                "NEWS_FETCH_TIMEOUT_SECONDS",
                20.0,
                minimum=0.0,
                inclusive_minimum=False,
            ),
            news_fetch_retry_attempts=_integer("NEWS_FETCH_RETRY_ATTEMPTS", 3),
            news_max_concurrency=_integer("NEWS_MAX_CONCURRENCY", 5),
            news_command_candidate_limit=_integer(
                "NEWS_COMMAND_CANDIDATE_LIMIT",
                30,
                minimum=10,
                maximum=500,
            ),
            news_command_evaluation_concurrency=_integer(
                "NEWS_COMMAND_EVALUATION_CONCURRENCY",
                5,
                maximum=50,
            ),
            news_url_policy_version=_text("NEWS_URL_POLICY_VERSION", "1.0"),
            news_tracking_parameters=tracking_parameters,
            news_raw_payload_retention_days=_integer(
                "NEWS_RAW_PAYLOAD_RETENTION_DAYS", 7, minimum=0
            ),
            news_near_duplicate_title_threshold=_threshold(
                "NEWS_NEAR_DUPLICATE_TITLE_THRESHOLD", 0.85
            ),
            news_near_duplicate_content_threshold=_threshold(
                "NEWS_NEAR_DUPLICATE_CONTENT_THRESHOLD", 0.80
            ),
            news_near_duplicate_review_threshold=_threshold(
                "NEWS_NEAR_DUPLICATE_REVIEW_THRESHOLD", 0.72
            ),
            news_event_window_hours=_integer("NEWS_EVENT_WINDOW_HOURS", 48),
            news_event_title_weight=_threshold("NEWS_EVENT_TITLE_WEIGHT", 0.50),
            news_event_content_weight=_threshold("NEWS_EVENT_CONTENT_WEIGHT", 0.30),
            news_event_topic_weight=_threshold("NEWS_EVENT_TOPIC_WEIGHT", 0.10),
            news_event_geography_weight=_threshold("NEWS_EVENT_GEOGRAPHY_WEIGHT", 0.10),
            news_event_anchor_threshold=_threshold("NEWS_EVENT_ANCHOR_THRESHOLD", 0.55),
            news_event_assignment_threshold=_threshold(
                "NEWS_EVENT_ASSIGNMENT_THRESHOLD", 0.62
            ),
            news_event_review_threshold=_threshold("NEWS_EVENT_REVIEW_THRESHOLD", 0.52),
            preferences_model_base_url=preferences_model_base_url,
            preferences_model_api_key=preferences_model_api_key,
            preferences_model_name=preferences_model_name,
            preferences_model_timeout_seconds=_number(
                "PREFERENCES_MODEL_TIMEOUT_SECONDS",
                30.0,
                minimum=0.0,
                inclusive_minimum=False,
            ),
            preferences_model_retry_attempts=_integer(
                "PREFERENCES_MODEL_RETRY_ATTEMPTS", 2
            ),
            preferences_model_max_response_bytes=_integer(
                "PREFERENCES_MODEL_MAX_RESPONSE_BYTES", 262_144
            ),
            preferences_questionnaire_generation_attempts=_integer(
                "PREFERENCES_QUESTIONNAIRE_GENERATION_ATTEMPTS",
                3,
                maximum=5,
            ),
            preferences_interpretation_attempts=_integer(
                "PREFERENCES_INTERPRETATION_ATTEMPTS",
                2,
                maximum=5,
            ),
            preferences_history_question_limit=_integer(
                "PREFERENCES_HISTORY_QUESTION_LIMIT", 50
            ),
            preferences_explicit_request_max_length=_integer(
                "PREFERENCES_EXPLICIT_REQUEST_MAX_LENGTH", 1000
            ),
            preferences_explicit_history_limit=_integer(
                "PREFERENCES_EXPLICIT_HISTORY_LIMIT", 20
            ),
            preferences_explicit_stale_retry_limit=_integer(
                "PREFERENCES_EXPLICIT_STALE_RETRY_LIMIT",
                1,
                minimum=0,
                maximum=1,
            ),
            preferences_duplicate_review_threshold=_threshold(
                "PREFERENCES_DUPLICATE_REVIEW_THRESHOLD", 0.72
            ),
            preferences_repetition_threshold=_threshold(
                "PREFERENCES_REPETITION_THRESHOLD", 0.85
            ),
            preferences_questionnaire_retention_days=_integer(
                "PREFERENCES_QUESTIONNAIRE_RETENTION_DAYS", 365, minimum=0
            ),
            preferences_change_history_retention_days=_integer(
                "PREFERENCES_CHANGE_HISTORY_RETENTION_DAYS", 0, minimum=0
            ),
            preferences_retention_scan_interval_seconds=_integer(
                "PREFERENCES_RETENTION_SCAN_INTERVAL_SECONDS", 86_400
            ),
            preferences_retention_batch_size=_integer(
                "PREFERENCES_RETENTION_BATCH_SIZE", 500
            ),
            ranking_model_base_url=ranking_model_base_url,
            ranking_model_api_key=ranking_model_api_key,
            ranking_model_name=_text("RANKING_MODEL_NAME"),
            ranking_model_timeout_seconds=_number(
                "RANKING_MODEL_TIMEOUT_SECONDS",
                30.0,
                minimum=0.0,
                inclusive_minimum=False,
            ),
            ranking_model_retry_attempts=_integer("RANKING_MODEL_RETRY_ATTEMPTS", 3),
            ranking_model_max_response_bytes=_integer(
                "RANKING_MODEL_MAX_RESPONSE_BYTES", 262_144
            ),
            ranking_configuration_version=_text("RANKING_CONFIGURATION_VERSION", "1.0"),
            ranking_tie_policy_version=_text("RANKING_TIE_POLICY_VERSION", "1.0"),
            ranking_retention_policy_version=_text(
                "RANKING_RETENTION_POLICY_VERSION", "1.0"
            ),
            ranking_personal_coefficient=_decimal(
                "RANKING_PERSONAL_COEFFICIENT",
                "0.45000",
                minimum="0.00000",
                maximum="1.00000",
                places=5,
            ),
            ranking_importance_coefficient=_decimal(
                "RANKING_IMPORTANCE_COEFFICIENT",
                "0.20000",
                minimum="0.00000",
                maximum="1.00000",
                places=5,
            ),
            ranking_freshness_coefficient=_decimal(
                "RANKING_FRESHNESS_COEFFICIENT",
                "0.15000",
                minimum="0.00000",
                maximum="1.00000",
                places=5,
            ),
            ranking_quality_coefficient=_decimal(
                "RANKING_QUALITY_COEFFICIENT",
                "0.10000",
                minimum="0.00000",
                maximum="1.00000",
                places=5,
            ),
            ranking_novelty_coefficient=_decimal(
                "RANKING_NOVELTY_COEFFICIENT",
                "0.10000",
                minimum="0.00000",
                maximum="1.00000",
                places=5,
            ),
            ranking_freshness_horizon_seconds=_integer(
                "RANKING_FRESHNESS_HORIZON_SECONDS", 259_200
            ),
            ranking_future_tolerance_seconds=_integer(
                "RANKING_FUTURE_TOLERANCE_SECONDS", 300, minimum=0
            ),
            ranking_minimum_source_quality=_decimal(
                "RANKING_MINIMUM_SOURCE_QUALITY",
                "0.35000",
                minimum="0.00000",
                maximum="1.00000",
                places=5,
            ),
            ranking_maximum_candidates=_integer(
                "RANKING_MAXIMUM_CANDIDATES", 500, maximum=500
            ),
            ranking_event_cap=_integer("RANKING_EVENT_CAP", 2),
            ranking_topic_cap=_integer("RANKING_TOPIC_CAP", 3),
            ranking_source_cap=_integer("RANKING_SOURCE_CAP", 3),
            ranking_explicit_weight_threshold=_decimal(
                "RANKING_EXPLICIT_WEIGHT_THRESHOLD",
                "0.75",
                minimum="0.00",
                maximum="1.00",
                places=2,
            ),
            ranking_explicit_relevance_threshold=_decimal(
                "RANKING_EXPLICIT_RELEVANCE_THRESHOLD",
                "0.6000",
                minimum="0.0000",
                maximum="1.0000",
                places=4,
            ),
            ranking_explanation_contribution_limit=_integer(
                "RANKING_EXPLANATION_CONTRIBUTION_LIMIT", 3, maximum=10
            ),
            ranking_evaluation_retry_attempts=_integer(
                "RANKING_EVALUATION_RETRY_ATTEMPTS", 3
            ),
            ranking_raw_response_retention_days=_integer(
                "RANKING_RAW_RESPONSE_RETENTION_DAYS", 30, minimum=0
            ),
            ranking_detail_retention_days=_integer(
                "RANKING_DETAIL_RETENTION_DAYS", 90, minimum=0
            ),
            ranking_retention_batch_size=_integer("RANKING_RETENTION_BATCH_SIZE", 500),
            ranking_retention_scan_interval_seconds=_integer(
                "RANKING_RETENTION_SCAN_INTERVAL_SECONDS",
                86_400,
                minimum=1,
            ),
            digest_scan_interval_seconds=_integer(
                "DIGEST_SCAN_INTERVAL_SECONDS", 60, maximum=86_400
            ),
            digest_claim_batch_size=_integer(
                "DIGEST_CLAIM_BATCH_SIZE", 100, minimum=1, maximum=1_000
            ),
            digest_max_claims_per_tick=_integer(
                "DIGEST_MAX_CLAIMS_PER_TICK", 1000, minimum=1, maximum=10_000
            ),
            digest_claim_time_budget_seconds=_integer(
                "DIGEST_CLAIM_TIME_BUDGET_SECONDS", 30, minimum=1, maximum=300
            ),
            digest_user_concurrency=_integer(
                "DIGEST_USER_CONCURRENCY", 5, minimum=1, maximum=50
            ),
            digest_default_count=_integer(
                "DIGEST_DEFAULT_COUNT", 10, minimum=5, maximum=20
            ),
            digest_default_local_time=_text("DIGEST_DEFAULT_LOCAL_TIME", "09:00"),
            digest_default_timezone=_text("DIGEST_DEFAULT_TIMEZONE", "UTC"),
            digest_candidate_limit=_integer(
                "DIGEST_CANDIDATE_LIMIT", 100, minimum=20, maximum=500
            ),
            digest_max_attempts=_integer(
                "DIGEST_MAX_ATTEMPTS", 3, minimum=1, maximum=10
            ),
            digest_retry_base_seconds=_integer(
                "DIGEST_RETRY_BASE_SECONDS", 60, minimum=1, maximum=86_400
            ),
            digest_retry_max_seconds=_integer(
                "DIGEST_RETRY_MAX_SECONDS", 900, minimum=1, maximum=86_400
            ),
            digest_material_update_policy_version=_text(
                "DIGEST_MATERIAL_UPDATE_POLICY_VERSION", "1.0"
            ),
            digest_material_update_novelty_threshold=_decimal(
                "DIGEST_MATERIAL_UPDATE_NOVELTY_THRESHOLD",
                "0.7000",
                minimum="0.0000",
                maximum="1.0000",
                places=4,
            ),
            digest_material_update_max_content_similarity=_decimal(
                "DIGEST_MATERIAL_UPDATE_MAX_CONTENT_SIMILARITY",
                "0.60000",
                minimum="0.00000",
                maximum="1.00000",
                places=5,
            ),
            digest_material_update_min_text_chars=_integer(
                "DIGEST_MATERIAL_UPDATE_MIN_TEXT_CHARS",
                200,
                minimum=1,
                maximum=100_000,
            ),
            digest_history_retention_days=_integer(
                "DIGEST_HISTORY_RETENTION_DAYS", 30, minimum=1, maximum=3_650
            ),
            digest_content_max_input_chars=_integer(
                "DIGEST_CONTENT_MAX_INPUT_CHARS",
                2000,
                minimum=100,
                maximum=10_000,
            ),
            digest_renderer_version=_text("DIGEST_RENDERER_VERSION", "1.0"),
        )
        settings._validate()
        return settings

    def _validate(self) -> None:
        if not self.news_url_policy_version:
            raise RuntimeError("NEWS_URL_POLICY_VERSION must not be empty")
        if self.news_near_duplicate_review_threshold > min(
            self.news_near_duplicate_title_threshold,
            self.news_near_duplicate_content_threshold,
        ):
            raise RuntimeError(
                "NEWS_NEAR_DUPLICATE_REVIEW_THRESHOLD must not exceed "
                "duplicate thresholds"
            )
        event_weight_sum = sum(
            (
                self.news_event_title_weight,
                self.news_event_content_weight,
                self.news_event_topic_weight,
                self.news_event_geography_weight,
            )
        )
        if not math.isclose(event_weight_sum, 1.0, abs_tol=1e-9):
            raise RuntimeError("NEWS_EVENT_*_WEIGHT values must sum to 1.0")
        if self.news_event_review_threshold >= self.news_event_assignment_threshold:
            raise RuntimeError(
                "NEWS_EVENT_REVIEW_THRESHOLD must be lower than "
                "NEWS_EVENT_ASSIGNMENT_THRESHOLD"
            )
        preference_model_values = (
            self.preferences_model_base_url,
            self.preferences_model_api_key,
            self.preferences_model_name,
        )
        if any(preference_model_values) and not all(preference_model_values):
            raise RuntimeError(
                "PREFERENCES_MODEL_BASE_URL, PREFERENCES_MODEL_API_KEY, and "
                "PREFERENCES_MODEL_NAME must be configured together"
            )
        if self.preferences_model_base_url:
            parsed = urlsplit(self.preferences_model_base_url)
            if parsed.scheme != "https" or not parsed.netloc:
                raise RuntimeError("PREFERENCES_MODEL_BASE_URL must be an HTTPS URL")
        ranking_model_values = (
            self.ranking_model_base_url,
            self.ranking_model_api_key,
            self.ranking_model_name,
        )
        if any(ranking_model_values) and not all(ranking_model_values):
            raise RuntimeError(
                "RANKING_MODEL_BASE_URL, RANKING_MODEL_API_KEY, and "
                "RANKING_MODEL_NAME must be configured together"
            )
        if self.ranking_model_base_url:
            parsed = urlsplit(self.ranking_model_base_url)
            if parsed.scheme != "https" or not parsed.netloc:
                raise RuntimeError("RANKING_MODEL_BASE_URL must be an HTTPS URL")
        for field_name in (
            "ranking_configuration_version",
            "ranking_tie_policy_version",
            "ranking_retention_policy_version",
        ):
            if not getattr(self, field_name):
                raise RuntimeError(f"{field_name.upper()} must not be empty")
        coefficient_sum = sum(
            (
                self.ranking_personal_coefficient,
                self.ranking_importance_coefficient,
                self.ranking_freshness_coefficient,
                self.ranking_quality_coefficient,
                self.ranking_novelty_coefficient,
            ),
            start=Decimal("0.00000"),
        )
        if coefficient_sum != Decimal("1.00000"):
            raise RuntimeError(
                "RANKING_*_COEFFICIENT values must sum exactly to 1.00000"
            )
        if self.ranking_personal_coefficient < Decimal("0.40000"):
            raise RuntimeError("RANKING_PERSONAL_COEFFICIENT must be at least 0.40000")
        if self.digest_retry_max_seconds < self.digest_retry_base_seconds:
            raise RuntimeError(
                "DIGEST_RETRY_MAX_SECONDS must not be below DIGEST_RETRY_BASE_SECONDS"
            )
        if self.digest_max_claims_per_tick < self.digest_claim_batch_size:
            raise RuntimeError(
                "DIGEST_MAX_CLAIMS_PER_TICK must not be below DIGEST_CLAIM_BATCH_SIZE"
            )
        if not self.digest_material_update_policy_version:
            raise RuntimeError(
                "DIGEST_MATERIAL_UPDATE_POLICY_VERSION must not be empty"
            )
        if not self.digest_default_timezone:
            raise RuntimeError("DIGEST_DEFAULT_TIMEZONE must not be empty")
        from anxious_news_bot.digest.domain import validate_iana_timezone

        try:
            validate_iana_timezone(self.digest_default_timezone)
        except ValueError as exc:
            raise RuntimeError(f"DIGEST_DEFAULT_TIMEZONE is invalid: {exc}") from exc
        from anxious_news_bot.digest.domain import validate_local_time

        try:
            validate_local_time(self.digest_default_local_time)
        except ValueError as exc:
            raise RuntimeError(f"DIGEST_DEFAULT_LOCAL_TIME is invalid: {exc}") from exc
        if not self.digest_renderer_version:
            raise RuntimeError("DIGEST_RENDERER_VERSION must not be empty")
        if self.digest_candidate_limit > self.ranking_maximum_candidates:
            raise RuntimeError(
                "DIGEST_CANDIDATE_LIMIT must not exceed RANKING_MAXIMUM_CANDIDATES"
            )
        freshness_days = math.ceil(self.ranking_freshness_horizon_seconds / 86_400)
        if self.digest_history_retention_days < freshness_days:
            raise RuntimeError(
                "DIGEST_HISTORY_RETENTION_DAYS must cover the ranking freshness horizon"
            )
