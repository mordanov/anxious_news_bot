from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from anxious_news_bot.news.domain import (
    ConditionalHeaders,
    FetchStatus,
    NewsSource,
    SourceType,
)
from anxious_news_bot.news.errors import SourceRejected, SourceUnavailable
from anxious_news_bot.news.infrastructure.feeds import FeedFetcher

FIXTURES = Path(__file__).parents[2] / "fixtures" / "feeds"


def source(url: str = "https://feeds.example.test/news") -> NewsSource:
    return NewsSource(
        id=uuid4(),
        name="Fixture",
        source_type=SourceType.RSS,
        endpoint_url=url,
        region="World",
        language_code="en",
    )


@pytest.mark.parametrize(
    ("fixture", "expected_count"),
    [("valid_rss.xml", 2), ("valid_atom.xml", 1), ("empty_rss.xml", 0)],
)
async def test_feed_fetcher_parses_rss_atom_and_empty_feeds(
    fixture: str, expected_count: int
) -> None:
    body = (FIXTURES / fixture).read_bytes()
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            content=body,
            headers={"ETag": '"v2"', "Last-Modified": "Wed, 12 Aug 2026 10:00:00 GMT"},
            request=request,
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        result = await FeedFetcher(client, retry_attempts=1).fetch(
            source(), ConditionalHeaders()
        )

    assert result.status is FetchStatus.FETCHED
    assert len(result.records) == expected_count
    assert result.etag == '"v2"'
    assert result.last_modified == "Wed, 12 Aug 2026 10:00:00 GMT"
    if result.records:
        assert all(record.source_id for record in result.records)
        assert all(record.original_url.startswith("http") for record in result.records)


async def test_feed_fetcher_sends_conditional_headers_and_handles_304() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        return httpx.Response(304, headers={"ETag": '"same"'}, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await FeedFetcher(client, retry_attempts=1).fetch(
            source(),
            ConditionalHeaders(
                etag='"same"',
                last_modified="Tue, 11 Aug 2026 10:00:00 GMT",
            ),
        )

    assert seen["if-none-match"] == '"same"'
    assert seen["if-modified-since"] == "Tue, 11 Aug 2026 10:00:00 GMT"
    assert result.status is FetchStatus.NOT_MODIFIED
    assert result.records == ()


async def test_feed_fetcher_retries_transient_responses() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(503, request=request)
        return httpx.Response(
            200,
            content=(FIXTURES / "valid_rss.xml").read_bytes(),
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await FeedFetcher(
            client, retry_attempts=3, backoff_base_seconds=0
        ).fetch(source(), ConditionalHeaders())

    assert attempts == 3
    assert result.status is FetchStatus.FETCHED


async def test_feed_fetcher_maps_timeout_after_bounded_retries() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("slow", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceUnavailable) as error:
            await FeedFetcher(
                client, retry_attempts=2, backoff_base_seconds=0
            ).fetch(source(), ConditionalHeaders())

    assert attempts == 2
    assert error.value.code == "source_timeout"


async def test_feed_fetcher_rejects_permanent_and_malformed_responses() -> None:
    responses = [
        httpx.Response(404),
        httpx.Response(200, content=(FIXTURES / "malformed.xml").read_bytes()),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        response = responses.pop(0)
        response.request = request
        return response

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetcher = FeedFetcher(client, retry_attempts=1)
        with pytest.raises(SourceRejected, match="HTTP 404"):
            await fetcher.fetch(source(), ConditionalHeaders())
        with pytest.raises(SourceRejected) as error:
            await fetcher.fetch(source(), ConditionalHeaders())

    assert error.value.code == "malformed_feed"
