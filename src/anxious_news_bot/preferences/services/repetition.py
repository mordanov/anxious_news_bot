from __future__ import annotations

from difflib import SequenceMatcher

from anxious_news_bot.preferences.domain import PriorAnswer
from anxious_news_bot.preferences.errors import QuestionnaireInvalid
from anxious_news_bot.preferences.schemas import QuestionnaireGenerationSchema
from anxious_news_bot.preferences.services.questionnaire_quality import normalize_text

AMBIGUOUS_ANSWERS = frozenset(
    {
        "unsure",
        "it depends",
        "no preference",
        "not sure",
        "не уверен",
        "зависит",
        "без разницы",
    }
)


class SubstantialRepetitionDetector:
    def __init__(self, *, threshold: float = 0.85) -> None:
        self._threshold = threshold

    def is_repetition(
        self,
        question: str,
        dimension_key: str,
        prior: PriorAnswer,
    ) -> bool:
        if (
            prior.dimension_key == dimension_key
            and normalize_text(prior.selected_option) in AMBIGUOUS_ANSWERS
        ):
            return False
        return (
            SequenceMatcher(
                None,
                normalize_text(question),
                normalize_text(prior.question),
            ).ratio()
            >= self._threshold
        )

    def validate(
        self,
        candidate: QuestionnaireGenerationSchema,
        prior_answers: tuple[PriorAnswer, ...],
    ) -> None:
        for question in candidate.questions:
            if any(
                self.is_repetition(
                    question.text,
                    question.dimension_key,
                    prior,
                )
                for prior in prior_answers
            ):
                raise QuestionnaireInvalid(
                    "question substantially repeats prior context"
                )
