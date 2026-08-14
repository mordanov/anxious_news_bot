"""Structured digest title/summary composer using shared model transport."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

import httpx

from anxious_news_bot.digest.errors import (
    CompositionPermanentError,
    CompositionTransientError,
)
from anxious_news_bot.digest.schemas import (
    validate_composer_response,
)
from anxious_news_bot.infrastructure.structured_model import StructuredModelTransport

# JSON Schema for the response
DIGEST_CONTENT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "DigestContentResponse",
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "items"],
    "properties": {
        "schema_version": {"type": "string", "const": "1.0"},
        "items": {
            "type": "array",
            "minItems": 1,
            "maxItems": 20,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["index", "title", "summary"],
                "properties": {
                    "index": {"type": "integer", "minimum": 1, "maximum": 20},
                    "title": {"type": "string", "minLength": 1, "maxLength": 500},
                    "summary": {"type": "string", "minLength": 1, "maxLength": 1200},
                },
            },
        },
    },
}


class StructuredDigestComposer:
    def __init__(self, transport: StructuredModelTransport) -> None:
        self._transport = transport

    async def compose(
        self,
        execution_id: UUID,
        language: str,
        ranked_items: Sequence[dict],
    ) -> tuple[dict, ...]:
        """Compose localized title/summary for all items in one request."""
        if not ranked_items:
            return ()
        if not self._transport.configured:
            raise CompositionPermanentError(
                "digest model transport is not configured",
                code="model_not_configured",
            )

        count = len(ranked_items)
        prompt = {
            "task": "digest_composition",
            "language": language,
            "item_count": count,
            "items": [
                {
                    "index": item["index"],
                    "title": item["title"],
                    "grounding": item["grounding"],
                }
                for item in ranked_items
            ],
            "instructions": (
                f"Translate/localize each item's title and write a concise summary "
                f"in {language}. Return exactly {count} items with indexes 1..{count}. "
                f"Preserve factual accuracy from the grounding text."
            ),
        }

        try:
            response = await self._transport.request(
                "DigestContentResponse",
                prompt,
                DIGEST_CONTENT_SCHEMA,
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (400, 422):
                raise CompositionPermanentError(
                    "model rejected request", code="model_rejected"
                ) from exc
            raise CompositionTransientError(
                "model request failed", code="model_transient"
            ) from exc
        except (httpx.TransportError, TimeoutError) as exc:
            raise CompositionTransientError(
                "model connection failed", code="transport_error"
            ) from exc
        except Exception as exc:
            raise CompositionTransientError(
                f"unexpected composition error: {exc}", code="unexpected"
            ) from exc

        try:
            validated = validate_composer_response(response, count)
        except Exception as exc:
            raise CompositionPermanentError(
                f"validation failed: {exc}", code="validation_failed"
            ) from exc

        return validated
