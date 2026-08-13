from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from anxious_news_bot.news.domain import AnalysisStatus, NormalizedArticle
from anxious_news_bot.news.services.enrich import ArticleEnrichmentService

NOW = datetime(2026, 8, 12, 12, tzinfo=UTC)


class FixedClock:
    def now(self) -> datetime:
        return NOW


class FakeEnricher:
    def __init__(self, result: object = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.articles: list[NormalizedArticle] = []

    async def enrich(self, article: NormalizedArticle):
        self.articles.append(article)
        if self.error is not None:
            raise self.error
        return self.result


def article() -> NormalizedArticle:
    return NormalizedArticle(
        uuid4(),
        "Title",
        "Summary",
        "https://example.com/article",
        "1.0",
        uuid4(),
        NOW,
        NOW,
        "en",
        "title summary",
        uuid4(),
    )


def service(enricher: FakeEnricher) -> ArticleEnrichmentService:
    return ArticleEnrichmentService(
        enricher,
        FixedClock(),
        analyzer_name="fake",
        analyzer_version="2026-08",
    )


async def test_complete_result_maps_all_validated_sections() -> None:
    enricher = FakeEnricher(
        {
            "schema_version": "1.0",
            "status": "complete",
            "sections": {
                "topics": ["economy"],
                "countries": ["ES"],
                "cities": ["Madrid"],
                "locations": ["Community of Madrid"],
                "people": ["Person"],
                "organizations": ["Org"],
                "event_type": "policy",
                "importance": Decimal("0.8"),
                "novelty": Decimal("0.6"),
                "source_quality": Decimal("0.9"),
                "semantic_metadata": {"model": "fake-v1"},
            },
        }
    )

    analysis = await service(enricher).enrich_article(article())

    assert analysis.status is AnalysisStatus.COMPLETE
    assert analysis.topics == ("economy",)
    assert analysis.countries == ("ES",)
    assert analysis.locations == ("Community of Madrid",)
    assert analysis.importance_score == Decimal("0.8")
    assert analysis.semantic_metadata == {"model": "fake-v1"}


async def test_invalid_section_is_dropped_while_valid_sections_survive() -> None:
    enricher = FakeEnricher(
        {
            "schema_version": "1.0",
            "status": "partial",
            "sections": {
                "topics": ["economy"],
                "countries": ["Spain"],
                "importance": Decimal("0.7"),
            },
            "errors": [{"section": "countries", "code": "invalid_country"}],
        }
    )

    analysis = await service(enricher).enrich_article(article())

    assert analysis.status is AnalysisStatus.PARTIAL
    assert analysis.topics == ("economy",)
    assert analysis.countries == ()
    assert analysis.importance_score == Decimal("0.7")
    assert analysis.error_code == "invalid_sections:countries"


async def test_wholly_invalid_result_degrades_without_metadata() -> None:
    analysis = await service(
        FakeEnricher(
            {
                "schema_version": "1.0",
                "status": "complete",
                "sections": {"importance": Decimal(2)},
            }
        )
    ).enrich_article(article())

    assert analysis.status is AnalysisStatus.INVALID
    assert analysis.importance_score is None
    assert analysis.error_code == "invalid_sections:importance"


async def test_enricher_failure_is_sanitized_and_article_is_not_mutated() -> None:
    source_article = article()
    analysis = await service(
        FakeEnricher(error=RuntimeError("secret provider payload"))
    ).enrich_article(source_article)

    assert analysis.article_id == source_article.id
    assert analysis.status is AnalysisStatus.FAILED
    assert analysis.error_code == "enrichment_failed"
    assert "secret" not in repr(analysis)


async def test_user_specific_data_is_never_accepted() -> None:
    analysis = await service(
        FakeEnricher(
            {
                "schema_version": "1.0",
                "status": "complete",
                "sections": {"topics": ["economy"]},
                "user_profile": {"interests": ["economy"]},
            }
        )
    ).enrich_article(article())

    assert analysis.status is AnalysisStatus.INVALID
    assert analysis.topics == ()
    assert analysis.error_code == "invalid_enrichment_result"
