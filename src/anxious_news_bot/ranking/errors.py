from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from anxious_news_bot.news.errors import DiagnosticContext


class RankingError(Exception):
    default_code = "ranking_error"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code or self.default_code
        self.context = DiagnosticContext.sanitized(context)


class ExplicitRequestError(RankingError):
    default_code = "explicit_request_error"


class EvaluationError(RankingError):
    default_code = "evaluation_error"


class RankingConfigurationError(RankingError):
    default_code = "ranking_configuration_error"


class StaleSnapshotError(RankingError):
    default_code = "stale_snapshot_error"


class RankingRunError(RankingError):
    default_code = "ranking_run_error"


class RetentionError(RankingError):
    default_code = "retention_error"
