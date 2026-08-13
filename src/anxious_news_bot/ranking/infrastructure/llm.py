from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from anxious_news_bot.infrastructure.structured_model import StructuredModelTransport
from anxious_news_bot.preferences.domain import ProfileSnapshot
from anxious_news_bot.ranking.domain import (
    ArticleEvaluationIdentity,
    RankingArticleSnapshot,
)
from anxious_news_bot.ranking.errors import EvaluationError

ARTICLE_EVALUATION_SCHEMA_VERSION = "1.0"
STRUCTURED_EVALUATOR_NAME = "structured-ranking-model"
STRUCTURED_EVALUATOR_VERSION = "1.0"
ARTICLE_EVALUATION_PROMPT_VERSION = "article-preference-evaluator-v1"


class StructuredArticlePreferenceEvaluator:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 30.0,
        retry_attempts: int = 3,
        max_response_bytes: int = 262_144,
        max_title_length: int = 300,
        max_summary_length: int = 600,
        max_article_length: int = 4_000,
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
        self._max_title_length = max_title_length
        self._max_summary_length = max_summary_length
        self._max_article_length = max_article_length

    @property
    def configured(self) -> bool:
        return self._transport.configured

    @property
    def evaluator_name(self) -> str:
        return STRUCTURED_EVALUATOR_NAME

    @property
    def evaluator_version(self) -> str:
        return STRUCTURED_EVALUATOR_VERSION

    @property
    def prompt_version(self) -> str:
        return ARTICLE_EVALUATION_PROMPT_VERSION

    async def evaluate(
        self,
        article_snapshot: RankingArticleSnapshot,
        profile_snapshot: ProfileSnapshot,
        evaluation_identity: ArticleEvaluationIdentity,
    ) -> Mapping[str, Any]:
        if not self.configured:
            raise EvaluationError(
                "ranking model is not configured",
                code="evaluator_not_configured",
            )
        prompt = {
            "schema_version": ARTICLE_EVALUATION_SCHEMA_VERSION,
            "evaluation_identity": {
                "article_id": str(evaluation_identity.article_id),
                "article_analysis_id": str(evaluation_identity.article_analysis_id),
                "profile_revision": evaluation_identity.profile_revision,
                "parameter_set_hash": evaluation_identity.parameter_set_hash,
            },
            "article": self._article(article_snapshot),
            "profile": self._profile(profile_snapshot),
            "instructions": (
                "Return one relevance object for every active parameter exactly once. "
                "Use the provided parameter_id values unchanged. Relevance must be a "
                "canonical decimal string with exactly four decimal places in the range "
                "-1.0000 to 1.0000, where 0.0000 is neutral, positive values indicate "
                "semantic alignment, and negative values indicate contradiction. Use "
                "short snake_case reason_code values only."
            ),
        }
        try:
            return await self._transport.request(
                "article_preference_evaluation",
                prompt,
                self._evaluation_schema(),
            )
        except EvaluationError:
            raise
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise EvaluationError(
                "model request failed",
                code="transport_failure",
            ) from exc
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code == 429:
                code = "rate_limited"
            elif status_code >= 500:
                code = "server_error"
            else:
                code = "request_rejected"
            raise EvaluationError("model request failed", code=code) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise EvaluationError(
                "model response is invalid",
                code="invalid_response",
            ) from exc
        except Exception as exc:
            raise EvaluationError(
                "model request failed", code="model_request_failed"
            ) from exc

    def _article(self, article_snapshot: RankingArticleSnapshot) -> Mapping[str, Any]:
        return {
            "article_id": str(article_snapshot.article_id),
            "article_analysis_id": str(article_snapshot.article_analysis_id),
            "language_code": article_snapshot.language_code,
            "published_at": article_snapshot.published_at.isoformat()
            if article_snapshot.published_at is not None
            else None,
            "title": self._trim(article_snapshot.title, self._max_title_length),
            "summary": self._trim(article_snapshot.summary, self._max_summary_length),
            "normalized_text": self._trim(
                article_snapshot.normalized_text,
                self._max_article_length,
            ),
            "topic_key": article_snapshot.topic_key,
        }

    @staticmethod
    def _profile(profile_snapshot: ProfileSnapshot) -> Mapping[str, Any]:
        active_parameters = tuple(
            parameter for parameter in profile_snapshot.parameters if parameter.active
        )
        return {
            "revision": profile_snapshot.revision,
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
                for parameter in active_parameters
            ],
        }

    @staticmethod
    def _trim(value: str | None, maximum: int) -> str | None:
        if value is None:
            return None
        return value[:maximum]

    @staticmethod
    def _evaluation_schema() -> Mapping[str, Any]:
        from anxious_news_bot.ranking.schemas import ArticlePreferenceEvaluationSchema

        return ArticlePreferenceEvaluationSchema.model_json_schema()


__all__ = [
    "ARTICLE_EVALUATION_PROMPT_VERSION",
    "ARTICLE_EVALUATION_SCHEMA_VERSION",
    "STRUCTURED_EVALUATOR_NAME",
    "STRUCTURED_EVALUATOR_VERSION",
    "StructuredArticlePreferenceEvaluator",
]
