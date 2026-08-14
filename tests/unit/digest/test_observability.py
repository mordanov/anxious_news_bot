"""Observability tests - redaction and safe fields."""

from unittest.mock import patch
from uuid import uuid4

from anxious_news_bot.digest.observability import (
    _safe_hash,
    _sanitize,
    log_digest_event,
)


class TestSanitize:
    def test_drops_forbidden_fields(self):
        result = _sanitize({"prompt": "secret", "status": "ok"})
        assert "prompt" not in result
        assert result["status"] == "ok"

    def test_drops_text_field(self):
        result = _sanitize({"text": "body", "count": 5})
        assert "text" not in result
        assert result["count"] == 5

    def test_truncates_long_values(self):
        result = _sanitize({"field": "x" * 300})
        assert len(result["field"]) <= 203

    def test_recursively_drops_prompts_content_and_provider_responses(self):
        result = _sanitize(
            {
                "nested": {
                    "article_text": "private",
                    "provider_response": "private",
                    "duration_ms": 15,
                }
            }
        )
        assert result == {"nested": {"duration_ms": 15}}


class TestSafeHash:
    def test_produces_short_hash(self):
        result = _safe_hash(uuid4())
        assert len(result) == 16

    def test_none_returns_none(self):
        assert _safe_hash(None) is None


class TestLogEvent:
    def test_hashes_occurrence_and_user_without_logging_raw_values(self):
        user_id = uuid4()
        occurrence_key = "2026-01-15/09:00/Europe/Madrid"

        with patch("anxious_news_bot.digest.observability.LOGGER.log") as logger_log:
            log_digest_event(
                "test_event",
                execution_id=uuid4(),
                user_id=user_id,
                occurrence_key=occurrence_key,
                phase="test",
                status="ok",
                fields={"duration_ms": 12, "prompt": "secret"},
            )

        context = logger_log.call_args.kwargs["extra"]["digest"]
        rendered = str(context)
        assert str(user_id) not in rendered
        assert occurrence_key not in rendered
        assert context["user_id_hash"]
        assert context["occurrence_key_hash"]
        assert "prompt" not in context
        assert context["duration_ms"] == 12
