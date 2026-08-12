from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "content",
        "cookie",
        "credential",
        "credential_ref",
        "header",
        "key",
        "password",
        "payload",
        "raw_payload",
        "secret",
        "token",
        "x_api_key",
    }
)
_MAX_ITEMS = 20
_MAX_TEXT = 240


def is_sensitive_key(key: object) -> bool:
    normalized = "".join(
        character for character in str(key).lower() if character.isalnum()
    )
    return any(
        marker in normalized
        for marker in (
            "apikey",
            "authorization",
            "cookie",
            "credential",
            "header",
            "key",
            "password",
            "payload",
            "secret",
            "token",
        )
    ) or any(
        "".join(character for character in marker if character.isalnum())
        in normalized
        for marker in _SENSITIVE_KEYS
    )


def _safe_value(value: Any, depth: int = 0) -> Any:
    if depth >= 3:
        return "<truncated>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:_MAX_TEXT]
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for key, item in list(value.items())[:_MAX_ITEMS]:
            normalized_key = str(key)[:80]
            if is_sensitive_key(normalized_key):
                sanitized[normalized_key] = "<redacted>"
            else:
                sanitized[normalized_key] = _safe_value(item, depth + 1)
        return sanitized
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_safe_value(item, depth + 1) for item in list(value)[:_MAX_ITEMS]]
    return str(value)[:_MAX_TEXT]


@dataclass(frozen=True, slots=True)
class DiagnosticContext:
    values: Mapping[str, Any]

    @classmethod
    def sanitized(cls, values: Mapping[str, Any] | None) -> "DiagnosticContext":
        return cls(_safe_value(values or {}))

    def as_dict(self) -> dict[str, Any]:
        return dict(self.values)


class NewsError(Exception):
    default_code = "news_error"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code or self.default_code
        self.context = DiagnosticContext.sanitized(context)


class SourceUnavailable(NewsError):
    default_code = "source_unavailable"


class SourceRejected(NewsError):
    default_code = "source_rejected"


class RecordRejected(NewsError):
    default_code = "record_rejected"


class DuplicateResolved(NewsError):
    default_code = "duplicate_resolved"


class EnrichmentInvalid(NewsError):
    default_code = "enrichment_invalid"


class EnrichmentFailed(NewsError):
    default_code = "enrichment_failed"


class PersistenceConflict(NewsError):
    default_code = "persistence_conflict"
