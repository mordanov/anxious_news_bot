from __future__ import annotations

import json
from uuid import uuid4

import httpx
import pytest

from anxious_news_bot.preferences.domain import ProfileSnapshot
from anxious_news_bot.preferences.errors import InterpretationFailed
from anxious_news_bot.preferences.infrastructure.llm import (
    StructuredPreferenceModelAdapter,
)
from tests.fixtures.ranking import preference_parameter


async def test_explicit_interpretation_request_includes_bounded_context_and_schema() -> (
    None
):
    request_id = uuid4()
    parameter = preference_parameter(user_id=uuid4())
    history = tuple(
        {
            "action": "adjust",
            "source": "explicit",
            "parameter_name": f"History {ordinal}",
            "changed_at": f"2026-01-{ordinal:02d}T00:00:00Z",
        }
        for ordinal in range(1, 26)
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"]
        body = json.loads(request.content)
        assert body["model"] == "test-model"
        prompt = json.loads(body["messages"][0]["content"])
        assert prompt["request_id"] == str(request_id)
        assert prompt["interpretation_version"] == "explicit-preference-v1"
        assert prompt["statement"] == "More Kirov city news"
        assert len(prompt["profile"]["parameters"]) == 1
        assert len(prompt["relevant_history"]) == 20
        schema = body["response_format"]["json_schema"]["schema"]
        assert "request_id" in schema["required"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "schema_version": "1.0",
                                    "request_id": str(request_id),
                                    "base_profile_revision": 3,
                                    "changes": [
                                        {
                                            "action": "create",
                                            "semantic_key": "kirov_city_news",
                                            "name": "Kirov city news",
                                            "description": "Specific city reporting about Kirov.",
                                            "evaluation_instructions": "Prefer relevant Kirov city reporting.",
                                            "target_weight": "0.80",
                                            "reason": "User explicitly asked for more Kirov city news.",
                                        }
                                    ],
                                }
                            )
                        }
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = StructuredPreferenceModelAdapter(
            client,
            base_url="https://model.example/v1",
            api_key="secret",
            model="test-model",
            explicit_history_limit=20,
        )
        value = await adapter.interpret(
            request_id,
            "More Kirov city news",
            ProfileSnapshot(parameter.user_id, 3, (parameter,)),
            history,
        )

    assert value["request_id"] == str(request_id)


async def test_explicit_interpretation_retries_transient_transport_failures() -> None:
    request_id = uuid4()
    calls = 0

    async def handler(request: httpx.Request):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("boom", request=request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "schema_version": "1.0",
                                    "request_id": str(request_id),
                                    "base_profile_revision": 0,
                                    "changes": [
                                        {
                                            "action": "create",
                                            "semantic_key": "kirov_city_news",
                                            "name": "Kirov city news",
                                            "description": "Specific city reporting about Kirov.",
                                            "evaluation_instructions": "Prefer relevant Kirov city reporting.",
                                            "target_weight": "0.80",
                                            "reason": "User explicitly asked for more Kirov city news.",
                                        }
                                    ],
                                }
                            )
                        }
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = StructuredPreferenceModelAdapter(
            client,
            base_url="https://model.example/v1",
            api_key="secret",
            model="test-model",
            retry_attempts=2,
        )
        value = await adapter.interpret(
            request_id,
            "More Kirov city news",
            ProfileSnapshot(uuid4(), 0, ()),
            (),
        )

    assert calls == 2
    assert value["request_id"] == str(request_id)


async def test_explicit_interpretation_fails_closed_when_unconfigured() -> None:
    async with httpx.AsyncClient() as client:
        adapter = StructuredPreferenceModelAdapter(
            client,
            base_url="",
            api_key="",
            model="",
        )
        with pytest.raises(InterpretationFailed):
            await adapter.interpret(
                uuid4(),
                "More Kirov city news",
                ProfileSnapshot(uuid4(), 0, ()),
                (),
            )


async def test_explicit_interpretation_response_size_is_bounded() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, content=b"x" * 101)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = StructuredPreferenceModelAdapter(
            client,
            base_url="https://model.example/v1",
            api_key="secret",
            model="test-model",
            max_response_bytes=100,
        )
        with pytest.raises(InterpretationFailed):
            await adapter.interpret(
                uuid4(),
                "More Kirov city news",
                ProfileSnapshot(uuid4(), 0, ()),
                (),
            )
