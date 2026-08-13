import json
import logging

from pydantic import ValidationError

from anxious_news_bot.logging import JsonFormatter
from anxious_news_bot.preferences.observability import (
    log_preference_event,
    preference_exception_context,
)
from anxious_news_bot.preferences.schemas import QuestionnaireGenerationSchema


def test_preference_event_fields_are_emitted_as_json() -> None:
    records: list[logging.LogRecord] = []

    class CaptureHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    logger = log_preference_event.__globals__["LOGGER"]
    handler = CaptureHandler()
    previous_level = logger.level
    previous_disabled = logger.disabled
    previous_propagate = logger.propagate
    logger.addHandler(handler)
    logger.disabled = False
    logger.propagate = False
    logger.setLevel(logging.INFO)
    try:
        log_preference_event(
            "generation_validation",
            "rejected",
            error_code="generation_failed",
            attempt=2,
            reason="question_is_vague",
        )
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
        logger.disabled = previous_disabled
        logger.propagate = previous_propagate

    payload = json.loads(JsonFormatter().format(records[-1]))
    assert payload["preference"] == {
        "stage": "generation_validation",
        "status": "rejected",
        "questionnaire_id": None,
        "request_id": None,
        "error_code": "generation_failed",
        "attempt": 2,
        "reason": "question_is_vague",
    }


def test_validation_diagnostics_exclude_input_values() -> None:
    try:
        QuestionnaireGenerationSchema.model_validate(
            {"schema_version": "1.0", "questions": "private question text"},
            strict=True,
        )
    except ValidationError as exc:
        context = preference_exception_context(exc)
    else:
        raise AssertionError("expected validation failure")

    assert context["validation_error_count"] == 1
    assert context["validation_fields"] == ["questions"]
    assert "private question text" not in json.dumps(context)
