from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func, select, text

from anxious_news_bot.digest.infrastructure.models import (
    DigestMaterialUpdateEvidence,
)
from anxious_news_bot.digest.services.material_updates import (
    MaterialUpdateEvidenceProducer,
    MaterialUpdatePolicy,
)
from anxious_news_bot.news.domain import DecisionOutcome, DecisionType
from tests.integration.digest.test_delivery_history import _confirmed_history

NOW = datetime(2026, 1, 15, 9, 1, tzinfo=UTC)
POLICY = MaterialUpdatePolicy(
    version="integration-v1",
    novelty_threshold=Decimal("0.7000"),
    max_content_similarity=Decimal("0.60000"),
    min_text_chars=200,
)


async def _input(
    repository,
    provision_digest_user,
    enable_digest_user,
    seed_digest_graph,
):
    event_group_id = uuid4()
    user, prior = await _confirmed_history(
        repository,
        provision_digest_user,
        enable_digest_user,
        seed_digest_graph,
        event_group_id,
    )
    candidate = (
        await seed_digest_graph(
            user.application_user.id,
            count=1,
            event_group_id=event_group_id,
            novelty_scores=(Decimal("0.1000"),),
            normalized_texts=("a genuinely different event development " * 30,),
            published_at=prior.published_at + timedelta(hours=2),
        )
    ).articles[0]
    values = await repository.load_material_update_inputs(
        user.application_user.id,
        [candidate.article_id],
    )
    assert len(values) == 1
    return values[0]


def _evaluate(value):
    return MaterialUpdateEvidenceProducer().evaluate(
        delivery_history_id=value.delivered.history_id,
        prior_article_id=value.delivered.article_id,
        candidate_article_id=value.candidate.article_id,
        candidate_analysis_id=value.candidate.article_analysis_id,
        prior_event_group_id=value.delivered.event_group_id,
        candidate_event_group_id=value.candidate.event_group_id,
        prior_published_at=value.delivered.publication_time,
        candidate_published_at=value.candidate.publication_time,
        policy=POLICY,
        prior_normalized_text=value.delivered.normalized_text,
        candidate_normalized_text=value.candidate.normalized_text,
        candidate_novelty_score=value.candidate.novelty_score,
        has_duplicate_or_review_veto=value.has_duplicate_or_review_veto,
    )


async def test_evidence_insert_or_load_is_atomic_under_concurrency(
    digest_database,
    digest_repository,
    provision_digest_user,
    enable_digest_user,
    seed_digest_graph,
) -> None:
    value = await _input(
        digest_repository,
        provision_digest_user,
        enable_digest_user,
        seed_digest_graph,
    )
    proposed = _evaluate(value)

    results = await asyncio.gather(
        *(digest_repository.save_material_update_evidence(proposed) for _ in range(8))
    )

    assert len({result.prior_text_hash for result in results}) == 1
    async with digest_database.session() as session:
        count = await session.scalar(
            select(func.count()).select_from(DigestMaterialUpdateEvidence)
        )
    assert count == 1


async def test_duplicate_review_veto_is_loaded_for_content_delta(
    digest_database,
    digest_repository,
    provision_digest_user,
    enable_digest_user,
    seed_digest_graph,
) -> None:
    value = await _input(
        digest_repository,
        provision_digest_user,
        enable_digest_user,
        seed_digest_graph,
    )
    left, right = sorted((value.delivered.article_id, value.candidate.article_id))
    async with digest_database.session() as session:
        await session.execute(
            text(
                "INSERT INTO deduplication_decisions "
                "(id, left_article_id, right_article_id, decision_type, outcome, "
                "threshold_configuration, normalization_version, evidence, decided_at) "
                "VALUES (:id, :left, :right, :decision_type, :outcome, "
                "'{}'::jsonb, '1.0', '{}'::jsonb, :now)"
            ),
            {
                "id": uuid4(),
                "left": left,
                "right": right,
                "decision_type": DecisionType.NEAR_DUPLICATE.value,
                "outcome": DecisionOutcome.REVIEW.value,
                "now": NOW,
            },
        )

    async with digest_database.session() as session:
        user_id = await session.scalar(
            text("SELECT user_id FROM digest_delivery_history WHERE id = :history_id"),
            {"history_id": value.delivered.history_id},
        )
    refreshed = await digest_repository.load_material_update_inputs(
        user_id,
        [value.candidate.article_id],
    )
    assert refreshed[0].has_duplicate_or_review_veto is True
