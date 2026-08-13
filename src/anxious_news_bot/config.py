from __future__ import annotations

import math
import os
from dataclasses import dataclass
from urllib.parse import urlsplit


def _text(name: str, default: str = "", *, required: bool = False) -> str:
    value = os.getenv(name, default).strip()
    if required and not value:
        raise RuntimeError(f"{name} is required")
    return value


def _integer(name: str, default: int, *, minimum: int = 1) -> int:
    raw = _text(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if value < minimum:
        raise RuntimeError(f"{name} must be at least {minimum}")
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
    database_url: str = "postgresql+psycopg://localhost/anxious_news"
    news_scheduler_interval_seconds: int = 60
    news_fetch_timeout_seconds: float = 20.0
    news_fetch_retry_attempts: int = 3
    news_max_concurrency: int = 5
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
    preferences_history_question_limit: int = 50
    preferences_duplicate_review_threshold: float = 0.72
    preferences_repetition_threshold: float = 0.85
    preferences_questionnaire_retention_days: int = 365
    preferences_change_history_retention_days: int = 0
    preferences_retention_scan_interval_seconds: int = 86_400
    preferences_retention_batch_size: int = 500

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

        settings = cls(
            telegram_bot_token=_text("TELEGRAM_BOT_TOKEN", required=True),
            database_url=_database_url(),
            news_scheduler_interval_seconds=_integer(
                "NEWS_SCHEDULER_INTERVAL_SECONDS", 60
            ),
            news_fetch_timeout_seconds=_number(
                "NEWS_FETCH_TIMEOUT_SECONDS",
                20.0,
                minimum=0.0,
                inclusive_minimum=False,
            ),
            news_fetch_retry_attempts=_integer("NEWS_FETCH_RETRY_ATTEMPTS", 3),
            news_max_concurrency=_integer("NEWS_MAX_CONCURRENCY", 5),
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
            preferences_model_base_url=_text("PREFERENCES_MODEL_BASE_URL"),
            preferences_model_api_key=_text("PREFERENCES_MODEL_API_KEY"),
            preferences_model_name=_text("PREFERENCES_MODEL_NAME"),
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
            preferences_history_question_limit=_integer(
                "PREFERENCES_HISTORY_QUESTION_LIMIT", 50
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
        model_values = (
            self.preferences_model_base_url,
            self.preferences_model_api_key,
            self.preferences_model_name,
        )
        if any(model_values) and not all(model_values):
            raise RuntimeError(
                "PREFERENCES_MODEL_BASE_URL, PREFERENCES_MODEL_API_KEY, and "
                "PREFERENCES_MODEL_NAME must be configured together"
            )
        if self.preferences_model_base_url:
            parsed = urlsplit(self.preferences_model_base_url)
            if parsed.scheme != "https" or not parsed.netloc:
                raise RuntimeError("PREFERENCES_MODEL_BASE_URL must be an HTTPS URL")
