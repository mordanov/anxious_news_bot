from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest
from telegram.ext import JobQueue

from anxious_news_bot.news.infrastructure.feeds import FeedFetcher
from anxious_news_bot.news.services.aggregate import DefaultNewsAggregator
from anxious_news_bot.preferences.domain import (
    PreferenceAction,
    PreferenceOrigin,
    PreferenceParameter,
    ProfileSnapshot,
    SpecifyState,
    SpecifyStateKind,
)
from anxious_news_bot.preferences.services.apply_changes import (
    DeterministicPreferenceChangeValidator,
)
from anxious_news_bot.preferences.services.specify import ExplicitPreferenceService
from anxious_news_bot.ranking.services.evaluate import ArticleEvaluationService
from anxious_news_bot.ranking.services.rank import PersonalRankingService
from anxious_news_bot.ranking.services.score import DeterministicRankingScorer
from tests.fixtures.preferences import FixedClock
from tests.fixtures.ranking import (
    DeterministicArticlePreferenceEvaluator,
    DeterministicExplicitInterpreter,
    StaticRankingConfigurationProvider,
    StubRankingRepository,
    article_evaluation,
    article_snapshot,
    evaluation_identity,
    ranking_preference,
)


@dataclass(frozen=True, slots=True)
class ClaimResult:
    request_id: UUID
    replay_state: SpecifyState | None = None


class SpecifyRepository:
    def __init__(self, profile: ProfileSnapshot) -> None:
        self.profile = profile
        self.request_id = uuid4()

    async def claim_explicit_request(
        self,
        telegram_user_id: int,
        telegram_update_id: int,
        statement: str,
        language_code: str | None,
        claimed_at: datetime,
    ) -> ClaimResult:
        del telegram_user_id, telegram_update_id, statement, language_code, claimed_at
        return ClaimResult(self.request_id)

    async def load_explicit_context(self, request_id: UUID):
        assert request_id == self.request_id
        return self.profile, ()

    async def duplicate_candidates(self, user_id, semantic_key, name, *, limit=20):
        del user_id, semantic_key, name, limit
        return self.profile

    async def apply_explicit_changes(self, request_id, proposal, applied_at):
        del proposal, applied_at
        return SpecifyState(
            SpecifyStateKind.APPLIED,
            request_id=request_id,
            action=PreferenceAction.ADJUST,
            parameter_name="Kirov city news",
            message="Saved your explicit preference for Kirov city news.",
        )

    async def complete_no_change(self, request_id, proposal_hash, completed_at):
        del proposal_hash, completed_at
        return SpecifyState(
            SpecifyStateKind.NO_CHANGE,
            request_id=request_id,
            message="Already covered.",
        )

    async def fail_explicit_request(self, request_id, error_code, failed_at):
        del error_code, failed_at
        return SpecifyState(
            SpecifyStateKind.FAILED,
            request_id=request_id,
            message="failed",
        )


def _profile() -> ProfileSnapshot:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    parameter = PreferenceParameter(
        id=uuid4(),
        user_id=uuid4(),
        semantic_key="kirov_city_news",
        name="Kirov city news",
        description="Specific city reporting about Kirov.",
        evaluation_instructions="Prefer relevant Kirov city reporting.",
        weight=Decimal("0.40"),
        origin=PreferenceOrigin.QUESTIONNAIRE,
        active=True,
        created_at=now,
        updated_at=now,
    )
    return ProfileSnapshot(parameter.user_id, 3, (parameter,))


class RankRepository:
    def __init__(self) -> None:
        self.preference = ranking_preference()
        self.article = article_snapshot()
        self.evaluation = article_evaluation(
            identity=evaluation_identity(
                user_id=self.preference.user_id,
                article_id=self.article.article_id,
                article_analysis_id=self.article.article_analysis_id,
            ),
            parameter_id=self.preference.id,
        )

    async def load_ranking_snapshot(self, user_id, candidate_article_ids):
        del user_id, candidate_article_ids
        return (
            3,
            (self.preference,),
            (self.article,),
            (self.evaluation,),
        )

    async def find_complete_run(self, identity, configuration):
        del identity, configuration
        return None

    async def persist_complete_run(self, result, configuration):
        del configuration
        return result

    async def mark_stale_or_failed(
        self,
        identity,
        configuration,
        status,
        *,
        error_code=None,
    ):
        del identity, configuration, status, error_code
        return None


@pytest.mark.parametrize("path", ["specify", "evaluate", "rank"])
async def test_personalization_paths_never_fetch_news_aggregate_or_schedule_jobs(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
) -> None:
    fetch = AsyncMock(side_effect=AssertionError("unexpected source fetch"))
    aggregate = AsyncMock(side_effect=AssertionError("unexpected aggregation"))
    schedule = Mock(side_effect=AssertionError("unexpected scheduling"))
    deliver = AsyncMock(side_effect=AssertionError("unexpected delivery"))

    monkeypatch.setattr(FeedFetcher, "fetch", fetch)
    monkeypatch.setattr(DefaultNewsAggregator, "run_cycle", aggregate)
    monkeypatch.setattr(JobQueue, "run_repeating", schedule, raising=False)

    if path == "specify":
        profile = _profile()
        repository = SpecifyRepository(profile)
        service = ExplicitPreferenceService(
            repository,
            DeterministicExplicitInterpreter(
                {
                    "schema_version": "1.0",
                    "request_id": repository.request_id,
                    "base_profile_revision": profile.revision,
                    "changes": [
                        {
                            "action": "adjust",
                            "parameter_id": profile.parameters[0].id,
                            "target_weight": "0.80",
                            "reason": "User explicitly asked for more Kirov city news.",
                        }
                    ],
                }
            ),
            DeterministicPreferenceChangeValidator(),
            FixedClock(),
        )
        service.deliver_digest = deliver
        state = await service.specify(123, 77, "More Kirov city news", "en")
        assert state.kind is SpecifyStateKind.APPLIED
    elif path == "evaluate":
        repository = StubRankingRepository()
        service = ArticleEvaluationService(
            repository,
            DeterministicArticlePreferenceEvaluator(
                {
                    "schema_version": "1.0",
                    "article_id": repository.snapshot[2][0].article_id,
                    "article_analysis_id": repository.snapshot[2][
                        0
                    ].article_analysis_id,
                    "profile_revision": 3,
                    "parameter_set_hash": repository.snapshot[3][
                        0
                    ].identity.parameter_set_hash,
                    "relevances": [
                        {
                            "parameter_id": repository.snapshot[3][0]
                            .relevances[0]
                            .parameter_id,
                            "relevance": "0.7500",
                            "reason_code": "clear_match",
                        }
                    ],
                }
            ),
            FixedClock(),
            evaluator_name="test-evaluator",
            evaluator_version="1.0",
            prompt_version="1.0",
        )
        service.deliver_digest = deliver
        evaluation = await service.evaluate(
            repository.snapshot[1][0].user_id,
            repository.snapshot[2][0].article_id,
        )
        assert evaluation.status is not None
    else:
        repository = RankRepository()
        service = PersonalRankingService(
            repository,
            StaticRankingConfigurationProvider(),
            DeterministicRankingScorer(),
            FixedClock(),
        )
        service.deliver_digest = deliver
        result = await service.rank(
            repository.preference.user_id,
            "boundary-check",
            [repository.article.article_id],
            requested_count=1,
            ranking_at=FixedClock.value,
        )
        assert result.status is not None

    fetch.assert_not_awaited()
    aggregate.assert_not_awaited()
    assert schedule.call_count == 0
    deliver.assert_not_awaited()
