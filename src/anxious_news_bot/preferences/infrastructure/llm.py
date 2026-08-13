from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from anxious_news_bot.preferences.domain import ProfileSnapshot, QuestionnaireContext
from anxious_news_bot.preferences.errors import (
    InterpretationFailed,
    QuestionnaireGenerationFailed,
)
from anxious_news_bot.preferences.schemas import CreateChangeSchema


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
    ) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._retry_attempts = retry_attempts
        self._max_response_bytes = max_response_bytes

    async def generate(self, context: QuestionnaireContext) -> Mapping[str, Any]:
        if not self._configured:
            raise QuestionnaireGenerationFailed("preference model is not configured")
        active = tuple(
            parameter for parameter in context.profile.parameters if parameter.active
        )
        prompt = {
            "language_code": context.language_code,
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
                    {item.dimension_key for item in context.prior_answers}
                ),
            },
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
                "Prefer unexplored dimensions, strong interests, and ambiguity "
                "clarification. Avoid substantial repetition and disguised yes/no."
            ),
        }
        try:
            return await self._request(
                "questionnaire_generation",
                prompt,
                self._questionnaire_schema(),
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
                "Propose incremental preference changes. Create values have "
                "questionnaire origin assigned by the application. Target only "
                "questionnaire-origin parameters; explicit, inference, and system "
                "parameters are read-only. Use canonical two-decimal weights."
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
        return bool(self._base_url and self._api_key and self._model)

    async def _request(
        self,
        name: str,
        prompt: Mapping[str, Any],
        schema: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        retrying = AsyncRetrying(
            stop=stop_after_attempt(self._retry_attempts),
            wait=wait_exponential(min=0.2, max=2),
            retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException)),
            reraise=True,
        )
        async for attempt in retrying:
            with attempt:
                response = await self._client.post(
                    f"{self._base_url}/chat/completions",
                    timeout=self._timeout_seconds,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={
                        "model": self._model,
                        "messages": [
                            {
                                "role": "user",
                                "content": json.dumps(
                                    prompt,
                                    ensure_ascii=False,
                                    separators=(",", ":"),
                                ),
                            }
                        ],
                        "response_format": {
                            "type": "json_schema",
                            "json_schema": {
                                "name": name,
                                "strict": True,
                                "schema": schema,
                            },
                        },
                    },
                )
                response.raise_for_status()
                if len(response.content) > self._max_response_bytes:
                    raise ValueError("model response exceeds configured size")
                body = response.json()
                content = body["choices"][0]["message"]["content"]
                value = json.loads(content) if isinstance(content, str) else content
                if not isinstance(value, dict):
                    raise ValueError("model response must be an object")
                return value
        raise RuntimeError("unreachable")

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
    def _questionnaire_schema() -> Mapping[str, Any]:
        from anxious_news_bot.preferences.schemas import QuestionnaireGenerationSchema

        return QuestionnaireGenerationSchema.model_json_schema()

    @staticmethod
    def _changes_schema() -> Mapping[str, Any]:
        from anxious_news_bot.preferences.schemas import PreferenceChangesSchema

        return PreferenceChangesSchema.model_json_schema()
