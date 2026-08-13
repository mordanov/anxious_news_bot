from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from anxious_news_bot.news.errors import DiagnosticContext
from anxious_news_bot.ranking.domain import ArticleEvaluationIdentity

LOGGER = logging.getLogger(__name__)

_FORBIDDEN_FIELD_NAMES = frozenset(
    {
        "article",
        "articlecontent",
        "articletext",
        "content",
        "explicitstatement",
        "normalizedtext",
        "parameters",
        "profile",
        "profilesnapshot",
        "prompt",
        "rawprompt",
        "rawresponse",
        "rawstatement",
        "rawtext",
        "responsebody",
        "statement",
        "summary",
        "text",
        "title",
    }
)


def _normalized_key(key: object) -> str:
    return "".join(character for character in str(key).lower() if character.isalnum())


def _should_drop_field(key: object) -> bool:
    normalized = _normalized_key(key)
    return (
        normalized in _FORBIDDEN_FIELD_NAMES
        or normalized.endswith("prompt")
        or normalized.endswith("snapshot")
    )


def sanitized_fields(fields: Mapping[str, Any] | None) -> dict[str, Any]:
    if not fields:
        return {}
    allowed = {
        str(key): value for key, value in fields.items() if not _should_drop_field(key)
    }
    return DiagnosticContext.sanitized(allowed).as_dict()


def log_ranking_event(
    event: str,
    *,
    stage: str,
    status: str,
    user_id: UUID | str | None = None,
    article_id: UUID | str | None = None,
    evaluation_run_id: UUID | str | None = None,
    ranking_run_id: UUID | str | None = None,
    request_id: str | None = None,
    error_code: str | None = None,
    fields: Mapping[str, Any] | None = None,
    level: int = logging.INFO,
) -> None:
    payload: dict[str, Any] = {
        "event": event[:100],
        "stage": stage[:80],
        "status": status[:80],
        "user_id": str(user_id) if user_id else None,
        "article_id": str(article_id) if article_id else None,
        "evaluation_run_id": str(evaluation_run_id) if evaluation_run_id else None,
        "ranking_run_id": str(ranking_run_id) if ranking_run_id else None,
        "request_id": request_id[:200] if request_id else None,
        "error_code": error_code[:100] if error_code else None,
    }
    payload.update(sanitized_fields(fields))
    LOGGER.log(
        level,
        event,
        extra={
            "ranking": {
                key: value for key, value in payload.items() if value is not None
            }
        },
    )


def _identity_fields(
    identity: ArticleEvaluationIdentity,
    *,
    attempt_count: int | None = None,
    relevance_count: int | None = None,
    ordinal: int | None = None,
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "article_analysis_id": str(identity.article_analysis_id),
        "profile_revision": identity.profile_revision,
        "parameter_set_hash": identity.parameter_set_hash,
        "schema_version": identity.schema_version,
        "evaluator_name": identity.evaluator_name,
        "evaluator_version": identity.evaluator_version,
        "prompt_version": identity.prompt_version,
    }
    if attempt_count is not None:
        fields["attempt_count"] = attempt_count
    if relevance_count is not None:
        fields["relevance_count"] = relevance_count
    if ordinal is not None:
        fields["ordinal"] = ordinal
    return fields


def log_evaluation_claim(
    identity: ArticleEvaluationIdentity,
    *,
    evaluation_run_id: UUID,
    attempt_count: int,
    status: str,
) -> None:
    log_ranking_event(
        "evaluation_claim",
        stage="evaluation",
        status=status,
        user_id=identity.user_id,
        article_id=identity.article_id,
        evaluation_run_id=evaluation_run_id,
        fields=_identity_fields(identity, attempt_count=attempt_count),
    )


def log_evaluation_replay(
    identity: ArticleEvaluationIdentity,
    *,
    evaluation_run_id: UUID,
    attempt_count: int,
) -> None:
    log_ranking_event(
        "evaluation_replay",
        stage="evaluation",
        status="returned",
        user_id=identity.user_id,
        article_id=identity.article_id,
        evaluation_run_id=evaluation_run_id,
        fields=_identity_fields(identity, attempt_count=attempt_count),
    )


def log_evaluation_reprocess(
    identity: ArticleEvaluationIdentity,
    *,
    evaluation_run_id: UUID,
    attempt_count: int,
) -> None:
    log_ranking_event(
        "evaluation_reprocess",
        stage="evaluation",
        status="claimed",
        user_id=identity.user_id,
        article_id=identity.article_id,
        evaluation_run_id=evaluation_run_id,
        fields=_identity_fields(identity, attempt_count=attempt_count),
    )


def log_evaluation_attempt(
    identity: ArticleEvaluationIdentity,
    *,
    evaluation_run_id: UUID,
    ordinal: int,
    status: str,
    error_code: str | None = None,
) -> None:
    log_ranking_event(
        "evaluation_attempt",
        stage="evaluation",
        status=status,
        user_id=identity.user_id,
        article_id=identity.article_id,
        evaluation_run_id=evaluation_run_id,
        error_code=error_code,
        fields=_identity_fields(identity, ordinal=ordinal),
    )


def log_evaluation_validation(
    identity: ArticleEvaluationIdentity,
    *,
    evaluation_run_id: UUID,
    ordinal: int,
    status: str,
    relevance_count: int | None = None,
    error_code: str | None = None,
) -> None:
    log_ranking_event(
        "evaluation_validation",
        stage="evaluation",
        status=status,
        user_id=identity.user_id,
        article_id=identity.article_id,
        evaluation_run_id=evaluation_run_id,
        error_code=error_code,
        fields=_identity_fields(
            identity,
            ordinal=ordinal,
            relevance_count=relevance_count,
        ),
    )


def log_evaluation_acceptance(
    identity: ArticleEvaluationIdentity,
    *,
    evaluation_run_id: UUID,
    attempt_count: int,
    relevance_count: int,
) -> None:
    log_ranking_event(
        "evaluation_acceptance",
        stage="evaluation",
        status="accepted",
        user_id=identity.user_id,
        article_id=identity.article_id,
        evaluation_run_id=evaluation_run_id,
        fields=_identity_fields(
            identity,
            attempt_count=attempt_count,
            relevance_count=relevance_count,
        ),
    )


def log_evaluation_stale(
    identity: ArticleEvaluationIdentity,
    *,
    evaluation_run_id: UUID,
    error_code: str,
) -> None:
    log_ranking_event(
        "evaluation_stale",
        stage="evaluation",
        status="stale",
        user_id=identity.user_id,
        article_id=identity.article_id,
        evaluation_run_id=evaluation_run_id,
        error_code=error_code,
        fields=_identity_fields(identity),
    )


def log_evaluation_failure(
    identity: ArticleEvaluationIdentity,
    *,
    evaluation_run_id: UUID,
    error_code: str,
    status: str,
) -> None:
    log_ranking_event(
        "evaluation_failure",
        stage="evaluation",
        status=status,
        user_id=identity.user_id,
        article_id=identity.article_id,
        evaluation_run_id=evaluation_run_id,
        error_code=error_code,
        fields=_identity_fields(identity),
        level=logging.WARNING,
    )


_DIVERSITY_SAMPLE_LIMIT = 10


def _bounded_identifiers(values: Sequence[UUID | str]) -> tuple[str, ...]:
    return tuple(str(value) for value in values[:_DIVERSITY_SAMPLE_LIMIT])


def _cap_vector_fields(cap_vector: tuple[int, int, int] | None) -> dict[str, int]:
    if cap_vector is None:
        return {}
    event_cap, topic_cap, source_cap = cap_vector
    return {
        "event_cap": event_cap,
        "topic_cap": topic_cap,
        "source_cap": source_cap,
    }


def log_diversity_protection(
    *,
    user_id: UUID,
    request_id: str,
    protected_count: int,
    article_ids: Sequence[UUID],
) -> None:
    log_ranking_event(
        "diversity_protection",
        stage="ranking",
        status="classified",
        user_id=user_id,
        request_id=request_id,
        fields={
            "protected_count": protected_count,
            "protected_article_ids": _bounded_identifiers(article_ids),
        },
    )


def log_diversity_veto(
    *,
    user_id: UUID,
    request_id: str,
    vetoed_count: int,
    article_ids: Sequence[UUID],
) -> None:
    log_ranking_event(
        "diversity_veto",
        stage="ranking",
        status="classified",
        user_id=user_id,
        request_id=request_id,
        fields={
            "vetoed_count": vetoed_count,
            "vetoed_article_ids": _bounded_identifiers(article_ids),
        },
    )


def log_diversity_cap_rejection(
    *,
    user_id: UUID,
    request_id: str,
    pass_number: int,
    cap_vector: tuple[int, int, int],
    reason: str,
    rejected_count: int,
    article_ids: Sequence[UUID],
) -> None:
    fields = {
        "pass_number": pass_number,
        "rejected_count": rejected_count,
        "rejected_reason": reason[:100],
        "rejected_article_ids": _bounded_identifiers(article_ids),
    }
    fields.update(_cap_vector_fields(cap_vector))
    log_ranking_event(
        "diversity_cap_rejection",
        stage="ranking",
        status="rejected",
        user_id=user_id,
        request_id=request_id,
        fields=fields,
    )


def log_diversity_relaxation(
    *,
    user_id: UUID,
    request_id: str,
    from_pass: int,
    from_vector: tuple[int, int, int],
    to_pass: int,
    to_vector: tuple[int, int, int],
    selected_count: int,
    requested_count: int,
) -> None:
    fields = {
        "from_pass": from_pass,
        "to_pass": to_pass,
        "selected_count": selected_count,
        "requested_count": requested_count,
        "from_event_cap": from_vector[0],
        "from_topic_cap": from_vector[1],
        "from_source_cap": from_vector[2],
        "to_event_cap": to_vector[0],
        "to_topic_cap": to_vector[1],
        "to_source_cap": to_vector[2],
    }
    log_ranking_event(
        "diversity_relaxation",
        stage="ranking",
        status="relaxed",
        user_id=user_id,
        request_id=request_id,
        fields=fields,
    )


def log_diversity_shortage(
    *,
    user_id: UUID,
    request_id: str,
    pass_number: int,
    cap_vector: tuple[int, int, int],
    selected_count: int,
    requested_count: int,
    unsatisfied_limits: Sequence[str],
) -> None:
    fields = {
        "pass_number": pass_number,
        "selected_count": selected_count,
        "requested_count": requested_count,
        "shortage_count": max(requested_count - selected_count, 0),
        "unsatisfied_limits": tuple(limit[:40] for limit in unsatisfied_limits[:3]),
    }
    fields.update(_cap_vector_fields(cap_vector))
    log_ranking_event(
        "diversity_shortage",
        stage="ranking",
        status="shortage",
        user_id=user_id,
        request_id=request_id,
        fields=fields,
    )


def log_diversity_selection(
    *,
    user_id: UUID,
    request_id: str,
    pass_number: int,
    cap_vector: tuple[int, int, int],
    selected_count: int,
    requested_count: int,
    article_ids: Sequence[UUID],
    unsatisfied_limits: Sequence[str],
) -> None:
    fields = {
        "pass_number": pass_number,
        "selected_count": selected_count,
        "requested_count": requested_count,
        "selected_article_ids": _bounded_identifiers(article_ids),
        "unsatisfied_limits": tuple(limit[:40] for limit in unsatisfied_limits[:3]),
    }
    fields.update(_cap_vector_fields(cap_vector))
    log_ranking_event(
        "diversity_selection",
        stage="ranking",
        status="selected",
        user_id=user_id,
        request_id=request_id,
        fields=fields,
    )


def log_diversity_completion(
    *,
    user_id: UUID,
    request_id: str,
    ranking_run_id: UUID,
    status: str,
    selected_count: int,
    excluded_count: int,
    cap_vector: tuple[int, int, int] | None,
    unsatisfied_limits: Sequence[str],
) -> None:
    fields = {
        "selected_count": selected_count,
        "excluded_count": excluded_count,
        "unsatisfied_limits": tuple(limit[:40] for limit in unsatisfied_limits[:3]),
    }
    fields.update(_cap_vector_fields(cap_vector))
    log_ranking_event(
        "diversity_completion",
        stage="ranking",
        status=status,
        user_id=user_id,
        ranking_run_id=ranking_run_id,
        request_id=request_id,
        fields=fields,
    )
