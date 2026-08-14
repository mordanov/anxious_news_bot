from unittest.mock import Mock

import httpx

from anxious_news_bot.infrastructure.structured_model import StructuredModelTransport


async def test_structured_model_logs_request_timing(monkeypatch) -> None:
    info_log = Mock()
    monkeypatch.setattr(
        "anxious_news_bot.infrastructure.structured_model.LOGGER.info",
        info_log,
    )

    async def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            json={"choices": [{"message": {"content": '{"value":"ok"}'}}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await StructuredModelTransport(
            client,
            base_url="https://model.example/v1",
            api_key="secret",
            model="test-model",
        ).request(
            "test_operation",
            {"input": "private"},
            {
                "type": "object",
                "properties": {"value": {"type": "string"}},
            },
        )

    assert result == {"value": "ok"}
    fields = info_log.call_args.kwargs["extra"]["model"]
    assert fields["operation"] == "test_operation"
    assert fields["status"] == "succeeded"
    assert fields["attempt"] == 1
    assert fields["http_status"] == 200
    assert fields["duration_ms"] >= 0
    assert "input" not in fields
    assert "api_key" not in fields
