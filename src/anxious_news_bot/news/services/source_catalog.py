from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from decimal import Decimal
import re
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from typing_extensions import Literal

from anxious_news_bot.news.domain import (
    ConditionalHeaders,
    FetchResult,
    NewsSource,
    SourceType,
)

_UUID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


@dataclass(frozen=True, slots=True)
class CatalogSource:
    id: UUID
    name: str
    source_type: SourceType
    endpoint_url: str
    region: str
    country_code: str | None
    language_code: str
    enabled: bool
    quality_score: Decimal | None
    polling_interval_seconds: int
    credential_ref: str | None


@dataclass(frozen=True, slots=True)
class CatalogValidationIssue:
    code: str
    message: str
    source_indexes: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class CatalogValidationResult:
    valid: bool
    entries: tuple[CatalogSource, ...] = ()
    errors: tuple[CatalogValidationIssue, ...] = ()


@dataclass(frozen=True, slots=True)
class CatalogChangePlan:
    added: tuple[UUID, ...] = ()
    updated: tuple[UUID, ...] = ()
    unchanged: tuple[UUID, ...] = ()


@dataclass(frozen=True, slots=True)
class CatalogApplyResult:
    plan: CatalogChangePlan
    dry_run: bool = False


class CatalogValidationError(ValueError):
    def __init__(self, errors: Sequence[CatalogValidationIssue]) -> None:
        super().__init__("source catalog validation failed")
        self.errors = tuple(errors)


class _CatalogSourceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str = Field(min_length=1, max_length=200)
    source_type: Literal["rss", "atom"]
    endpoint_url: str
    region: str = Field(min_length=1, max_length=100)
    country_code: str | None = None
    language_code: str = Field(min_length=2, max_length=35)
    enabled: bool
    quality_score: Decimal | None = Field(default=None, ge=0, le=1)
    polling_interval_seconds: int = Field(ge=60, le=604800)
    credential_ref: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("id")
    @classmethod
    def valid_uuid(cls, value: object) -> str:
        if not isinstance(value, str) or not _UUID_PATTERN.fullmatch(value):
            raise ValueError("must be a UUID string")
        UUID(value)
        return value

    @field_validator("name", "region")
    @classmethod
    def non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("country_code")
    @classmethod
    def valid_country_code(cls, value: str | None) -> str | None:
        if value is not None and (
            len(value) != 2 or not value.isascii() or not value.isupper()
        ):
            raise ValueError("must be an uppercase ISO alpha-2 code")
        return value

    @field_validator("enabled", mode="before")
    @classmethod
    def strict_boolean(cls, value: object) -> object:
        if not isinstance(value, bool):
            raise ValueError("must be a boolean")
        return value

    @field_validator("polling_interval_seconds", mode="before")
    @classmethod
    def strict_integer(cls, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("must be an integer")
        return value

    @field_validator("quality_score", mode="before")
    @classmethod
    def strict_number(cls, value: object) -> object:
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, (int, float, Decimal))
        ):
            raise ValueError("must be a number")
        return value

    @field_validator("endpoint_url")
    @classmethod
    def valid_endpoint(cls, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("must be a URI string")
        parsed = urlsplit(value)
        if (
            not value.startswith(("http://", "https://"))
            or not value.isascii()
            or parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or any(character.isspace() for character in value)
        ):
            raise ValueError("must be an HTTP(S) URI")
        try:
            parsed.port
        except ValueError as exc:
            raise ValueError("must contain a valid port") from exc
        return value


class _CatalogModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    sources: list[_CatalogSourceModel] = Field(min_length=1)


class SourceAdapter(Protocol):
    async def fetch(
        self,
        source: NewsSource,
        conditional_headers: ConditionalHeaders,
    ) -> FetchResult: ...


class SourceAdapterRegistry:
    def __init__(
        self, adapters: Mapping[SourceType, SourceAdapter | object] | None = None
    ) -> None:
        self._adapters = dict(adapters or {})

    def register(
        self, source_type: SourceType, adapter: SourceAdapter | object
    ) -> None:
        self._adapters[source_type] = adapter

    def supports(self, source_type: SourceType) -> bool:
        return source_type in self._adapters

    def get(self, source_type: SourceType) -> SourceAdapter:
        try:
            adapter = self._adapters[source_type]
        except KeyError as exc:
            raise LookupError(
                f"no adapter registered for source type {source_type.value}"
            ) from exc
        if not hasattr(adapter, "fetch"):
            raise TypeError(
                f"adapter for source type {source_type.value} cannot fetch"
            )
        return adapter  # type: ignore[return-value]


class SourceAdapterRouter:
    def __init__(self, registry: SourceAdapterRegistry) -> None:
        self._registry = registry

    async def fetch(
        self,
        source: NewsSource,
        conditional_headers: ConditionalHeaders,
    ) -> FetchResult:
        adapter = self._registry.get(source.source_type)
        return await adapter.fetch(source, conditional_headers)


class CatalogRepository(Protocol):
    def unit_of_work(self) -> AbstractAsyncContextManager["CatalogRepository"]: ...

    async def plan_source_catalog(
        self, entries: Sequence[CatalogSource]
    ) -> CatalogChangePlan: ...

    async def upsert_source_catalog(
        self, entries: Sequence[CatalogSource]
    ) -> CatalogChangePlan: ...


class SourceCatalogService:
    def __init__(
        self,
        repository: CatalogRepository | None = None,
        adapter_registry: SourceAdapterRegistry | None = None,
    ) -> None:
        self._repository = repository
        self._adapter_registry = adapter_registry

    def validate(self, catalog: Mapping[str, Any] | object) -> CatalogValidationResult:
        try:
            model = _CatalogModel.model_validate(catalog)
        except ValidationError as exc:
            errors = tuple(
                CatalogValidationIssue(
                    code="schema_validation",
                    message="catalog does not match the source-catalog schema",
                    source_indexes=self._source_indexes(error.get("loc", ())),
                )
                for error in exc.errors(include_input=False)
            )
            return CatalogValidationResult(False, errors=errors)

        entries = tuple(self._entry(item) for item in model.sources)
        errors: list[CatalogValidationIssue] = []
        identifiers: dict[UUID, int] = {}
        endpoints: dict[str, int] = {}
        for index, entry in enumerate(entries):
            previous_id = identifiers.setdefault(entry.id, index)
            if previous_id != index:
                errors.append(
                    CatalogValidationIssue(
                        "duplicate_source_id",
                        "catalog contains a duplicate source identifier",
                        (previous_id, index),
                    )
                )
            endpoint_key = _endpoint_identity(entry.endpoint_url)
            previous_endpoint = endpoints.setdefault(endpoint_key, index)
            if previous_endpoint != index:
                errors.append(
                    CatalogValidationIssue(
                        "duplicate_endpoint",
                        "catalog contains a conflicting source endpoint",
                        (previous_endpoint, index),
                    )
                )
            if (
                self._adapter_registry is not None
                and not self._adapter_registry.supports(entry.source_type)
            ):
                errors.append(
                    CatalogValidationIssue(
                        "unsupported_source_type",
                        "catalog source type has no registered adapter",
                        (index,),
                    )
                )
        if errors:
            return CatalogValidationResult(False, errors=tuple(errors))
        return CatalogValidationResult(True, entries)

    async def apply(
        self,
        catalog: Mapping[str, Any] | object,
        *,
        dry_run: bool = False,
    ) -> CatalogApplyResult:
        validation = self.validate(catalog)
        if not validation.valid:
            raise CatalogValidationError(validation.errors)
        if self._repository is None:
            raise RuntimeError("catalog application requires a repository")
        async with self._repository.unit_of_work() as work:
            plan = await work.plan_source_catalog(validation.entries)
            if not dry_run:
                plan = await work.upsert_source_catalog(validation.entries)
        return CatalogApplyResult(plan, dry_run)

    @staticmethod
    def _entry(item: _CatalogSourceModel) -> CatalogSource:
        return CatalogSource(
            id=UUID(item.id),
            name=item.name,
            source_type=SourceType(item.source_type),
            endpoint_url=item.endpoint_url,
            region=item.region,
            country_code=item.country_code,
            language_code=item.language_code,
            enabled=item.enabled,
            quality_score=item.quality_score,
            polling_interval_seconds=item.polling_interval_seconds,
            credential_ref=item.credential_ref,
        )

    @staticmethod
    def _source_indexes(location: Sequence[str | int]) -> tuple[int, ...]:
        if len(location) >= 2 and location[0] == "sources":
            index = location[1]
            if isinstance(index, int):
                return (index,)
        return ()


def _endpoint_identity(value: str) -> str:
    parsed = urlsplit(value)
    hostname = parsed.hostname.lower() if parsed.hostname else ""
    port = parsed.port
    default_port = (parsed.scheme == "http" and port == 80) or (
        parsed.scheme == "https" and port == 443
    )
    netloc = hostname if port is None or default_port else f"{hostname}:{port}"
    path = parsed.path or "/"
    return urlunsplit((parsed.scheme.lower(), netloc, path, parsed.query, ""))
