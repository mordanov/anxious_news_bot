import json
import logging

from anxious_news_bot.digest.observability import _sanitize as sanitized_digest_fields
from anxious_news_bot.news.errors import DiagnosticContext
from anxious_news_bot.ranking.observability import (
    sanitized_fields as sanitized_ranking_fields,
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        news_context = getattr(record, "news", None)
        if isinstance(news_context, dict):
            payload["news"] = DiagnosticContext.sanitized(news_context).as_dict()
        ranking_context = getattr(record, "ranking", None)
        if isinstance(ranking_context, dict):
            payload["ranking"] = sanitized_ranking_fields(ranking_context)
        preference_context = getattr(record, "preference", None)
        if isinstance(preference_context, dict):
            payload["preference"] = DiagnosticContext.sanitized(
                preference_context
            ).as_dict()
        digest_context = getattr(record, "digest", None)
        if isinstance(digest_context, dict):
            payload["digest"] = sanitized_digest_fields(digest_context)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    logging.getLogger("httpx").setLevel(logging.WARNING)
