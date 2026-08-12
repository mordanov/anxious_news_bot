from __future__ import annotations

import json
import logging

from anxious_news_bot.logging import JsonFormatter
from anxious_news_bot.news.observability import log_news_event, sanitized_fields


class RecordHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def test_sanitized_fields_redact_credentials_and_nested_raw_payloads() -> None:
    fields = sanitized_fields(
        {
            "authorization": "Bearer credential-value",
            "database_credential": "database-password",
            "details": {
                "password": "nested-password",
                "raw_payload": {"article": "private article body"},
            },
        }
    )

    rendered = repr(fields)
    assert "credential-value" not in rendered
    assert "database-password" not in rendered
    assert "nested-password" not in rendered
    assert "private article body" not in rendered
    assert rendered.count("<redacted>") == 4


def test_sanitized_fields_remove_url_userinfo_secret_queries_and_fragments() -> None:
    fields = sanitized_fields(
        {
            "source_url": (
                "https://feed-user:feed-password@example.com/rss?"
                "api_key=query-secret&region=es#private-fragment"
            ),
            "nested": {
                "callback": "https://example.com/hook?token=nested-secret&ok=1"
            },
        }
    )

    rendered = repr(fields)
    for secret in (
        "feed-user",
        "feed-password",
        "query-secret",
        "private-fragment",
        "nested-secret",
    ):
        assert secret not in rendered
    assert "region=es" in fields["source_url"]
    assert "ok=1" in fields["nested"]["callback"]


def test_structured_log_record_never_contains_raw_payload_or_credentials() -> None:
    logger = logging.getLogger("tests.news.observability")
    logger.propagate = False
    logger.setLevel(logging.INFO)
    handler = RecordHandler()
    logger.addHandler(handler)
    try:
        log_news_event(
            logger,
            "source_processed",
            fields={
                "raw_payload": {"content": "unnecessary article content"},
                "credential_ref": "secret-reference",
                "endpoint_url": "https://example.com/feed?access_token=url-secret",
                "accepted_count": 2,
            },
        )
    finally:
        logger.removeHandler(handler)

    assert len(handler.records) == 1
    structured = handler.records[0].news
    rendered = repr(structured)
    assert structured["accepted_count"] == 2
    assert "unnecessary article content" not in rendered
    assert "secret-reference" not in rendered
    assert "url-secret" not in rendered


def test_all_api_key_and_generic_credential_variants_are_redacted() -> None:
    secrets = {
        "api_key": "one",
        "apikey": "two",
        "x-api-key": "three",
        "X_API_KEY": "four",
        "credentialHeader": "five",
        "service-key": "six",
        "request_headers": {"X-Custom-Credential": "seven"},
    }

    rendered = repr(sanitized_fields(secrets))

    for secret in secrets.values():
        if isinstance(secret, str):
            assert secret not in rendered
    assert "seven" not in rendered
    assert rendered.count("<redacted>") == len(secrets)


def test_json_formatter_applies_central_redaction_to_direct_news_context() -> None:
    record = logging.LogRecord(
        "test",
        logging.INFO,
        __file__,
        1,
        "message",
        (),
        None,
    )
    record.news = {
        "apikey": "direct-secret",
        "headers": {"x-api-key": "nested-secret"},
        "accepted_count": 2,
    }

    payload = json.loads(JsonFormatter().format(record))

    assert payload["news"]["apikey"] == "<redacted>"
    assert payload["news"]["headers"] == "<redacted>"
    assert payload["news"]["accepted_count"] == 2
