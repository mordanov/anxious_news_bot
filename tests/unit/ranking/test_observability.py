from __future__ import annotations

import json
import logging
from uuid import uuid4

from anxious_news_bot.logging import JsonFormatter
from anxious_news_bot.ranking.observability import (
    log_ranking_event,
    sanitized_fields,
)


class RecordHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def test_sanitized_fields_drop_raw_explicit_text_article_content_and_profile_snapshots() -> (
    None
):
    fields = sanitized_fields(
        {
            "statement": "Please send more Kirov city news",
            "raw_text": "Please send more Kirov city news",
            "article_content": "Full article body that must never be logged.",
            "prompt": "Secret evaluator prompt",
            "raw_response": {"content": "untrusted model output"},
            "profile_snapshot": {"parameters": ["private preference state"]},
            "api_key": "credential-value",
            "relevance_count": 2,
        }
    )

    rendered = repr(fields)
    for secret in (
        "Please send more Kirov city news",
        "Full article body that must never be logged.",
        "Secret evaluator prompt",
        "untrusted model output",
        "private preference state",
        "credential-value",
    ):
        assert secret not in rendered
    assert fields["relevance_count"] == 2
    assert "statement" not in fields
    assert "raw_text" not in fields
    assert "prompt" not in fields
    assert "profile_snapshot" not in fields


def test_structured_ranking_log_records_never_include_credentials_or_raw_content() -> (
    None
):
    logger = logging.getLogger("anxious_news_bot.ranking.observability")
    logger.disabled = False
    logger.propagate = False
    logger.setLevel(logging.INFO)
    handler = RecordHandler()
    logger.addHandler(handler)
    try:
        log_ranking_event(
            "evaluation_validation",
            stage="evaluation",
            status="failed",
            user_id=uuid4(),
            article_id=uuid4(),
            error_code="invalid_output",
            fields={
                "statement": "Please send more Kirov city news",
                "article_text": "private article text",
                "raw_response": {"content": "private model output"},
                "provider_api_key": "top-secret",
                "profile_revision": 3,
            },
        )
    finally:
        logger.removeHandler(handler)

    assert len(handler.records) == 1
    structured = handler.records[0].ranking
    rendered = repr(structured)
    assert structured["profile_revision"] == 3
    for secret in (
        "Please send more Kirov city news",
        "private article text",
        "private model output",
        "top-secret",
    ):
        assert secret not in rendered


def test_json_formatter_includes_sanitized_ranking_context() -> None:
    record = logging.LogRecord(
        "test",
        logging.INFO,
        __file__,
        1,
        "message",
        (),
        None,
    )
    record.ranking = {
        "statement": "Please send more Kirov city news",
        "raw_response": {"content": "secret"},
        "api_key": "direct-secret",
        "selected_count": 2,
    }

    payload = json.loads(JsonFormatter().format(record))

    assert payload["ranking"]["selected_count"] == 2
    assert "statement" not in payload["ranking"]
    assert "raw_response" not in payload["ranking"]
    assert payload["ranking"]["api_key"] == "<redacted>"
