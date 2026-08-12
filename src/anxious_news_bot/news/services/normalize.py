from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any

from anxious_news_bot.news.domain import (
    NewsSource,
    NormalizationResult,
    NormalizedArticleCandidate,
    RawArticle,
)
from anxious_news_bot.news.services.canonicalize import (
    CanonicalURLPolicy,
    InvalidURL,
)

_WHITESPACE = re.compile(r"\s+")
_LANGUAGE = re.compile(r"^[a-z]{2,3}(?:-[a-z0-9]{2,8})*$")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _plain_text(value: str | None) -> str:
    if not value:
        return ""
    parser = _TextExtractor()
    try:
        parser.feed(value)
        text = " ".join(parser.parts)
    except Exception:
        text = value
    return _WHITESPACE.sub(" ", html.unescape(text)).strip()


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return _utc(value).isoformat()  # type: ignore[union-attr]
    return str(value)


class DeterministicArticleNormalizer:
    def __init__(self, url_policy: CanonicalURLPolicy | None = None) -> None:
        self._url_policy = url_policy or CanonicalURLPolicy()

    def normalize(
        self,
        source: NewsSource,
        raw_article: RawArticle,
        observed_at: datetime,
    ) -> NormalizationResult:
        title = _plain_text(raw_article.title)
        if not title:
            return NormalizationResult(
                rejection_code="missing_title",
                diagnostic_context={"field": "title"},
            )
        if not raw_article.original_url.strip():
            return NormalizationResult(
                rejection_code="missing_url",
                diagnostic_context={"field": "original_url"},
            )
        try:
            canonical_url = self._url_policy.canonicalize(
                raw_article.original_url,
                base_url=source.endpoint_url,
            )
        except InvalidURL:
            return NormalizationResult(
                rejection_code="invalid_url",
                diagnostic_context={"field": "original_url"},
            )

        summary = _plain_text(raw_article.summary) or None
        content = _plain_text(raw_article.content)
        normalized_text = _WHITESPACE.sub(
            " ", " ".join(part for part in (title, content or summary) if part)
        ).strip()
        language = (raw_article.language_code or source.language_code).strip()
        language = language.replace("_", "-").casefold()
        if not _LANGUAGE.fullmatch(language):
            return NormalizationResult(
                rejection_code="invalid_language",
                diagnostic_context={"field": "language_code"},
            )
        observed_utc = _utc(observed_at)
        if observed_utc is None:
            raise ValueError("observed_at is required")
        payload_value = raw_article.payload or {
            "external_id": raw_article.external_id,
            "url": raw_article.original_url,
            "title": raw_article.title,
            "summary": raw_article.summary,
            "content": raw_article.content,
            "published_at": raw_article.published_at,
        }
        encoded_payload = json.dumps(
            payload_value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=_json_default,
        ).encode()
        return NormalizationResult(
            candidate=NormalizedArticleCandidate(
                source_id=source.id,
                title=title,
                summary=summary,
                canonical_url=canonical_url,
                original_url=raw_article.original_url.strip(),
                published_at=_utc(raw_article.published_at),
                ingested_at=observed_utc,
                language_code=language,
                normalized_text=normalized_text,
                canonicalization_version=self._url_policy.version,
                payload_hash=hashlib.sha256(encoded_payload).hexdigest(),
                external_id=(
                    raw_article.external_id.strip()
                    if raw_article.external_id
                    and raw_article.external_id.strip()
                    else None
                ),
            )
        )


ArticleNormalizer = DeterministicArticleNormalizer

