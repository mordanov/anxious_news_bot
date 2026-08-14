"""Redacted structured digest event builders."""

from __future__ import annotations

import hashlib
import logging
from typing import Any
from uuid import UUID

from anxious_news_bot.news.errors import DiagnosticContext

LOGGER = logging.getLogger(__name__)

_MAX_FIELD_LENGTH = 200
_FORBIDDEN = frozenset(
    {
        "prompt",
        "rawprompt",
        "rawresponse",
        "content",
        "text",
        "title",
        "summary",
        "article",
        "normalizedtext",
        "responsebody",
        "providerresponse",
        "articlecontent",
        "articletext",
        "rawtext",
        "renderedmessage",
    }
)
_MAX_ITEMS = 20
_MAX_DEPTH = 3


def _safe_hash(value: str | UUID | None) -> str | None:
    if value is None:
        return None
    raw = str(value)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _sanitize_value(value: Any, depth: int) -> Any:
    if depth >= _MAX_DEPTH:
        return "<truncated>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:_MAX_FIELD_LENGTH]
    if isinstance(value, dict):
        return _sanitize(value, depth=depth + 1)
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_sanitize_value(item, depth + 1) for item in list(value)[:_MAX_ITEMS]]
    return str(value)[:_MAX_FIELD_LENGTH]


def _sanitize(fields: dict[str, Any], *, depth: int = 0) -> dict[str, Any]:
    result = {}
    for key, value in list(fields.items())[:_MAX_ITEMS]:
        norm = "".join(c for c in key.lower() if c.isalnum())
        if norm in _FORBIDDEN or norm.endswith("prompt") or norm.endswith("snapshot"):
            continue
        result[key[:80]] = _sanitize_value(value, depth)
    return result


def log_digest_event(
    event: str,
    *,
    execution_id: UUID | None = None,
    user_id: UUID | None = None,
    occurrence_key: str | None = None,
    phase: str | None = None,
    status: str | None = None,
    reason_code: str | None = None,
    fields: dict[str, Any] | None = None,
    level: int = logging.INFO,
) -> None:
    payload: dict[str, Any] = {
        "event": event[:100],
    }
    if execution_id is not None:
        payload["execution_id"] = str(execution_id)
    if user_id is not None:
        payload["user_id_hash"] = _safe_hash(user_id)
    if occurrence_key is not None:
        payload["occurrence_key_hash"] = _safe_hash(occurrence_key)
    if phase is not None:
        payload["phase"] = phase[:80]
    if status is not None:
        payload["status"] = status[:80]
    if reason_code is not None:
        from anxious_news_bot.digest.domain import validate_reason_code

        try:
            payload["reason_code"] = validate_reason_code(reason_code)
        except ValueError:
            payload["reason_code"] = "invalid_reason_code"
    if fields:
        payload.update(_sanitize(fields))
    LOGGER.log(
        level,
        event,
        extra={"digest": DiagnosticContext.sanitized(payload).as_dict()},
    )
