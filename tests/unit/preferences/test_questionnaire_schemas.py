from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from anxious_news_bot.preferences.schemas import QuestionnaireGenerationSchema
from tests.fixtures.preferences import generated_questionnaire


def test_accepts_exactly_ten_ordered_questions_and_four_options() -> None:
    value = QuestionnaireGenerationSchema.model_validate(
        generated_questionnaire(), strict=True
    )
    assert len(value.questions) == 10
    assert all(len(question.options) == 4 for question in value.questions)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["questions"].pop(),
        lambda value: value["questions"][0]["options"].pop(),
        lambda value: value["questions"][0].update(extra=True),
        lambda value: value["questions"][0].update(ordinal="1"),
        lambda value: value["questions"][0]["options"][1].update(label="Preference 1"),
        lambda value: value["questions"][1].update(dimension_key="dimension_1"),
    ],
)
def test_rejects_malformed_questionnaires(mutate) -> None:
    value = deepcopy(generated_questionnaire())
    mutate(value)
    with pytest.raises(ValidationError):
        QuestionnaireGenerationSchema.model_validate(value, strict=True)
