from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from difflib import SequenceMatcher

from anxious_news_bot.preferences.errors import QuestionnaireInvalid
from anxious_news_bot.preferences.schemas import (
    YES_NO_WORDS,
    QuestionnaireGenerationSchema,
)


def normalize_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


class DeterministicQuestionnaireQualityValidator:
    def __init__(self, *, repetition_threshold: float = 0.85) -> None:
        if not 0 <= repetition_threshold <= 1:
            raise ValueError("repetition_threshold must be between 0 and 1")
        self._repetition_threshold = repetition_threshold

    def validate(
        self,
        candidate: QuestionnaireGenerationSchema,
        prior_questions: Sequence[str],
    ) -> None:
        prior = tuple(normalize_text(value) for value in prior_questions)
        for question in candidate.questions:
            normalized = normalize_text(question.text)
            if self._is_leading(normalized):
                raise QuestionnaireInvalid("question is leading")
            if self._is_vague(normalized):
                raise QuestionnaireInvalid("question is vague")
            if self._is_irrelevant(normalized):
                raise QuestionnaireInvalid("question is irrelevant to news preferences")
            if self._is_double_barreled(normalized):
                raise QuestionnaireInvalid("question is double-barreled")
            if all(
                YES_NO_WORDS.fullmatch(option.label.strip())
                for option in question.options
            ):
                raise QuestionnaireInvalid("question is a disguised yes/no choice")
            if any(
                SequenceMatcher(None, normalized, previous).ratio()
                >= self._repetition_threshold
                for previous in prior
            ):
                raise QuestionnaireInvalid(
                    "question substantially repeats prior context"
                )

    @staticmethod
    def _is_leading(value: str) -> bool:
        return value.startswith(
            ("don't you ", "wouldn't you ", "isn't it ", "разве ", "не правда ли")
        )

    @staticmethod
    def _is_vague(value: str) -> bool:
        vague = {"things", "stuff", "something", "anything", "всякое", "что-нибудь"}
        return any(token in vague for token in re.findall(r"\w+", value))

    @staticmethod
    def _is_irrelevant(value: str) -> bool:
        return any(
            phrase in value
            for phrase in (
                "favorite color",
                "shoe size",
                "breakfast food",
                "favourite colour",
                "любимый цвет",
                "размер обуви",
            )
        )

    @staticmethod
    def _is_double_barreled(value: str) -> bool:
        return value.count("?") > 1 or bool(
            re.search(r"\b(and|or|и|или)\b.+\b(and|or|и|или)\b", value)
        )
