"""Logging formatter tests including digest context."""

import json
import logging

from anxious_news_bot.logging import JsonFormatter


class TestJsonFormatterDigest:
    def test_digest_context_included(self):
        formatter = JsonFormatter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "test_msg", (), None)
        record.digest = {"event": "test", "status": "ok"}
        output = formatter.format(record)
        parsed = json.loads(output)
        assert "digest" in parsed
        assert parsed["digest"]["event"] == "test"

    def test_no_digest_context(self):
        formatter = JsonFormatter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "test_msg", (), None)
        output = formatter.format(record)
        parsed = json.loads(output)
        assert "digest" not in parsed

    def test_digest_context_redacts_content_even_for_direct_log_records(self):
        formatter = JsonFormatter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
        record.digest = {
            "status": "failed",
            "prompt": "secret prompt",
            "nested": {"article_text": "private", "duration_ms": 25},
        }

        parsed = json.loads(formatter.format(record))

        assert parsed["digest"] == {
            "status": "failed",
            "nested": {"duration_ms": 25},
        }
