from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from anxious_news_bot.news.errors import DiagnosticContext

LOGGER = logging.getLogger(__name__)
_SAFE_REASONS = frozenset(
    {
        "question is leading",
        "question is vague",
        "question is irrelevant to news preferences",
        "question is double-barreled",
        "question is a disguised yes/no choice",
        "question substantially repeats prior context",
        "equivalent preference parameter already exists",
        "request would not change preferences",
    }
)


def preference_exception_context(exc: BaseException) -> dict[str, Any]:
    context: dict[str, Any] = {
        "exception_type": type(exc).__name__,
    }
    code = getattr(exc, "code", None)
    if isinstance(code, str):
        context["exception_code"] = code
    reason = str(exc)
    if reason in _SAFE_REASONS:
        context["reason"] = reason.replace(" ", "_")
    if isinstance(exc, ValidationError):
        errors = exc.errors(
            include_url=False, include_context=False, include_input=False
        )
        context["validation_error_count"] = len(errors)
        context["validation_fields"] = [
            ".".join(str(part) for part in error["loc"])[:120] for error in errors[:10]
        ]
        context["validation_types"] = [str(error["type"])[:80] for error in errors[:10]]
    return context


def log_preference_event(
    stage: str,
    status: str,
    *,
    questionnaire_id: UUID | None = None,
    request_id: UUID | None = None,
    error_code: str | None = None,
    **safe_context: Any,
) -> None:
    preference = {
        "stage": stage,
        "status": status,
        "questionnaire_id": str(questionnaire_id) if questionnaire_id else None,
        "request_id": str(request_id) if request_id else None,
        "error_code": error_code,
        **safe_context,
    }
    LOGGER.info(
        "preference_event",
        extra={
            "preference": DiagnosticContext.sanitized(preference).as_dict(),
        },
    )
