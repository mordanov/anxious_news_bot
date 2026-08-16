from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx

from anxious_news_bot.infrastructure.structured_model import StructuredModelTransport
from anxious_news_bot.preferences.domain import (
    ProfileSnapshot,
    QuestionnaireContext,
    normalize_language_code,
)
from anxious_news_bot.preferences.errors import (
    InterpretationFailed,
    QuestionnaireGenerationFailed,
)
from anxious_news_bot.preferences.schemas import CreateChangeSchema
from anxious_news_bot.preferences.services.dimensions import (
    available_dimensions,
    consolidated_dimension_context,
)

EXPLICIT_INTERPRETATION_VERSION = "explicit-preference-v1"


class StructuredPreferenceModelAdapter:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 30.0,
        retry_attempts: int = 2,
        max_response_bytes: int = 262_144,
        explicit_history_limit: int = 20,
    ) -> None:
        self._transport = StructuredModelTransport(
            client,
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout_seconds=timeout_seconds,
            retry_attempts=retry_attempts,
            max_response_bytes=max_response_bytes,
        )
        self._explicit_history_limit = explicit_history_limit

    async def generate(self, context: QuestionnaireContext) -> Mapping[str, Any]:
        if not self._configured:
            raise QuestionnaireGenerationFailed("preference model is not configured")
        active = tuple(
            parameter for parameter in context.profile.parameters if parameter.active
        )
        language = normalize_language_code(context.language_code)
        language_names = {"ru": "Русский", "en": "English", "es": "Español"}
        dimensions = available_dimensions(
            context.prior_answers,
            context.dimension_context,
        )
        dimension_context = consolidated_dimension_context(context.dimension_context)
        prompt = {
            "language_code": language.value,
            "output_language": language_names[language.value],
            "profile": self._profile(context.profile),
            "adaptive_context": {
                "strong_preference_keys": [
                    parameter.semantic_key
                    for parameter in active
                    if abs(parameter.weight) >= Decimal("0.70")
                ],
                "ambiguous_preference_keys": [
                    parameter.semantic_key
                    for parameter in active
                    if abs(parameter.weight) <= Decimal("0.20")
                ],
                "explored_dimensions": sorted(
                    {item.dimension_key for item in dimension_context}
                    | {item.dimension_key for item in context.prior_answers}
                ),
                "dimension_exposure_counts": {
                    item.dimension_key: item.exposure_count
                    for item in dimension_context
                },
            },
            "available_dimensions": [
                {"key": dimension.key, "guidance": dimension.guidance}
                for dimension in dimensions
            ],
            "prior_answers": [
                {
                    "question": item.question,
                    "selected_option": item.selected_option,
                    "dimension_key": item.dimension_key,
                }
                for item in context.prior_answers
            ],
            "instructions": (
                "Generate exactly 10 short, concrete, neutral, single-dimensional "
                "news-preference questions with exactly four distinct options. "
                f"Write every question and option only in {language_names[language.value]}. "
                "Use exactly 10 distinct keys from available_dimensions; copy each "
                "key exactly into dimension_key. Do not revisit an explored semantic "
                "dimension under a new name. "
                "Prefer unexplored dimensions, strong interests, and ambiguity "
                "clarification. Avoid substantial repetition and disguised yes/no."
            ),
        }
        try:
            return await self._request(
                "questionnaire_generation",
                prompt,
                self._questionnaire_schema(
                    tuple(dimension.key for dimension in dimensions)
                ),
            )
        except Exception as exc:
            if isinstance(exc, QuestionnaireGenerationFailed):
                raise
            raise QuestionnaireGenerationFailed("model request failed") from exc

    async def propose(
        self,
        profile: ProfileSnapshot,
        questionnaire_id: UUID,
        answers: Sequence[tuple[str, str]],
    ) -> Mapping[str, Any]:
        if not self._configured:
            raise InterpretationFailed("preference model is not configured")
        prompt = {
            "questionnaire_id": str(questionnaire_id),
            "base_profile_revision": profile.revision,
            "profile": self._profile(profile),
            "answers": [
                {"question": question, "selected_option": option}
                for question, option in answers
            ],
            "instructions": (
                "Propose incremental preference changes based on the answers. "
                "Target only questionnaire-origin parameters; explicit, inference, "
                "and system parameters are read-only — do not include them in changes. "
                "For adjust changes the new target_weight must differ from the "
                "current weight; for refine changes at least one field must differ "
                "from the current value. "
                "Weights must be exactly four characters: '0.25', '0.50', '0.75', "
                "'1.00', etc. — never '0.5' or '0.500'."
            ),
        }
        try:
            return await self._request(
                "preference_changes",
                prompt,
                self._changes_schema(),
            )
        except Exception as exc:
            if isinstance(exc, InterpretationFailed):
                raise
            raise InterpretationFailed("model request failed") from exc

    async def interpret(
        self,
        request_id: UUID,
        statement: str,
        profile_snapshot: ProfileSnapshot,
        relevant_history: Sequence[Mapping[str, Any]],
        language_code: str | None = None,
    ) -> Mapping[str, Any]:
        if not self._configured:
            raise InterpretationFailed("preference model is not configured")
        language = normalize_language_code(language_code)
        language_names = {"ru": "Русский", "en": "English", "es": "Español"}
        output_language = language_names[language.value]
        prompt = {
            "request_id": str(request_id),
            "schema_version": "1.0",
            "interpretation_version": EXPLICIT_INTERPRETATION_VERSION,
            "statement": statement,
            "output_language": output_language,
            "profile": self._profile(profile_snapshot),
            "relevant_history": [
                dict(item) for item in relevant_history[: self._explicit_history_limit]
            ],
            "instructions": (
                f"Interpret one explicit news-preference statement as an incremental "
                f"change set. Write name, description, and evaluation_instructions "
                f"only in {output_language}, matching the statement's language. "
                "Keep specific intent specific. Preserve every named "
                "place, person, organization, and topic verbatim in the descriptive "
                "fields. Encode named entities in semantic_key using a stable ASCII "
                "transliteration; for example, Russian 'Киров' becomes "
                "'kirov_city_news'. Reuse equivalent active "
                "or inactive parameters instead of proposing duplicates. A narrower "
                "distinct concept may create a new explicit preference. Do not "
                "broaden, weaken, deactivate, or relabel unrelated explicit "
                "preferences. Use canonical two-decimal weights and concise reasons."
            ),
        }
        try:
            return await self._request(
                "explicit_preference_changes",
                prompt,
                self._explicit_changes_schema(),
            )
        except Exception as exc:
            if isinstance(exc, InterpretationFailed):
                raise
            raise InterpretationFailed("model request failed") from exc

    async def classify(
        self,
        proposal: CreateChangeSchema,
        candidates: ProfileSnapshot,
    ) -> Mapping[str, Any]:
        if not self._configured:
            raise InterpretationFailed("preference model is not configured")
        return await self._request(
            "preference_equivalence",
            {
                "proposal": proposal.model_dump(mode="json"),
                "candidates": self._profile(candidates),
            },
            {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "schema_version",
                    "outcome",
                    "candidate_parameter_id",
                    "confidence",
                    "reason",
                ],
                "properties": {
                    "schema_version": {"const": "1.0"},
                    "outcome": {"enum": ["equivalent", "distinct"]},
                    "candidate_parameter_id": {
                        "type": ["string", "null"],
                        "format": "uuid",
                    },
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "reason": {"type": "string", "minLength": 1, "maxLength": 500},
                },
            },
        )

    @property
    def _configured(self) -> bool:
        return self._transport.configured

    async def _request(
        self,
        name: str,
        prompt: Mapping[str, Any],
        schema: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        return await self._transport.request(name, prompt, schema)

    @staticmethod
    def _profile(profile: ProfileSnapshot) -> Mapping[str, Any]:
        return {
            "revision": profile.revision,
            "parameters": [
                {
                    "id": str(parameter.id),
                    "semantic_key": parameter.semantic_key,
                    "name": parameter.name,
                    "description": parameter.description,
                    "evaluation_instructions": parameter.evaluation_instructions,
                    "weight": f"{parameter.weight:.2f}",
                    "origin": parameter.origin.value,
                    "active": parameter.active,
                }
                for parameter in profile.parameters
            ],
        }

    @staticmethod
    def _questionnaire_schema(
        allowed_dimension_keys: tuple[str, ...] | None = None,
    ) -> Mapping[str, Any]:
        from anxious_news_bot.preferences.schemas import QuestionnaireGenerationSchema

        schema = deepcopy(QuestionnaireGenerationSchema.model_json_schema())
        if allowed_dimension_keys is not None:
            schema["$defs"]["GeneratedQuestionSchema"]["properties"]["dimension_key"][
                "enum"
            ] = list(allowed_dimension_keys)
        return schema

    @staticmethod
    def _changes_schema() -> Mapping[str, Any]:
        from anxious_news_bot.preferences.schemas import PreferenceChangesSchema

        return PreferenceChangesSchema.model_json_schema()

    @staticmethod
    def _explicit_changes_schema() -> Mapping[str, Any]:
        from anxious_news_bot.preferences.schemas import ExplicitPreferenceChangesSchema

        return ExplicitPreferenceChangesSchema.model_json_schema()
