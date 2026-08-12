from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from anxious_news_bot.news.domain import (
    ConditionalHeaders,
    FetchResult,
    FetchStatus,
    NewsSource,
    SourceType,
)
from anxious_news_bot.news.services.source_catalog import (
    CatalogChangePlan,
    SourceAdapterRegistry,
    SourceAdapterRouter,
    SourceCatalogService,
)


SOURCE_ID = uuid4()


def catalog(**source_changes):
    source = {
        "id": str(SOURCE_ID),
        "name": "Example",
        "source_type": "rss",
        "endpoint_url": "https://example.com/feed",
        "region": "Antarctica",
        "country_code": None,
        "language_code": "en",
        "enabled": True,
        "quality_score": 0.8,
        "polling_interval_seconds": 300,
        "credential_ref": None,
    }
    source.update(source_changes)
    return {"schema_version": "1.0", "sources": [source]}


@pytest.mark.parametrize(
    "change",
    [
        {"unexpected": "value"},
        {"enabled": "true"},
        {"polling_interval_seconds": 59},
        {"endpoint_url": "ftp://example.com/feed"},
        {"endpoint_url": "HTTPS://example.com/feed"},
        {"country_code": "gb"},
        {"quality_score": 1.1},
        {"id": f"urn:uuid:{SOURCE_ID}"},
    ],
)
def test_catalog_validation_strictly_matches_schema(change) -> None:
    result = SourceCatalogService().validate(catalog(**change))

    assert not result.valid
    assert result.errors


def test_catalog_detects_duplicate_ids_and_equivalent_endpoints() -> None:
    document = catalog()
    duplicate = deepcopy(document["sources"][0])
    duplicate["name"] = "Duplicate"
    duplicate["endpoint_url"] = "https://EXAMPLE.com:443/feed#fragment"
    document["sources"].append(duplicate)

    result = SourceCatalogService().validate(document)

    assert not result.valid
    assert {error.code for error in result.errors} == {
        "duplicate_source_id",
        "duplicate_endpoint",
    }
    assert all("example.com" not in error.message for error in result.errors)


def test_new_regions_are_accepted_but_unsupported_adapters_are_rejected() -> None:
    registry = SourceAdapterRegistry()
    registry.register(SourceType.RSS, object())
    service = SourceCatalogService(adapter_registry=registry)

    assert service.validate(catalog(region="Antarctica")).valid
    unsupported = service.validate(catalog(source_type="atom"))

    assert not unsupported.valid
    assert [error.code for error in unsupported.errors] == [
        "unsupported_source_type"
    ]


class RecordingAdapter:
    def __init__(self, marker: str) -> None:
        self.marker = marker
        self.calls: list[UUID] = []

    async def fetch(self, source, conditional_headers):
        del conditional_headers
        self.calls.append(source.id)
        return FetchResult(FetchStatus.FETCHED)


async def test_adapter_router_selects_by_type_without_region_logic() -> None:
    rss = RecordingAdapter("rss")
    atom = RecordingAdapter("atom")
    registry = SourceAdapterRegistry(
        {SourceType.RSS: rss, SourceType.ATOM: atom}
    )
    router = SourceAdapterRouter(registry)
    source = NewsSource(
        SOURCE_ID,
        "Polar feed",
        SourceType.ATOM,
        "https://example.com/atom",
        "New Unrecognized Region",
        "en",
    )

    result = await router.fetch(source, ConditionalHeaders())

    assert result.status is FetchStatus.FETCHED
    assert atom.calls == [SOURCE_ID]
    assert rss.calls == []


class FakeCatalogRepository:
    def __init__(self) -> None:
        self.upsert_calls = 0

    @asynccontextmanager
    async def unit_of_work(self):
        yield self

    async def plan_source_catalog(self, entries):
        return CatalogChangePlan(added=(entries[0].id,))

    async def upsert_source_catalog(self, entries):
        self.upsert_calls += 1
        return CatalogChangePlan(added=(entries[0].id,))


async def test_dry_run_returns_sanitized_plan_without_writing() -> None:
    repository = FakeCatalogRepository()
    registry = SourceAdapterRegistry({SourceType.RSS: object()})
    service = SourceCatalogService(repository, registry)

    result = await service.apply(catalog(credential_ref="secret-name"), dry_run=True)

    assert result.dry_run
    assert result.plan.added == (SOURCE_ID,)
    assert repository.upsert_calls == 0
    assert "secret" not in repr(result)
