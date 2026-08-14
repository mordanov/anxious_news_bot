from __future__ import annotations

import asyncio
import calendar
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser
import httpx

from anxious_news_bot.news.domain import (
    ConditionalHeaders,
    FetchResult,
    FetchStatus,
    NewsSource,
    RawArticle,
)
from anxious_news_bot.news.errors import SourceRejected, SourceUnavailable

_TRANSIENT_STATUSES = {408, 425, 429, 500, 502, 503, 504}
_USER_AGENT = "anxious-news-bot/1.0 (+https://github.com/mordanov/anxious_news_bot)"


def _published(entry: Any) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        return datetime.fromtimestamp(calendar.timegm(parsed), tz=UTC)
    value = entry.get("published") or entry.get("updated")
    if value:
        try:
            result = parsedate_to_datetime(value)
            return (
                result.replace(tzinfo=UTC)
                if result.tzinfo is None
                else result.astimezone(UTC)
            )
        except (TypeError, ValueError):
            return None
    return None


def _content(entry: Any) -> str | None:
    values = entry.get("content") or ()
    if values and isinstance(values[0], dict):
        return values[0].get("value")
    return None


class FeedFetcher:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        retry_attempts: int = 3,
        backoff_base_seconds: float = 0.25,
    ) -> None:
        if retry_attempts < 1:
            raise ValueError("retry_attempts must be positive")
        self._client = client
        self._retry_attempts = retry_attempts
        self._backoff_base_seconds = max(0.0, backoff_base_seconds)

    async def fetch(
        self,
        source: NewsSource,
        conditional_headers: ConditionalHeaders,
    ) -> FetchResult:
        headers = {
            "Accept": "application/atom+xml, application/rss+xml, application/xml",
            "User-Agent": _USER_AGENT,
        }
        if conditional_headers.etag:
            headers["If-None-Match"] = conditional_headers.etag
        if conditional_headers.last_modified:
            headers["If-Modified-Since"] = conditional_headers.last_modified

        response: httpx.Response | None = None
        for attempt in range(1, self._retry_attempts + 1):
            try:
                response = await self._client.get(source.endpoint_url, headers=headers)
            except asyncio.CancelledError:
                raise
            except httpx.TimeoutException as exc:
                if attempt == self._retry_attempts:
                    raise SourceUnavailable(
                        "source request timed out",
                        code="source_timeout",
                        context={"source_id": str(source.id), "attempts": attempt},
                    ) from exc
            except httpx.RequestError as exc:
                if attempt == self._retry_attempts:
                    raise SourceUnavailable(
                        "source request failed",
                        code="source_connection",
                        context={"source_id": str(source.id), "attempts": attempt},
                    ) from exc
            else:
                if response.status_code not in _TRANSIENT_STATUSES:
                    break
                if attempt == self._retry_attempts:
                    raise SourceUnavailable(
                        "source remained unavailable",
                        code="source_http_transient",
                        context={
                            "source_id": str(source.id),
                            "status_code": response.status_code,
                            "attempts": attempt,
                        },
                    )
            await asyncio.sleep(self._retry_delay(response, attempt))

        if response is None:
            raise SourceUnavailable("source request failed")
        if response.status_code == 304:
            return FetchResult(
                FetchStatus.NOT_MODIFIED,
                etag=response.headers.get("etag") or conditional_headers.etag,
                last_modified=response.headers.get("last-modified")
                or conditional_headers.last_modified,
            )
        if response.status_code >= 400:
            raise SourceRejected(
                f"source returned HTTP {response.status_code}",
                code="source_http_rejected",
                context={
                    "source_id": str(source.id),
                    "status_code": response.status_code,
                },
            )

        parsed = feedparser.parse(response.content)
        if parsed.bozo and not any(
            entry.get("title") and entry.get("link") for entry in parsed.entries
        ):
            raise SourceRejected(
                "source returned a malformed feed",
                code="malformed_feed",
                context={"source_id": str(source.id)},
            )
        records = tuple(
            RawArticle(
                source_id=source.id,
                original_url=str(entry.get("link") or ""),
                title=entry.get("title"),
                summary=entry.get("summary"),
                content=_content(entry),
                external_id=entry.get("id") or entry.get("guid"),
                published_at=_published(entry),
                language_code=entry.get("language") or parsed.feed.get("language"),
                payload={
                    key: entry.get(key)
                    for key in ("id", "guid", "link", "title", "summary", "published")
                    if entry.get(key) is not None
                },
            )
            for entry in parsed.entries
        )
        return FetchResult(
            FetchStatus.FETCHED,
            records,
            response.headers.get("etag"),
            response.headers.get("last-modified"),
        )

    def _retry_delay(self, response: httpx.Response | None, attempt: int) -> float:
        if response is not None:
            retry_after = response.headers.get("retry-after")
            if retry_after:
                try:
                    return min(60.0, max(0.0, float(retry_after)))
                except ValueError:
                    try:
                        when = parsedate_to_datetime(retry_after)
                        if when.tzinfo is None:
                            when = when.replace(tzinfo=UTC)
                        return min(
                            60.0,
                            max(0.0, (when - datetime.now(UTC)).total_seconds()),
                        )
                    except (TypeError, ValueError):
                        pass
        return self._backoff_base_seconds * (2 ** (attempt - 1))
