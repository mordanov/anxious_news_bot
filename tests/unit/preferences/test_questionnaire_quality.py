from __future__ import annotations

from copy import deepcopy

import pytest

from anxious_news_bot.preferences.errors import QuestionnaireInvalid
from anxious_news_bot.preferences.schemas import QuestionnaireGenerationSchema
from anxious_news_bot.preferences.services.questionnaire_quality import (
    DeterministicQuestionnaireQualityValidator,
)
from tests.fixtures.preferences import generated_questionnaire


def _candidate(value=None):
    return QuestionnaireGenerationSchema.model_validate(
        value or generated_questionnaire(), strict=True
    )


def test_accepts_concrete_neutral_questions() -> None:
    DeterministicQuestionnaireQualityValidator().validate(_candidate(), ())


@pytest.mark.parametrize(
    ("text", "labels"),
    [
        ("Don't you prefer local news?", None),
        ("What things matter in news?", None),
        ("What is your favorite color?", None),
        ("Do you prefer local and detailed or global and short news?", None),
        ("Would you choose this?", ["Yes", "No", "Rather yes", "Rather no"]),
    ],
)
def test_rejects_low_quality_questions(text, labels) -> None:
    value = deepcopy(generated_questionnaire())
    value["questions"][0]["text"] = text
    if labels:
        for option, label in zip(value["questions"][0]["options"], labels, strict=True):
            option["label"] = label
    with pytest.raises(QuestionnaireInvalid):
        DeterministicQuestionnaireQualityValidator().validate(_candidate(value), ())


def test_rejects_substantial_prior_repetition() -> None:
    candidate = _candidate()
    with pytest.raises(QuestionnaireInvalid):
        DeterministicQuestionnaireQualityValidator().validate(
            candidate, (candidate.questions[0].text,)
        )
