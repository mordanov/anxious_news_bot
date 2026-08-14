from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from anxious_news_bot.digest.errors import (
    CompositionPermanentError,
    CompositionTransientError,
)
from anxious_news_bot.digest.infrastructure.llm import StructuredDigestComposer


def _inputs(count: int = 2):
    return tuple(
        {"index": index, "title": f"Title {index}", "grounding": f"Facts {index}"}
        for index in range(1, count + 1)
    )


@pytest.mark.parametrize("language", ["ru", "en", "es"])
async def test_composes_all_items_in_one_indexed_language_request(language):
    transport = AsyncMock()
    transport.request.return_value = {
        "schema_version": "1.0",
        "items": [
            {"index": 2, "title": "Localized 2", "summary": "Summary 2"},
            {"index": 1, "title": "Localized 1", "summary": "Summary 1"},
        ],
    }

    result = await StructuredDigestComposer(transport).compose(
        uuid4(), language, _inputs()
    )

    assert [item["index"] for item in result] == [1, 2]
    transport.request.assert_awaited_once()
    prompt = transport.request.await_args.args[1]
    assert prompt["language"] == language
    assert prompt["item_count"] == 2
    assert prompt["items"] == list(_inputs())


async def test_zero_items_skips_model_transport():
    transport = AsyncMock()

    result = await StructuredDigestComposer(transport).compose(uuid4(), "en", ())

    assert result == ()
    transport.request.assert_not_awaited()


@pytest.mark.parametrize(
    "items",
    [
        [{"index": 1, "title": "One", "summary": "One"}],
        [
            {"index": 1, "title": "One", "summary": "One"},
            {"index": 1, "title": "Duplicate", "summary": "Duplicate"},
        ],
        [
            {"index": 1, "title": "One", "summary": "One"},
            {"index": 3, "title": "Three", "summary": "Three"},
        ],
    ],
)
async def test_rejects_partial_duplicate_or_missing_model_indexes(items):
    transport = AsyncMock()
    transport.request.return_value = {"schema_version": "1.0", "items": items}

    with pytest.raises(CompositionPermanentError, match="validation failed"):
        await StructuredDigestComposer(transport).compose(uuid4(), "en", _inputs())


async def test_classifies_rate_limit_as_transient():
    request = httpx.Request("POST", "https://model.example")
    response = httpx.Response(429, request=request)
    transport = AsyncMock()
    transport.request.side_effect = httpx.HTTPStatusError(
        "rate limited",
        request=request,
        response=response,
    )

    with pytest.raises(CompositionTransientError) as caught:
        await StructuredDigestComposer(transport).compose(uuid4(), "en", _inputs())
    assert caught.value.code == "model_transient"


async def test_classifies_provider_rejection_as_permanent():
    request = httpx.Request("POST", "https://model.example")
    response = httpx.Response(422, request=request)
    transport = AsyncMock()
    transport.request.side_effect = httpx.HTTPStatusError(
        "invalid",
        request=request,
        response=response,
    )

    with pytest.raises(CompositionPermanentError) as caught:
        await StructuredDigestComposer(transport).compose(uuid4(), "en", _inputs())
    assert caught.value.code == "model_rejected"
