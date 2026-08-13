from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from anxious_news_bot.news.errors import DiagnosticContext

LOGGER = logging.getLogger(__name__)


def log_preference_event(
    stage: str,
    status: str,
    *,
    questionnaire_id: UUID | None = None,
    request_id: UUID | None = None,
    error_code: str | None = None,
    **safe_context: Any,
) -> None:
    LOGGER.info(
        "preference_event",
        extra={
            "stage": stage,
            "status": status,
            "questionnaire_id": str(questionnaire_id) if questionnaire_id else None,
            "request_id": str(request_id) if request_id else None,
            "error_code": error_code,
            **DiagnosticContext.sanitized(safe_context).as_dict(),
        },
    )
