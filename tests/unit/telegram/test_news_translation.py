from __future__ import annotations

import json

import httpx
import pytest

from anxious_news_bot.preferences.domain import SupportedLanguage
from anxious_news_bot.telegram.news_translation import (
    NewsTranslationError,
    StructuredNewsTitleTranslator,
)


async def test_translates_all_titles_in_requested_order() -> None:
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "translations": [
                                        {"index": 2, "title": "Второй заголовок"},
                                        {"index": 1, "title": "Первый заголовок"},
                                    ]
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    translator = StructuredNewsTitleTranslator(
        client,
        base_url="https://model.test/v1",
        api_key="secret",
        model="test-model",
    )

    result = await translator.translate(
        ("First headline", "Second headline"),
        SupportedLanguage.RUSSIAN,
    )

    assert result == ("Первый заголовок", "Второй заголовок")
    prompt = json.loads(captured["messages"][0]["content"])
    assert prompt["target_language"] == "Russian"
    assert [item["index"] for item in prompt["headlines"]] == [1, 2]
    await client.aclose()


async def test_rejects_incomplete_translation_response() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"translations": [{"index": 1, "title": "Solo uno"}]}
                            )
                        }
                    }
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    translator = StructuredNewsTitleTranslator(
        client,
        base_url="https://model.test/v1",
        api_key="secret",
        model="test-model",
    )

    with pytest.raises(NewsTranslationError):
        await translator.translate(
            ("First headline", "Second headline"),
            SupportedLanguage.SPANISH,
        )
    await client.aclose()
