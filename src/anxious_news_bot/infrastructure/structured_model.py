from __future__ import annotations

import json
import logging
import time
from collections.abc import Mapping
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

LOGGER = logging.getLogger(__name__)


def _openai_compatible_schema(value: Any) -> Any:
    if isinstance(value, list):
        return [_openai_compatible_schema(item) for item in value]
    if not isinstance(value, Mapping):
        return value

    normalized = {
        ("anyOf" if key == "oneOf" else key): _openai_compatible_schema(item)
        for key, item in value.items()
        if key not in {"default", "discriminator"}
    }
    properties = normalized.get("properties")
    if isinstance(properties, dict):
        normalized["required"] = list(properties)
    return normalized


class StructuredModelTransport:
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
        if retry_attempts < 1:
            raise ValueError("retry_attempts must be positive")
        self._retry_attempts = retry_attempts
        self._max_response_bytes = max_response_bytes

    @property
    def configured(self) -> bool:
        return bool(self._base_url and self._api_key and self._model)

    async def request(
        self,
        name: str,
        prompt: Mapping[str, Any],
        schema: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        retrying = AsyncRetrying(
            stop=stop_after_attempt(self._retry_attempts),
            wait=wait_exponential(min=0.2, max=2),
            retry=retry_if_exception(self._is_transient),
            reraise=True,
        )
        async for attempt in retrying:
            started = time.monotonic()
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
                                "schema": _openai_compatible_schema(schema),
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
                LOGGER.info(
                    "structured_model_request_completed",
                    extra={
                        "model": {
                            "operation": name,
                            "status": "succeeded",
                            "attempt": attempt.retry_state.attempt_number,
                            "attempt_limit": self._retry_attempts,
                            "duration_ms": round((time.monotonic() - started) * 1000),
                            "response_bytes": len(response.content),
                            "http_status": response.status_code,
                        }
                    },
                )
                return value
        raise RuntimeError("unreachable")

    @staticmethod
    def _is_transient(exc: BaseException) -> bool:
        if isinstance(exc, httpx.TransportError):
            return True
        if isinstance(exc, httpx.HTTPStatusError):
            status_code = exc.response.status_code
            return status_code == 429 or status_code >= 500
        return False
