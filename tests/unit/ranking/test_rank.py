from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest

from anxious_news_bot.ranking.domain import (
    ArticleEvaluation,
    ArticleEvaluationIdentity,
    ArticleParameterRelevance,
    EligibilityReason,
    EvaluationStatus,
    RankingConfiguration,
    RankingIdentity,
    RankingResult,
    RankingStatus,
)
from anxious_news_bot.ranking.errors import RankingRunError, StaleSnapshotError
from anxious_news_bot.ranking.services.rank import (
    PersonalRankingService,
    candidate_snapshot_hash,
)
from anxious_news_bot.ranking.services.score import DeterministicRankingScorer
from tests.fixtures.ranking import (
    FixedClock,
    StaticRankingConfigurationProvider,
    article_snapshot,
    ranking_configuration,
    ranking_preference,
)


def _uuid(value: int) -> UUID:
    return UUID(f"00000000-0000-0000-0000-{value:012d}")


def _evaluation(
    article, preferences, *, relevance: str = "0.7500"
) -> ArticleEvaluation:
    return ArticleEvaluation(
        run_id=uuid4(),
        identity=ArticleEvaluationIdentity(
            user_id=preferences[0].user_id if preferences else _uuid(999),
            article_id=article.article_id,
            article_analysis_id=article.article_analysis_id,
            profile_revision=3,
            parameter_set_hash="a" * 64,
            schema_version="1.0",
            evaluator_name="test-evaluator",
            evaluator_version="1.0",
            prompt_version="1.0",
        ),
        status=EvaluationStatus.COMPLETE,
        relevances=tuple(
            ArticleParameterRelevance(
                parameter_id=preference.id,
                relevance=Decimal(relevance),
                reason_code="clear_match",
            )
            for preference in preferences
        ),
    )


class Repository:
    def __init__(self, snapshot) -> None:
        self.snapshot = snapshot
        self.loaded: list[tuple[UUID, tuple[UUID, ...]]] = []
        self.persisted: RankingResult | None = None
        self.results_by_request: dict[tuple[UUID, str], RankingResult] = {}
        self.request_inputs: dict[tuple[UUID, str], RankingIdentity] = {}
        self.results_by_snapshot: dict[tuple[object, ...], RankingResult] = {}
        self.marked: tuple[RankingIdentity, str, str | None] | None = None
        self.persist_calls = 0
        self.stale_on_persist = False

    async def load_ranking_snapshot(self, user_id: UUID, candidate_article_ids):
        self.loaded.append((user_id, tuple(candidate_article_ids)))
        return self.snapshot

    async def find_complete_run(
        self,
        identity: RankingIdentity,
        configuration: RankingConfiguration,
    ) -> RankingResult | None:
        del configuration
        request_key = (identity.user_id, identity.request_id)
        existing_identity = self.request_inputs.get(request_key)
        if existing_identity is not None and existing_identity != identity:
            raise RankingRunError(
                "same request id cannot be reused with different input"
            )
        existing = self.results_by_request.get(request_key)
        if existing is not None:
            return existing
        self.request_inputs[request_key] = identity
        return self.results_by_snapshot.get(self._snapshot_key(identity))

    async def persist_complete_run(
        self,
        result: RankingResult,
        configuration: RankingConfiguration,
    ) -> RankingResult:
        del configuration
        if self.stale_on_persist:
            raise StaleSnapshotError("ranking snapshot changed before persistence")
        existing = self.results_by_request.get(
            (result.identity.user_id, result.identity.request_id)
        )
        if existing is not None:
            return existing
        self.persist_calls += 1
        self.results_by_request[
            (result.identity.user_id, result.identity.request_id)
        ] = result
        self.results_by_snapshot[self._snapshot_key(result.identity)] = result
        self.persisted = result
        return result

    async def mark_stale_or_failed(
        self,
        identity: RankingIdentity,
        configuration: RankingConfiguration,
        status: str,
        *,
        error_code: str | None = None,
    ) -> RankingResult | None:
        del configuration
        self.marked = (identity, status, error_code)
        stale = RankingResult(
            ranking_run_id=uuid4(),
            identity=identity,
            status=RankingStatus(status),
            records=(),
            selected_count=0,
            excluded_count=0,
            completed_at=FixedClock.value,
            error_code=error_code,
        )
        self.results_by_request[(identity.user_id, identity.request_id)] = stale
        self.results_by_snapshot[self._snapshot_key(identity)] = stale
        return stale

    @staticmethod
    def _snapshot_key(identity: RankingIdentity) -> tuple[object, ...]:
        return (
            identity.user_id,
            identity.profile_revision,
            identity.candidate_set_hash,
            identity.configuration_version,
            identity.ranking_at,
            identity.requested_count,
        )


def _service(snapshot, configuration=None) -> PersonalRankingService:
    return PersonalRankingService(
        Repository(snapshot),
        StaticRankingConfigurationProvider(configuration or ranking_configuration()),
        DeterministicRankingScorer(),
        FixedClock(),
    )


def test_candidate_snapshot_hash_is_canonical_and_version_sensitive() -> None:
    preferences = (ranking_preference(parameter_id=_uuid(1), user_id=_uuid(10)),)
    first = article_snapshot(
        article_id=_uuid(100),
        article_analysis_id=_uuid(200),
        source_id=_uuid(300),
        published_at=FixedClock.value,
    )
    second = article_snapshot(
        article_id=_uuid(101),
        article_analysis_id=_uuid(201),
        source_id=_uuid(301),
        published_at=FixedClock.value - timedelta(hours=1),
    )
    evaluations = (_evaluation(first, preferences), _evaluation(second, preferences))

    original = candidate_snapshot_hash((first, second), evaluations)
    reordered = candidate_snapshot_hash((second, first), tuple(reversed(evaluations)))
    changed = candidate_snapshot_hash(
        (
            first,
            replace(second, article_analysis_id=_uuid(999)),
        ),
        evaluations,
    )

    assert original == reordered
    assert changed != original


def test_candidate_snapshot_hash_distinguishes_missing_analysis() -> None:
    article = article_snapshot(
        article_id=_uuid(102),
        article_analysis_id=_uuid(202),
        source_id=_uuid(302),
        published_at=FixedClock.value,
    )

    with_analysis = candidate_snapshot_hash((article,), ())
    without_analysis = candidate_snapshot_hash(
        (replace(article, article_analysis_id=None),),
        (),
    )

    assert without_analysis != with_analysis
    assert without_analysis == candidate_snapshot_hash(
        (replace(article, article_analysis_id=None),),
        (),
    )


@pytest.mark.asyncio
async def test_rank_rejects_candidate_bounds_before_loading_snapshot() -> None:
    service = _service((3, (), (), ()))

    with pytest.raises(RankingRunError, match="maximum candidate count"):
        await service.rank(
            _uuid(10),
            "request-1",
            tuple(_uuid(value) for value in range(1, 502)),
            requested_count=10,
            ranking_at=FixedClock.value,
        )


@pytest.mark.asyncio
async def test_rank_builds_identity_from_immutable_snapshot_and_replays_complete_runs() -> (
    None
):
    user_id = _uuid(20)
    preferences = ()
    first = article_snapshot(
        article_id=_uuid(110),
        article_analysis_id=_uuid(210),
        source_id=_uuid(310),
        published_at=FixedClock.value,
        importance_score=Decimal("0.8000"),
        novelty_score=Decimal("0.5000"),
    )
    second = article_snapshot(
        article_id=_uuid(111),
        article_analysis_id=_uuid(211),
        source_id=_uuid(311),
        published_at=FixedClock.value,
        importance_score=Decimal("0.8000"),
        novelty_score=Decimal("0.5000"),
    )
    repository = Repository((7, preferences, (second, first), ()))
    service = PersonalRankingService(
        repository,
        StaticRankingConfigurationProvider(),
        DeterministicRankingScorer(),
        FixedClock(),
    )

    first_result = await service.rank(
        user_id,
        "request-2",
        (second.article_id, first.article_id),
        requested_count=2,
        ranking_at=FixedClock.value,
    )
    replay = await service.rank(
        user_id,
        "request-2",
        (first.article_id, second.article_id),
        requested_count=2,
        ranking_at=FixedClock.value,
    )

    assert first_result.identity.profile_revision == 7
    assert first_result.identity.ranking_at == FixedClock.value
    assert [record.article_id for record in first_result.records] == [
        first.article_id,
        second.article_id,
    ]
    assert replay.ranking_run_id == first_result.ranking_run_id
    assert repository.persist_calls == 1


@pytest.mark.asyncio
async def test_rank_retains_missing_analysis_candidate_as_ineligible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event_log = Mock()
    monkeypatch.setattr(
        "anxious_news_bot.ranking.services.rank.log_ranking_event",
        event_log,
    )
    user_id = _uuid(23)
    complete = article_snapshot(
        article_id=_uuid(140),
        article_analysis_id=_uuid(240),
        source_id=_uuid(340),
        published_at=FixedClock.value,
    )
    missing = replace(
        article_snapshot(
            article_id=_uuid(141),
            article_analysis_id=_uuid(241),
            source_id=_uuid(341),
            published_at=FixedClock.value,
        ),
        article_analysis_id=None,
        importance_score=None,
        novelty_score=None,
        source_quality_score=None,
    )
    repository = Repository((3, (), (complete, missing), ()))
    service = PersonalRankingService(
        repository,
        StaticRankingConfigurationProvider(),
        DeterministicRankingScorer(),
        FixedClock(),
    )

    result = await service.rank(
        user_id,
        "request-missing-analysis",
        (complete.article_id, missing.article_id),
        requested_count=2,
        ranking_at=FixedClock.value,
    )

    missing_record = next(
        record for record in result.records if record.article_id == missing.article_id
    )
    assert result.status is RankingStatus.COMPLETE
    assert len(result.records) == 2
    assert missing_record.article_analysis_id is None
    assert missing_record.eligible is False
    assert (
        missing_record.eligibility_reason is EligibilityReason.MISSING_GENERIC_ANALYSIS
    )
    assert repository.persisted == result
    summary = next(
        call
        for call in event_log.call_args_list
        if call.args == ("ranking_eligibility_summary",)
    )
    assert summary.kwargs["fields"]["candidate_count"] == 2
    assert summary.kwargs["fields"]["eligible_count"] == 1
    assert summary.kwargs["fields"]["eligibility_reason_counts"] == {
        "eligible": 1,
        "missing_generic_analysis": 1,
    }


@pytest.mark.asyncio
async def test_rank_rejects_same_request_id_for_different_inputs() -> None:
    user_id = _uuid(21)
    article = article_snapshot(article_id=_uuid(120), article_analysis_id=_uuid(220))
    repository = Repository((3, (), (article,), ()))
    service = PersonalRankingService(
        repository,
        StaticRankingConfigurationProvider(),
        DeterministicRankingScorer(),
        FixedClock(),
    )

    await service.rank(
        user_id,
        "request-3",
        (article.article_id,),
        requested_count=1,
        ranking_at=FixedClock.value,
    )

    with pytest.raises(RankingRunError, match="same request id"):
        await service.rank(
            user_id,
            "request-3",
            (article.article_id,),
            requested_count=2,
            ranking_at=FixedClock.value,
        )


@pytest.mark.asyncio
async def test_rank_returns_stale_outcome_when_snapshot_changes_before_persist() -> (
    None
):
    user_id = _uuid(22)
    preference = ranking_preference(
        parameter_id=_uuid(2), user_id=user_id, weight="0.80"
    )
    article = article_snapshot(article_id=_uuid(130), article_analysis_id=_uuid(230))
    repository = Repository(
        (3, (preference,), (article,), (_evaluation(article, (preference,)),))
    )
    repository.stale_on_persist = True
    service = PersonalRankingService(
        repository,
        StaticRankingConfigurationProvider(),
        DeterministicRankingScorer(),
        FixedClock(),
    )

    result = await service.rank(
        user_id,
        "request-4",
        (article.article_id,),
        requested_count=1,
        ranking_at=FixedClock.value,
    )

    assert result.status is RankingStatus.STALE
    assert repository.marked is not None
