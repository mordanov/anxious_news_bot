from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Any, Protocol

import httpx
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from anxious_news_bot.infrastructure.structured_model import StructuredModelTransport
from anxious_news_bot.preferences.domain import SupportedLanguage

_LANGUAGE_NAMES = {
    SupportedLanguage.RUSSIAN: "Russian",
    SupportedLanguage.ENGLISH: "English",
    SupportedLanguage.SPANISH: "Spanish",
}


class NewsTranslationError(Exception):
    pass


class _StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


def _tuple(value: Any) -> Any:
    return tuple(value) if isinstance(value, list) else value


class _TranslatedTitle(_StrictSchema):
    index: Annotated[int, Field(strict=True, ge=1, le=10)]
    title: Annotated[
        str,
        StringConstraints(
            strict=True, strip_whitespace=True, min_length=1, max_length=500
        ),
    ]


class _TranslationResponse(_StrictSchema):
    translations: Annotated[
        tuple[_TranslatedTitle, ...],
        BeforeValidator(_tuple),
        Field(min_length=1, max_length=10),
    ]

    @model_validator(mode="after")
    def unique_indexes(self) -> _TranslationResponse:
        indexes = [item.index for item in self.translations]
        if len(indexes) != len(set(indexes)):
            raise ValueError("translation indexes must be unique")
        return self


class StructuredNewsTitleTranslator:
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

    async def translate(
        self,
        titles: Sequence[str],
        language: SupportedLanguage,
    ) -> tuple[str, ...]:
        if not titles:
            return ()
        if len(titles) > 10:
            raise ValueError("at most 10 titles can be translated")
        if not self._transport.configured:
            raise NewsTranslationError("news translation model is not configured")

        prompt = {
            "schema_version": "1.0",
            "target_language": _LANGUAGE_NAMES[language],
            "headlines": [
                {"index": index, "title": title[:500]}
                for index, title in enumerate(titles, start=1)
            ],
            "instructions": (
                "Translate every news headline into the target language. Preserve names, "
                "places, numbers, facts, and tone. Do not summarize, explain, censor, or "
                "add information. If a headline is already in the target language, return "
                "it unchanged. Return every index exactly once."
            ),
        }
        try:
            raw = await self._transport.request(
                "news_headline_translations",
                prompt,
                _TranslationResponse.model_json_schema(),
            )
            response = _TranslationResponse.model_validate(raw, strict=True)
            by_index = {item.index: item.title for item in response.translations}
            expected = set(range(1, len(titles) + 1))
            if set(by_index) != expected:
                raise ValueError("translation indexes do not match requested titles")
            return tuple(by_index[index] for index in range(1, len(titles) + 1))
        except NewsTranslationError:
            raise
        except Exception as exc:
            raise NewsTranslationError("news headline translation failed") from exc


class NewsTitleTranslator(Protocol):
    async def translate(
        self,
        titles: Sequence[str],
        language: SupportedLanguage,
    ) -> tuple[str, ...]:
        raise NotImplementedError


__all__ = [
    "NewsTitleTranslator",
    "NewsTranslationError",
    "StructuredNewsTitleTranslator",
]
