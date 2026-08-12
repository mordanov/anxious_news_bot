import json
from io import StringIO
from uuid import uuid4

from anxious_news_bot.news.services.source_catalog import (
    CatalogApplyResult,
    CatalogChangePlan,
    CatalogValidationIssue,
    CatalogValidationResult,
)


class FakeService:
    def __init__(self, *, valid=True) -> None:
        self.valid = valid
        self.applied: list[bool] = []

    def validate(self, document):
        del document
        if self.valid:
            return CatalogValidationResult(True)
        return CatalogValidationResult(
            False,
            errors=(
                CatalogValidationIssue(
                    "schema_validation",
                    "catalog does not match the source-catalog schema",
                ),
            ),
        )

    async def apply(self, document, *, dry_run=False):
        del document
        self.applied.append(dry_run)
        return CatalogApplyResult(
            CatalogChangePlan(added=(uuid4(),)),
            dry_run=dry_run,
        )


async def test_validate_cli_reads_json_and_reports_sanitized_success(
    monkeypatch,
) -> None:
    from anxious_news_bot.news import cli

    monkeypatch.setattr(
        cli.Path,
        "read_text",
        lambda self, encoding: json.dumps(
            {"schema_version": "1.0", "sources": []}
        ),
    )
    output = StringIO()

    status = await cli.run_cli(
        ["validate", "catalog.json"],
        service=FakeService(),
        stdout=output,
    )

    assert status == 0
    assert output.getvalue().strip() == "valid"


async def test_apply_cli_supports_dry_run_without_exposing_catalog_values(
    monkeypatch,
) -> None:
    from anxious_news_bot.news import cli

    secret = "credential-production-secret"
    monkeypatch.setattr(
        cli.Path,
        "read_text",
        lambda self, encoding: json.dumps({"credential_ref": secret}),
    )
    service = FakeService()
    output = StringIO()

    status = await cli.run_cli(
        ["apply", "--dry-run", "catalog.json"],
        service=service,
        stdout=output,
    )

    assert status == 0
    assert service.applied == [True]
    assert "dry-run" in output.getvalue()
    assert secret not in output.getvalue()


async def test_cli_returns_nonzero_for_invalid_json(monkeypatch) -> None:
    from anxious_news_bot.news import cli

    monkeypatch.setattr(
        cli.Path, "read_text", lambda self, encoding: "{not-json"
    )
    errors = StringIO()

    status = await cli.run_cli(
        ["validate", "catalog.json"],
        service=FakeService(),
        stderr=errors,
    )

    assert status != 0
    assert errors.getvalue().strip() == "invalid catalog JSON"
