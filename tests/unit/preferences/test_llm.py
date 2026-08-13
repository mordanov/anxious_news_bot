from __future__ import annotations

import json
from uuid import uuid4

import httpx
import pytest

from anxious_news_bot.preferences.domain import ProfileSnapshot, QuestionnaireContext
from anxious_news_bot.preferences.errors import QuestionnaireGenerationFailed
from anxious_news_bot.preferences.infrastructure.llm import (
    StructuredPreferenceModelAdapter,
)
from tests.fixtures.preferences import generated_questionnaire


async def test_structured_adapter_returns_untrusted_mapping() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer secret"
        body = json.loads(request.content)
        assert body["response_format"]["type"] == "json_schema"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": json.dumps(generated_questionnaire())}}
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = StructuredPreferenceModelAdapter(
            client,
            base_url="https://model.example/v1",
            api_key="secret",
            model="test",
        )
        value = await adapter.generate(
            QuestionnaireContext(ProfileSnapshot(uuid4(), 0, ()), "en")
        )
    assert len(value["questions"]) == 10


@pytest.mark.parametrize("status_code", [429, 500, 503])
async def test_structured_adapter_retries_transient_http_statuses(
    status_code: int,
) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(status_code, request=request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": json.dumps(generated_questionnaire())}}
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = StructuredPreferenceModelAdapter(
            client,
            base_url="https://model.example/v1",
            api_key="secret",
            model="test",
            retry_attempts=2,
        )
        value = await adapter.generate(
            QuestionnaireContext(ProfileSnapshot(uuid4(), 0, ()), "en")
        )

    assert calls == 2
    assert len(value["questions"]) == 10


async def test_structured_adapter_retries_transport_errors() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.RemoteProtocolError("connection dropped", request=request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": json.dumps(generated_questionnaire())}}
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = StructuredPreferenceModelAdapter(
            client,
            base_url="https://model.example/v1",
            api_key="secret",
            model="test",
            retry_attempts=2,
        )
        value = await adapter.generate(
            QuestionnaireContext(ProfileSnapshot(uuid4(), 0, ()), "en")
        )

    assert calls == 2
    assert len(value["questions"]) == 10


async def test_structured_adapter_does_not_retry_non_transient_http_status() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = StructuredPreferenceModelAdapter(
            client,
            base_url="https://model.example/v1",
            api_key="secret",
            model="test",
            retry_attempts=3,
        )
        with pytest.raises(QuestionnaireGenerationFailed):
            await adapter.generate(
                QuestionnaireContext(ProfileSnapshot(uuid4(), 0, ()), "en")
            )

    assert calls == 1


async def test_structured_adapter_caps_transient_status_attempts() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = StructuredPreferenceModelAdapter(
            client,
            base_url="https://model.example/v1",
            api_key="secret",
            model="test",
            retry_attempts=2,
        )
        with pytest.raises(QuestionnaireGenerationFailed):
            await adapter.generate(
                QuestionnaireContext(ProfileSnapshot(uuid4(), 0, ()), "en")
            )

    assert calls == 2


async def test_unconfigured_adapter_fails_closed() -> None:
    async with httpx.AsyncClient() as client:
        adapter = StructuredPreferenceModelAdapter(
            client, base_url="", api_key="", model=""
        )
        with pytest.raises(QuestionnaireGenerationFailed):
            await adapter.generate(
                QuestionnaireContext(ProfileSnapshot(uuid4(), 0, ()), "en")
            )


async def test_response_size_is_bounded() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, content=b"x" * 101)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = StructuredPreferenceModelAdapter(
            client,
            base_url="https://model.example/v1",
            api_key="secret",
            model="test",
            max_response_bytes=100,
        )
        with pytest.raises(QuestionnaireGenerationFailed):
            await adapter.generate(
                QuestionnaireContext(ProfileSnapshot(uuid4(), 0, ()), "en")
            )
