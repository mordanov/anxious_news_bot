from __future__ import annotations

import asyncio
from collections.abc import Mapping
from decimal import Decimal
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from anxious_news_bot.news.domain import (
    AnalysisStatus,
    ArticleAnalysis,
    EnrichmentResult,
    NormalizedArticle,
)
from anxious_news_bot.news.ports import ArticleEnricher, Clock
from anxious_news_bot.news.schemas import EnrichmentEnvelopeSchema, SECTION_ADAPTERS


class ArticleEnrichmentService:
    def __init__(
        self,
        enricher: ArticleEnricher,
        clock: Clock,
        *,
        analyzer_name: str,
        analyzer_version: str,
    ) -> None:
        if not analyzer_name.strip() or not analyzer_version.strip():
            raise ValueError("analyzer name and version must be non-empty")
        self._enricher = enricher
        self._clock = clock
        self._analyzer_name = analyzer_name
        self._analyzer_version = analyzer_version

    async def enrich_article(
        self, article: NormalizedArticle
    ) -> ArticleAnalysis:
        try:
            raw_result = await self._enricher.enrich(article)
        except asyncio.CancelledError:
            raise
        except Exception:
            return self._empty_analysis(
                article, AnalysisStatus.FAILED, "1.0", "enrichment_failed"
            )

        try:
            payload = self._payload(raw_result)
            envelope = EnrichmentEnvelopeSchema.model_validate(payload)
        except (ValidationError, TypeError, ValueError):
            return self._empty_analysis(
                article,
                AnalysisStatus.INVALID,
                "1.0",
                "invalid_enrichment_result",
            )

        if envelope.status == "failed":
            return self._empty_analysis(
                article,
                AnalysisStatus.FAILED,
                envelope.schema_version,
                "enrichment_failed",
            )
        if envelope.status == "invalid":
            return self._empty_analysis(
                article,
                AnalysisStatus.INVALID,
                envelope.schema_version,
                "invalid_enrichment_result",
            )

        valid: dict[str, Any] = {}
        invalid: list[str] = []
        for name in sorted(envelope.sections):
            try:
                valid[name] = SECTION_ADAPTERS[name].validate_python(
                    envelope.sections[name], strict=True
                )
            except ValidationError:
                invalid.append(name)

        if invalid and not valid:
            status = AnalysisStatus.INVALID
        elif invalid or envelope.status == "partial" or envelope.errors:
            status = AnalysisStatus.PARTIAL
        else:
            status = AnalysisStatus.COMPLETE
        error_code = self._invalid_sections_code(invalid)
        if error_code is None and envelope.errors:
            error_code = "enrichment_reported_errors"
        semantic = valid.get("semantic_metadata")
        semantic_metadata = (
            semantic.model_dump(exclude_none=True) if semantic is not None else None
        )
        return ArticleAnalysis(
            id=uuid4(),
            article_id=article.id,
            status=status,
            schema_version=envelope.schema_version,
            analyzer_name=self._analyzer_name,
            analyzer_version=self._analyzer_version,
            created_at=self._clock.now(),
            topics=valid.get("topics", ()),
            countries=valid.get("countries", ()),
            cities=valid.get("cities", ()),
            locations=valid.get("locations", ()),
            people=valid.get("people", ()),
            organizations=valid.get("organizations", ()),
            event_type=valid.get("event_type"),
            importance_score=self._decimal(valid.get("importance")),
            novelty_score=self._decimal(valid.get("novelty")),
            source_quality_score=self._decimal(valid.get("source_quality")),
            semantic_metadata=semantic_metadata,
            error_code=error_code,
        )

    def _empty_analysis(
        self,
        article: NormalizedArticle,
        status: AnalysisStatus,
        schema_version: str,
        error_code: str,
    ) -> ArticleAnalysis:
        return ArticleAnalysis(
            id=uuid4(),
            article_id=article.id,
            status=status,
            schema_version=schema_version,
            analyzer_name=self._analyzer_name,
            analyzer_version=self._analyzer_version,
            created_at=self._clock.now(),
            error_code=error_code,
        )

    @staticmethod
    def _payload(result: object) -> Mapping[str, Any]:
        if isinstance(result, EnrichmentResult):
            return {
                "schema_version": result.schema_version,
                "status": result.status.value,
                "sections": dict(result.sections),
                "errors": tuple(result.errors),
            }
        if not isinstance(result, Mapping):
            raise TypeError("enrichment result must be a mapping")
        return result

    @staticmethod
    def _decimal(value: object) -> Decimal | None:
        return Decimal(str(value)) if value is not None else None

    @staticmethod
    def _invalid_sections_code(invalid: list[str]) -> str | None:
        if not invalid:
            return None
        code = f"invalid_sections:{','.join(invalid)}"
        return code if len(code) <= 100 else "invalid_sections:multiple"
