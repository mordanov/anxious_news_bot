import json
import logging

from anxious_news_bot.news.errors import DiagnosticContext


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
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
