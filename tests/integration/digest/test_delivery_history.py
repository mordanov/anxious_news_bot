from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from anxious_news_bot.digest.domain import CandidateDecision
from anxious_news_bot.digest.services.history import DigestHistoryFilter
from tests.integration.digest.test_delivery_idempotency import _ready_digest

NOW = datetime(2026, 1, 15, 9, 1, tzinfo=UTC)


async def _confirmed_history(
    digest_repository,
    provision_digest_user,
    enable_digest_user,
    seed_digest_graph,
    event_group_id,
):
    user, occurrence, _, digest, _ = await _ready_digest(
        digest_repository,
        provision_digest_user,
        enable_digest_user,
        seed_digest_graph,
        count=1,
        event_group_id=event_group_id,
    )
    claim = await digest_repository.claim_delivery_part(occurrence.execution_id, 1, NOW)
    await digest_repository.acknowledge_delivery_part(
        claim,
        "provider-history",
        NOW,
    )
    return user, digest.items[0]


async def test_delivery_history_is_scoped_per_user(
    digest_repository,
    provision_digest_user,
    enable_digest_user,
    seed_digest_graph,
) -> None:
    event_group_id = uuid4()
    user, prior = await _confirmed_history(
        digest_repository,
        provision_digest_user,
        enable_digest_user,
        seed_digest_graph,
        event_group_id,
    )
    other = await provision_digest_user(telegram_user_id=51_999)

    first = await DigestHistoryFilter(digest_repository).filter(
        user.application_user.id,
        [prior.article_id],
        NOW,
    )
    second = await DigestHistoryFilter(digest_repository).filter(
        other.application_user.id,
        [prior.article_id],
        NOW,
    )

    assert first.eligible_article_ids == ()
    assert first.decisions[0].outcome is CandidateDecision.SAME_ARTICLE
    assert second.eligible_article_ids == (prior.article_id,)


async def test_later_high_novelty_same_event_candidate_is_eligible(
    digest_repository,
    provision_digest_user,
    enable_digest_user,
    seed_digest_graph,
) -> None:
    event_group_id = uuid4()
    user, prior = await _confirmed_history(
        digest_repository,
        provision_digest_user,
        enable_digest_user,
        seed_digest_graph,
        event_group_id,
    )
    candidate_graph = await seed_digest_graph(
        user.application_user.id,
        count=1,
        event_group_id=event_group_id,
        novelty_scores=(Decimal("0.9000"),),
        normalized_texts=("material new facts " * 30,),
        published_at=prior.published_at + timedelta(hours=2),
    )
    candidate = candidate_graph.articles[0]

    result = await DigestHistoryFilter(digest_repository).filter(
        user.application_user.id,
        [candidate.article_id],
        NOW,
    )

    assert result.eligible_article_ids == (candidate.article_id,)
    assert result.decisions[0].outcome is CandidateDecision.ELIGIBLE


async def test_baseline_content_delta_is_eligible_without_veto(
    digest_repository,
    provision_digest_user,
    enable_digest_user,
    seed_digest_graph,
) -> None:
    event_group_id = uuid4()
    user, prior = await _confirmed_history(
        digest_repository,
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
            normalized_texts=("entirely different verified development " * 30,),
            published_at=prior.published_at + timedelta(hours=3),
        )
    ).articles[0]

    result = await DigestHistoryFilter(digest_repository).filter(
        user.application_user.id,
        [candidate.article_id],
        NOW,
    )

    assert result.eligible_article_ids == (candidate.article_id,)


async def test_unchanged_same_event_candidate_is_excluded(
    digest_repository,
    provision_digest_user,
    enable_digest_user,
    seed_digest_graph,
) -> None:
    event_group_id = uuid4()
    user, prior = await _confirmed_history(
        digest_repository,
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
            normalized_texts=("normalized article 0 " * 30,),
            published_at=prior.published_at + timedelta(hours=3),
        )
    ).articles[0]

    result = await DigestHistoryFilter(digest_repository).filter(
        user.application_user.id,
        [candidate.article_id],
        NOW,
    )

    assert result.eligible_article_ids == ()
    assert result.decisions[0].outcome is CandidateDecision.UNCHANGED_STORY
