from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

LOGGER = logging.getLogger(__name__)


def log_preference_event(
    stage: str,
    status: str,
    *,
    questionnaire_id: UUID | None = None,
    error_code: str | None = None,
    **safe_context: Any,
) -> None:
    LOGGER.info(
        "preference_tuning_event",
        extra={
            "stage": stage,
            "status": status,
            "questionnaire_id": str(questionnaire_id) if questionnaire_id else None,
            "error_code": error_code,
            **safe_context,
        },
    )
