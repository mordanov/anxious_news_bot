from datetime import UTC, datetime
from uuid import uuid4

import pytest

from anxious_news_bot.news.domain import NewsSource, RawArticle, SourceType
from anxious_news_bot.news.services.canonicalize import (
    CanonicalURLPolicy,
    InvalidURL,
)
from anxious_news_bot.news.services.normalize import DeterministicArticleNormalizer


@pytest.mark.parametrize(
    ("value", "base_url", "expected"),
    [
        (
            "HTTPS://Example.COM:443/a/../story?b=2&utm_source=x&a=1#part",
            None,
            "https://example.com/story?a=1&b=2",
        ),
        (
            "/news/%7Euser?z=&fbclid=secret",
            "https://Example.com/feed.xml",
            "https://example.com/news/~user?z=",
        ),
        (
            "http://EXAMPLE.com:80/path/",
            None,
            "http://example.com/path/",
        ),
        (
            "https://example.com/article?id=2&id=1",
            None,
            "https://example.com/article?id=1&id=2",
        ),
    ],
)
def test_canonical_url_policy_is_deterministic(
    value: str, base_url: str | None, expected: str
) -> None:
    policy = CanonicalURLPolicy(
        version="2026-08",
        tracking_parameters=("utm_source", "fbclid"),
    )

    assert policy.canonicalize(value, base_url=base_url) == expected
    assert policy.canonicalize(expected) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        "ftp://example.com/story",
        "https:///missing-host",
        "https://user:password@example.com/story",
    ],
)
def test_canonical_url_policy_rejects_unsafe_or_invalid_urls(value: str) -> None:
    with pytest.raises(InvalidURL):
        CanonicalURLPolicy().canonicalize(value)


def test_normalizer_validates_and_normalizes_a_record() -> None:
    source = NewsSource(
        id=uuid4(),
        name="Example",
        source_type=SourceType.RSS,
        endpoint_url="https://example.com/feed.xml",
        region="World",
        language_code="en",
    )
    observed_at = datetime(2026, 8, 12, 12, tzinfo=UTC)
    raw = RawArticle(
        source_id=source.id,
        original_url="/story?utm_source=feed&id=7",
        title="  Major   story \n",
        summary="<p>A useful   summary.</p>",
        content="<div>Full <b>article</b> text.</div>",
        external_id=" item-7 ",
        published_at=datetime(2026, 8, 12, 10),
        language_code="EN_us",
        payload={"b": 2, "a": 1},
    )
    normalizer = DeterministicArticleNormalizer(
        CanonicalURLPolicy(version="v1", tracking_parameters=("utm_source",))
    )

    result = normalizer.normalize(source, raw, observed_at)

    assert result.accepted
    assert result.candidate is not None
    assert result.candidate.canonical_url == "https://example.com/story?id=7"
    assert result.candidate.title == "Major story"
    assert result.candidate.summary == "A useful summary."
    assert result.candidate.normalized_text == "Major story Full article text."
    assert result.candidate.language_code == "en-us"
    assert result.candidate.published_at == datetime(2026, 8, 12, 10, tzinfo=UTC)
    assert result.candidate.canonicalization_version == "v1"
    assert len(result.candidate.payload_hash) == 64


@pytest.mark.parametrize(
    ("title", "url", "code"),
    [
        (None, "https://example.com/a", "missing_title"),
        (" \n ", "https://example.com/a", "missing_title"),
        ("Title", "", "missing_url"),
        ("Title", "javascript:alert(1)", "invalid_url"),
    ],
)
def test_normalizer_returns_typed_rejections(
    title: str | None, url: str, code: str
) -> None:
    source = NewsSource(
        id=uuid4(),
        name="Example",
        source_type=SourceType.RSS,
        endpoint_url="https://example.com/feed.xml",
        region="World",
        language_code="en",
    )
    raw = RawArticle(source.id, url, title)

    result = DeterministicArticleNormalizer().normalize(
        source, raw, datetime(2026, 8, 12, tzinfo=UTC)
    )

    assert not result.accepted
    assert result.rejection_code == code
    assert "title" not in result.diagnostic_context
