import logging
from uuid import uuid4

from anxious_news_bot.preferences.observability import log_preference_event


def test_structured_event_contains_only_safe_context(caplog) -> None:
    logger = logging.getLogger("anxious_news_bot.preferences.observability")
    logger.disabled = False
    caplog.set_level(logging.INFO, logger=logger.name)
    questionnaire_id = uuid4()
    log_preference_event(
        "generation",
        "failed",
        questionnaire_id=questionnaire_id,
        error_code="invalid_output",
        exception_type="ValidationError",
    )
    text = caplog.text
    assert "generation" not in text
    record = caplog.records[-1]
    assert record.stage == "generation"
    assert record.questionnaire_id == str(questionnaire_id)
    assert not hasattr(record, "question_text")
