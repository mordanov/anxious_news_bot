"""Deterministic delivery-history candidate filtering tests."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from anxious_news_bot.digest.domain import (
    CandidateArticleEvidence,
    CandidateDecision,
    DeliveredArticleEvidence,
    MaterialUpdateInput,
    MaterialUpdateOutcome,
)
from anxious_news_bot.digest.services.history import DigestHistoryFilter
from anxious_news_bot.digest.services.material_updates import MaterialUpdatePolicy


class FakeHistoryRepo:
    def __init__(
        self,
        delivered_ids: set | None = None,
        inputs: tuple[MaterialUpdateInput, ...] = (),
    ):
        self._delivered = delivered_ids or set()
        self._inputs = inputs
        self.evidence = {}
        self.insert_count = 0

    async def get_user_history_article_ids(self, user_id, candidate_ids=None):
        del user_id, candidate_ids
        return self._delivered

    async def load_material_update_inputs(self, user_id, candidate_ids):
        del user_id
        allowed = set(candidate_ids)
        return tuple(
            value for value in self._inputs if value.candidate.article_id in allowed
        )

    async def load_material_update_evidence(
        self, delivery_history_id, candidate_article_id, policy_version
    ):
        return self.evidence.get(
            (delivery_history_id, candidate_article_id, policy_version)
        )

    async def save_material_update_evidence(self, evidence):
        key = (
            evidence.delivery_history_id,
            evidence.candidate_article_id,
            evidence.policy_version,
        )
        self.insert_count += 1
        self.evidence.setdefault(key, evidence)
        return self.evidence[key]


def _material_input(*, novelty: str = "0.8000") -> MaterialUpdateInput:
    event_group_id = uuid4()
    prior_time = datetime(2026, 1, 1, tzinfo=UTC)
    return MaterialUpdateInput(
        delivered=DeliveredArticleEvidence(
            history_id=uuid4(),
            article_id=uuid4(),
            article_analysis_id=uuid4(),
            event_group_id=event_group_id,
            publication_time=prior_time,
            normalized_text="prior text " * 40,
        ),
        candidate=CandidateArticleEvidence(
            article_id=uuid4(),
            article_analysis_id=uuid4(),
            event_group_id=event_group_id,
            publication_time=prior_time + timedelta(hours=1),
            normalized_text="new development " * 40,
            novelty_score=Decimal(novelty),
        ),
        has_duplicate_or_review_veto=False,
    )


@pytest.mark.asyncio
async def test_excludes_same_article_and_preserves_candidate_order():
    delivered_id = uuid4()
    remaining = [uuid4(), uuid4()]
    repo = FakeHistoryRepo({delivered_id})
    result = await DigestHistoryFilter(repo).filter(
        uuid4(),
        [remaining[0], delivered_id, remaining[1]],
        datetime.now(UTC),
    )

    assert list(result.eligible_article_ids) == remaining
    assert [decision.outcome for decision in result.decisions] == [
        CandidateDecision.ELIGIBLE,
        CandidateDecision.SAME_ARTICLE,
        CandidateDecision.ELIGIBLE,
    ]


@pytest.mark.asyncio
async def test_all_delivered_candidates_are_excluded():
    ids = [uuid4() for _ in range(3)]
    result = await DigestHistoryFilter(FakeHistoryRepo(set(ids))).filter(
        uuid4(), ids, datetime.now(UTC)
    )
    assert result.eligible_article_ids == ()


@pytest.mark.asyncio
async def test_material_update_remains_eligible_and_persists_evidence():
    update_input = _material_input()
    repo = FakeHistoryRepo(inputs=(update_input,))

    result = await DigestHistoryFilter(repo).filter(
        uuid4(),
        [update_input.candidate.article_id],
        datetime.now(UTC),
    )

    assert result.eligible_article_ids == (update_input.candidate.article_id,)
    assert result.decisions[0].outcome is CandidateDecision.ELIGIBLE
    assert next(iter(repo.evidence.values())).outcome is (
        MaterialUpdateOutcome.MATERIAL_UPDATE
    )


@pytest.mark.asyncio
async def test_unchanged_story_is_excluded():
    update_input = _material_input(novelty="0.1000")
    update_input = MaterialUpdateInput(
        delivered=update_input.delivered,
        candidate=CandidateArticleEvidence(
            article_id=update_input.candidate.article_id,
            article_analysis_id=update_input.candidate.article_analysis_id,
            event_group_id=update_input.candidate.event_group_id,
            publication_time=update_input.candidate.publication_time,
            normalized_text=update_input.delivered.normalized_text,
            novelty_score=Decimal("0.1000"),
        ),
        has_duplicate_or_review_veto=False,
    )
    repo = FakeHistoryRepo(inputs=(update_input,))

    result = await DigestHistoryFilter(repo).filter(
        uuid4(),
        [update_input.candidate.article_id],
        datetime.now(UTC),
    )

    assert result.eligible_article_ids == ()
    assert result.decisions[0].outcome is CandidateDecision.UNCHANGED_STORY


@pytest.mark.asyncio
async def test_cached_pair_policy_decision_is_reused():
    update_input = _material_input()
    repo = FakeHistoryRepo(inputs=(update_input,))
    history_filter = DigestHistoryFilter(
        repo,
        policy=MaterialUpdatePolicy(
            version="test-v1",
            novelty_threshold=Decimal("0.7000"),
            max_content_similarity=Decimal("0.60000"),
            min_text_chars=200,
        ),
    )

    await history_filter.filter(
        uuid4(), [update_input.candidate.article_id], datetime.now(UTC)
    )
    await history_filter.filter(
        uuid4(), [update_input.candidate.article_id], datetime.now(UTC)
    )

    assert repo.insert_count == 1
