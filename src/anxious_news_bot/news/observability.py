from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID

from anxious_news_bot.news.errors import DiagnosticContext, is_sensitive_key


def _sanitize_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return value[:240]
    hostname = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    query = urlencode(
        [
            (key, "<redacted>" if is_sensitive_key(key) else item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        ]
    )
    return urlunsplit((parsed.scheme, f"{hostname}{port}", parsed.path, query, ""))


def _sanitize_urls(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return _sanitize_url(value)
    if isinstance(value, dict):
        return {key: _sanitize_urls(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_urls(item) for item in value]
    return value


def sanitized_fields(fields: Mapping[str, Any] | None) -> dict[str, Any]:
    sanitized = _sanitize_urls(DiagnosticContext.sanitized(fields).as_dict())
    for key, value in tuple(sanitized.items()):
        if isinstance(value, str) and (
            "url" in key.lower() or value.startswith(("http://", "https://"))
        ):
            sanitized[key] = _sanitize_url(value)
    return sanitized


def log_news_event(
    logger: logging.Logger,
    event: str,
    *,
    cycle_id: UUID | str | None = None,
    source_id: UUID | str | None = None,
    article_id: UUID | str | None = None,
    stage: str | None = None,
    status: str | None = None,
    fields: Mapping[str, Any] | None = None,
    level: int = logging.INFO,
) -> None:
    context: dict[str, Any] = {
        "event": event[:100],
        "cycle_id": str(cycle_id) if cycle_id else None,
        "source_id": str(source_id) if source_id else None,
        "article_id": str(article_id) if article_id else None,
        "stage": stage[:80] if stage else None,
        "status": status[:80] if status else None,
    }
    context.update(sanitized_fields(fields))
    logger.log(
        level,
        event,
        extra={"news": {k: v for k, v in context.items() if v is not None}},
    )


def log_cycle(
    logger: logging.Logger,
    event: str,
    cycle_id: UUID | str | None,
    status: str,
    **fields: Any,
) -> None:
    log_news_event(
        logger,
        event,
        cycle_id=cycle_id,
        stage="cycle",
        status=status,
        fields=fields,
    )


def log_source(
    logger: logging.Logger,
    event: str,
    cycle_id: UUID | str,
    source_id: UUID | str,
    stage: str,
    status: str,
    **fields: Any,
) -> None:
    log_news_event(
        logger,
        event,
        cycle_id=cycle_id,
        source_id=source_id,
        stage=stage,
        status=status,
        fields=fields,
    )
