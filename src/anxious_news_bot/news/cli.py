from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import TextIO

from anxious_news_bot.news.domain import SourceType
from anxious_news_bot.news.infrastructure.database import Database
from anxious_news_bot.news.infrastructure.persistence import SQLAlchemyNewsRepository
from anxious_news_bot.news.services.source_catalog import (
    CatalogApplyResult,
    CatalogValidationError,
    SourceAdapterRegistry,
    SourceCatalogService,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="anxious-news-sources")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("file")
    apply = commands.add_parser("apply")
    apply.add_argument("--dry-run", action="store_true")
    apply.add_argument("file")
    return parser


def _database_url() -> str:
    value = os.getenv("DATABASE_URL", "postgresql+psycopg://localhost/anxious_news")
    if value.startswith("postgres://"):
        return f"postgresql+psycopg://{value.removeprefix('postgres://')}"
    if value.startswith("postgresql://"):
        return f"postgresql+psycopg://{value.removeprefix('postgresql://')}"
    return value


def _registry() -> SourceAdapterRegistry:
    supported = object()
    return SourceAdapterRegistry(
        {SourceType.RSS: supported, SourceType.ATOM: supported}
    )


def _summary(result: CatalogApplyResult) -> str:
    prefix = "dry-run " if result.dry_run else ""
    fields = (
        ("added", result.plan.added),
        ("updated", result.plan.updated),
        ("unchanged", result.plan.unchanged),
    )
    return prefix + " ".join(
        f"{name}={','.join(str(value) for value in values) or '-'}"
        for name, values in fields
    )


async def run_cli(
    argv: list[str] | None = None,
    *,
    service: SourceCatalogService | object | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    output = stdout or sys.stdout
    errors = stderr or sys.stderr
    arguments = _parser().parse_args(argv)
    try:
        document = json.loads(Path(arguments.file).read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print("invalid catalog JSON", file=errors)
        return 2
    except OSError:
        print("unable to read catalog file", file=errors)
        return 2

    database: Database | None = None
    if service is None:
        if arguments.command == "apply":
            database = Database(_database_url())
            repository = SQLAlchemyNewsRepository(database)
            service = SourceCatalogService(repository, _registry())
        else:
            service = SourceCatalogService(adapter_registry=_registry())

    try:
        if arguments.command == "validate":
            validation = service.validate(document)
            if not validation.valid:
                for issue in validation.errors:
                    locations = ",".join(str(index) for index in issue.source_indexes)
                    suffix = f" sources={locations}" if locations else ""
                    print(f"{issue.code}{suffix}", file=errors)
                return 1
            print("valid", file=output)
            return 0
        result = await service.apply(document, dry_run=arguments.dry_run)
        print(_summary(result), file=output)
        return 0
    except CatalogValidationError as exc:
        for issue in exc.errors:
            print(issue.code, file=errors)
        return 1
    except Exception:
        print("catalog apply failed", file=errors)
        return 1
    finally:
        if database is not None:
            await database.close()


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(run_cli(argv))
