from __future__ import annotations

from dataclasses import dataclass

from anxious_news_bot.preferences.domain import (
    PreferenceParameter,
    PriorAnswer,
    QuestionnaireContext,
)


@dataclass(frozen=True, slots=True)
class AdaptiveContext:
    strong_preferences: tuple[PreferenceParameter, ...]
    ambiguous_preferences: tuple[PreferenceParameter, ...]
    explored_dimensions: frozenset[str]
    prior_answers: tuple[PriorAnswer, ...]


class AdaptiveContextSelector:
    def __init__(
        self,
        *,
        history_limit: int,
        strong_weight: float = 0.70,
        ambiguous_weight: float = 0.20,
    ) -> None:
        self._history_limit = history_limit
        self._strong_weight = strong_weight
        self._ambiguous_weight = ambiguous_weight

    def select(self, context: QuestionnaireContext) -> AdaptiveContext:
        active = tuple(
            parameter for parameter in context.profile.parameters if parameter.active
        )
        strong = tuple(
            sorted(
                (
                    parameter
                    for parameter in active
                    if abs(parameter.weight) >= self._strong_weight
                ),
                key=lambda parameter: (-abs(parameter.weight), parameter.semantic_key),
            )
        )
        ambiguous = tuple(
            sorted(
                (
                    parameter
                    for parameter in active
                    if abs(parameter.weight) <= self._ambiguous_weight
                ),
                key=lambda parameter: (abs(parameter.weight), parameter.semantic_key),
            )
        )
        prior = context.prior_answers[-self._history_limit :]
        return AdaptiveContext(
            strong_preferences=strong,
            ambiguous_preferences=ambiguous,
            explored_dimensions=frozenset(item.dimension_key for item in prior),
            prior_answers=prior,
        )
