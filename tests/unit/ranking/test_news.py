from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from anxious_news_bot.ranking.domain import (
    GROUNDED_SUMMARY_MAX_CHARS,
    DeliveryArticle,
    EvaluationStatus,
    PersonalNewsSelection,
    RankingIdentity,
    RankingResult,
    RankingStatus,
    SelectionOutcome,
    SelectionReason,
)
from anxious_news_bot.ranking.errors import RankingRunError
from anxious_news_bot.ranking.services.news import PersonalNewsService
from tests.fixtures.ranking import (
    FixedClock,
    StaticRankingConfigurationProvider,
    ranking_record,
)

_RANKING_AT = FixedClock.value


def _async_result(value):
    return AsyncMock(return_value=value)


def _delivery_articles(article_ids, **overrides) -> tuple[DeliveryArticle, ...]:
    return tuple(
        DeliveryArticle(
            article_id=article_id,
            title=f"Article {index}",
            summary=None,
            canonical_url=f"https://example.com/{index}",
            source_name="Example",
            published_at=datetime(2026, 1, 1, tzinfo=UTC),
            **overrides,
        )
        for index, article_id in enumerate(article_ids, start=1)
    )


def _ranking_identity(
    *,
    user_id: UUID,
    request_id: str = "request-1",
    requested_count: int = 10,
    profile_revision: int = 3,
) -> RankingIdentity:
    return RankingIdentity(
        request_id=request_id,
        user_id=user_id,
        profile_revision=profile_revision,
        candidate_set_hash="a" * 64,
        configuration_version="1.0",
        ranking_at=_RANKING_AT,
        requested_count=requested_count,
    )


def _ranking_result(
    *,
    user_id: UUID,
    records,
    request_id: str = "request-1",
    requested_count: int = 10,
    profile_revision: int = 3,
    ranking_run_id: UUID | None = None,
) -> RankingResult:
    records = tuple(records)
    selected_count = sum(1 for record in records if record.selection.selected)
    return RankingResult(
        ranking_run_id=ranking_run_id or uuid4(),
        identity=_ranking_identity(
            user_id=user_id,
            request_id=request_id,
            requested_count=requested_count,
            profile_revision=profile_revision,
        ),
        status=RankingStatus.COMPLETE,
        records=records,
        selected_count=selected_count,
        excluded_count=len(records) - selected_count,
        completed_at=_RANKING_AT,
    )


class _RecordingRepository:
    """Fake RankingRepository that records call order for ordering assertions."""

    def __init__(
        self,
        *,
        candidate_ids: tuple[UUID, ...],
        articles: tuple[DeliveryArticle, ...] = (),
        profile_revision: int = 5,
        has_preferences: bool = True,
        calls: list[tuple] | None = None,
    ) -> None:
        self.calls: list[tuple] = calls if calls is not None else []
        self._candidate_ids = tuple(candidate_ids)
        self._articles_by_id = {article.article_id: article for article in articles}
        self._profile_revision = profile_revision
        self._has_preferences = has_preferences
        self.resolve_user_id = AsyncMock(side_effect=self._resolve_user_id)
        self.last_prepare_limit: int | None = None

    async def _resolve_user_id(self, telegram_user_id: int) -> UUID | None:
        self.calls.append(("resolve_user_id", telegram_user_id))
        return telegram_user_id

    async def resolve_profile_revision(self, user_id: UUID) -> int:
        self.calls.append(("resolve_profile_revision", user_id))
        return self._profile_revision

    async def prepare_delivery_candidates(
        self, *, limit: int, ranking_at: datetime, freshness_horizon_seconds: int
    ) -> tuple[UUID, ...]:
        self.last_prepare_limit = limit
        self.calls.append(("prepare_delivery_candidates", limit))
        return self._candidate_ids

    async def has_active_nonzero_preferences(self, user_id: UUID) -> bool:
        self.calls.append(("has_active_nonzero_preferences", user_id))
        return self._has_preferences

    async def load_delivery_articles(self, article_ids) -> tuple[DeliveryArticle, ...]:
        ids = tuple(article_ids)
        self.calls.append(("load_delivery_articles", ids))
        return tuple(
            self._articles_by_id[article_id]
            for article_id in ids
            if article_id in self._articles_by_id
        )


class _RecordingEvaluator:
    def __init__(self, calls: list[tuple] | None = None) -> None:
        self.calls: list[tuple] = calls if calls is not None else []
        self.evaluated_article_ids: list[UUID] = []

    async def evaluate(self, user_id: UUID, article_id: UUID):
        self.evaluated_article_ids.append(article_id)
        self.calls.append(("evaluate", article_id))
        return SimpleNamespace(status=EvaluationStatus.COMPLETE)


class _RecordingRanker:
    def __init__(self, result: RankingResult, calls: list[tuple] | None = None) -> None:
        self.result = result
        self.calls: list[tuple] = calls if calls is not None else []

    async def rank(
        self,
        user_id: UUID,
        request_id: str,
        candidate_ids,
        *,
        requested_count: int,
        ranking_at: datetime,
    ) -> RankingResult:
        self.calls.append(("rank", tuple(candidate_ids)))
        return self.result


class _StaticCandidateFilter:
    def __init__(self, eligible_ids, calls: list[tuple] | None = None) -> None:
        self._eligible_ids = tuple(eligible_ids)
        self.calls: list[tuple] = calls if calls is not None else []
        self.received_args: tuple | None = None

    async def filter(self, user_id: UUID, candidate_ids, ranking_at: datetime):
        candidate_ids = tuple(candidate_ids)
        self.received_args = (user_id, candidate_ids, ranking_at)
        self.calls.append(("filter", candidate_ids))
        return SimpleNamespace(eligible_article_ids=self._eligible_ids)


def _selected_records(article_ids):
    return tuple(
        ranking_record(
            article_id=article_id,
            final_score=f"0.{9 - index}0000000",
            selection=SelectionOutcome(
                selected=True,
                reason=SelectionReason.SELECTED,
                position=index,
                diversity_pass=1,
            ),
        )
        for index, article_id in enumerate(article_ids, start=1)
    )


async def test_evaluates_candidates_ranks_and_returns_selected_articles() -> None:
    user_id = uuid4()
    article_ids = (uuid4(), uuid4())
    repository = _RecordingRepository(
        candidate_ids=article_ids,
        articles=_delivery_articles(article_ids),
    )
    evaluator = _RecordingEvaluator()
    records = _selected_records(article_ids)
    ranker = _RecordingRanker(_ranking_result(user_id=user_id, records=records))

    result = await PersonalNewsService(
        repository,
        evaluator,
        ranker,
        StaticRankingConfigurationProvider(),
        FixedClock(),
        candidate_limit=10,
    ).top(123, "request-1", count=10)

    assert [item.article.article_id for item in result] == list(article_ids)
    assert [item.position for item in result] == [1, 2]
    assert all(isinstance(item.score, Decimal) for item in result)
    assert len(evaluator.evaluated_article_ids) == 2
    assert len(ranker.calls) == 1


# ---------------------------------------------------------------------------
# Unchanged `top()` / `/news` behavior
# ---------------------------------------------------------------------------


async def test_top_delegates_to_select_for_user_without_filter_using_default_limit() -> (
    None
):
    user_id = uuid4()
    article_ids = (uuid4(), uuid4())
    repository = _RecordingRepository(
        candidate_ids=article_ids,
        articles=_delivery_articles(article_ids),
    )
    evaluator = _RecordingEvaluator()
    ranker = _RecordingRanker(
        _ranking_result(user_id=user_id, records=_selected_records(article_ids))
    )

    service = PersonalNewsService(
        repository,
        evaluator,
        ranker,
        StaticRankingConfigurationProvider(),
        FixedClock(),
        candidate_limit=15,
    )

    result = await service.top(123, "telegram-request", count=10)

    assert [item.article.article_id for item in result] == list(article_ids)
    # top() resolves the telegram user id and then uses the service's default
    # candidate limit, exactly as before this change.
    repository.resolve_user_id.assert_awaited_once_with(123)
    assert repository.last_prepare_limit == 15
    # No candidate filter is ever applied on the `/news` path.
    assert ("filter", article_ids) not in repository.calls


async def test_top_raises_when_user_profile_is_missing() -> None:
    repository = _RecordingRepository(candidate_ids=())
    repository.resolve_user_id = AsyncMock(return_value=None)
    evaluator = _RecordingEvaluator()
    ranker = _RecordingRanker(_ranking_result(user_id=uuid4(), records=()))

    service = PersonalNewsService(
        repository,
        evaluator,
        ranker,
        StaticRankingConfigurationProvider(),
        FixedClock(),
        candidate_limit=10,
    )

    with pytest.raises(RankingRunError):
        await service.top(999, "request-1")


# ---------------------------------------------------------------------------
# Internal user selection path
# ---------------------------------------------------------------------------


async def test_select_for_user_uses_internal_user_id_without_resolving_telegram_id() -> (
    None
):
    user_id = uuid4()
    article_ids = (uuid4(), uuid4())
    repository = _RecordingRepository(
        candidate_ids=article_ids,
        articles=_delivery_articles(article_ids),
    )
    evaluator = _RecordingEvaluator()
    ranker = _RecordingRanker(
        _ranking_result(user_id=user_id, records=_selected_records(article_ids))
    )

    service = PersonalNewsService(
        repository,
        evaluator,
        ranker,
        StaticRankingConfigurationProvider(),
        FixedClock(),
        candidate_limit=10,
    )

    selection = await service.select_for_user(user_id, "digest-request", 2, 20)

    assert isinstance(selection, PersonalNewsSelection)
    assert [item.article.article_id for item in selection.items] == list(article_ids)
    repository.resolve_user_id.assert_not_awaited()


# ---------------------------------------------------------------------------
# Candidate-limit bound validation
# ---------------------------------------------------------------------------


async def test_select_for_user_rejects_non_positive_candidate_limit() -> None:
    repository = _RecordingRepository(candidate_ids=())
    service = PersonalNewsService(
        repository,
        _RecordingEvaluator(),
        _RecordingRanker(_ranking_result(user_id=uuid4(), records=())),
        StaticRankingConfigurationProvider(),
        FixedClock(),
        candidate_limit=10,
    )

    with pytest.raises(ValueError, match="positive"):
        await service.select_for_user(uuid4(), "request-1", 5, 0)

    assert repository.calls == []


async def test_select_for_user_rejects_candidate_limit_below_count() -> None:
    repository = _RecordingRepository(candidate_ids=())
    service = PersonalNewsService(
        repository,
        _RecordingEvaluator(),
        _RecordingRanker(_ranking_result(user_id=uuid4(), records=())),
        StaticRankingConfigurationProvider(),
        FixedClock(),
        candidate_limit=10,
    )

    with pytest.raises(ValueError, match="at least count"):
        await service.select_for_user(uuid4(), "request-1", 10, 5)

    assert repository.calls == []


async def test_select_for_user_rejects_candidate_limit_above_ranking_maximum() -> None:
    repository = _RecordingRepository(candidate_ids=())
    configuration_provider = StaticRankingConfigurationProvider()
    assert configuration_provider.current().maximum_candidate_count == 500
    service = PersonalNewsService(
        repository,
        _RecordingEvaluator(),
        _RecordingRanker(_ranking_result(user_id=uuid4(), records=())),
        configuration_provider,
        FixedClock(),
        candidate_limit=10,
    )

    with pytest.raises(ValueError, match="ranking maximum"):
        await service.select_for_user(uuid4(), "request-1", 5, 501)

    assert repository.calls == []


async def test_select_for_user_accepts_candidate_limit_equal_to_count() -> None:
    user_id = uuid4()
    article_ids = (uuid4(),)
    repository = _RecordingRepository(
        candidate_ids=article_ids,
        articles=_delivery_articles(article_ids),
    )
    ranker = _RecordingRanker(
        _ranking_result(user_id=user_id, records=_selected_records(article_ids))
    )

    service = PersonalNewsService(
        repository,
        _RecordingEvaluator(),
        ranker,
        StaticRankingConfigurationProvider(),
        FixedClock(),
        candidate_limit=10,
    )

    # candidate_limit == count is the boundary and must be accepted.
    selection = await service.select_for_user(user_id, "request-1", 1, 1)

    assert len(selection.items) == 1
    assert repository.last_prepare_limit == 1


# ---------------------------------------------------------------------------
# Candidate filter ordering
# ---------------------------------------------------------------------------


async def test_select_for_user_applies_candidate_filter_after_preparation_before_evaluation() -> (
    None
):
    user_id = uuid4()
    prepared_ids = (uuid4(), uuid4(), uuid4())
    eligible_ids = (prepared_ids[0], prepared_ids[2])
    shared_calls: list[tuple] = []

    repository = _RecordingRepository(
        candidate_ids=prepared_ids,
        articles=_delivery_articles(eligible_ids),
        calls=shared_calls,
    )
    candidate_filter = _StaticCandidateFilter(eligible_ids, calls=shared_calls)
    evaluator = _RecordingEvaluator(calls=shared_calls)
    ranker = _RecordingRanker(
        _ranking_result(user_id=user_id, records=_selected_records(eligible_ids)),
        calls=shared_calls,
    )

    service = PersonalNewsService(
        repository,
        evaluator,
        ranker,
        StaticRankingConfigurationProvider(),
        FixedClock(),
        candidate_limit=10,
    )

    await service.select_for_user(
        user_id, "request-1", 2, 10, candidate_filter=candidate_filter
    )

    call_names = [call[0] for call in shared_calls]
    assert call_names.index("prepare_delivery_candidates") < call_names.index("filter")
    assert call_names.index("filter") < call_names.index(
        "has_active_nonzero_preferences"
    )
    assert call_names.index("filter") < call_names.index("rank")
    # The filter must only be evaluated with the freshly prepared candidates,
    # preserving their input order.
    assert candidate_filter.received_args[1] == prepared_ids
    # Only filtered-in (eligible) candidates reach personal evaluation.
    assert sorted(evaluator.evaluated_article_ids) == sorted(eligible_ids)
    assert prepared_ids[1] not in evaluator.evaluated_article_ids
    # Ranking only ever sees the eligible candidate set, in filter order.
    rank_call = next(call for call in shared_calls if call[0] == "rank")
    assert rank_call[1] == eligible_ids


async def test_select_for_user_without_candidate_filter_uses_all_prepared_candidates() -> (
    None
):
    user_id = uuid4()
    prepared_ids = (uuid4(), uuid4())
    repository = _RecordingRepository(
        candidate_ids=prepared_ids,
        articles=_delivery_articles(prepared_ids),
    )
    ranker = _RecordingRanker(
        _ranking_result(user_id=user_id, records=_selected_records(prepared_ids))
    )

    service = PersonalNewsService(
        repository,
        _RecordingEvaluator(),
        ranker,
        StaticRankingConfigurationProvider(),
        FixedClock(),
        candidate_limit=10,
    )

    await service.select_for_user(user_id, "request-1", 2, 10)

    assert ranker.calls[0] == ("rank", prepared_ids)


async def test_select_for_user_zero_candidates_after_filter_skips_evaluation_and_ranking() -> (
    None
):
    user_id = uuid4()
    prepared_ids = (uuid4(), uuid4())
    repository = _RecordingRepository(
        candidate_ids=prepared_ids,
        profile_revision=7,
    )
    candidate_filter = _StaticCandidateFilter(())
    evaluator = _RecordingEvaluator()
    ranker = _RecordingRanker(_ranking_result(user_id=user_id, records=()))

    service = PersonalNewsService(
        repository,
        evaluator,
        ranker,
        StaticRankingConfigurationProvider(),
        FixedClock(),
        candidate_limit=10,
    )

    selection = await service.select_for_user(
        user_id, "request-1", 2, 10, candidate_filter=candidate_filter
    )

    assert selection == PersonalNewsSelection(
        ranking_run_id=None,
        profile_revision=7,
        ranking_at=_RANKING_AT,
        items=(),
    )
    assert candidate_filter.received_args[1] == prepared_ids
    assert evaluator.evaluated_article_ids == []
    assert ranker.calls == []
    assert ("has_active_nonzero_preferences", user_id) not in repository.calls


# ---------------------------------------------------------------------------
# Selection metadata and grounding
# ---------------------------------------------------------------------------


async def test_select_for_user_returns_ranking_run_id_profile_revision_and_ranking_at() -> (
    None
):
    user_id = uuid4()
    article_ids = (uuid4(), uuid4())
    repository = _RecordingRepository(
        candidate_ids=article_ids,
        articles=_delivery_articles(article_ids),
    )
    ranking_run_id = uuid4()
    ranker = _RecordingRanker(
        _ranking_result(
            user_id=user_id,
            records=_selected_records(article_ids),
            ranking_run_id=ranking_run_id,
            profile_revision=11,
        )
    )

    service = PersonalNewsService(
        repository,
        _RecordingEvaluator(),
        ranker,
        StaticRankingConfigurationProvider(),
        FixedClock(),
        candidate_limit=10,
    )

    selection = await service.select_for_user(user_id, "request-1", 2, 10)

    assert selection.ranking_run_id == ranking_run_id
    assert selection.profile_revision == 11
    assert selection.ranking_at == _RANKING_AT
    assert [item.position for item in selection.items] == [1, 2]


async def test_select_for_user_zero_candidates_returns_none_ranking_run_id_and_profile_revision() -> (
    None
):
    user_id = uuid4()
    repository = _RecordingRepository(candidate_ids=(), profile_revision=42)
    evaluator = _RecordingEvaluator()
    ranker = _RecordingRanker(_ranking_result(user_id=user_id, records=()))

    service = PersonalNewsService(
        repository,
        evaluator,
        ranker,
        StaticRankingConfigurationProvider(),
        FixedClock(),
        candidate_limit=10,
    )

    selection = await service.select_for_user(user_id, "request-1", 2, 10)

    assert selection == PersonalNewsSelection(
        ranking_run_id=None,
        profile_revision=42,
        ranking_at=_RANKING_AT,
        items=(),
    )
    assert evaluator.evaluated_article_ids == []
    assert ranker.calls == []
    assert ("resolve_profile_revision", user_id) in repository.calls


async def test_select_for_user_enriches_articles_with_analysis_and_event_group() -> (
    None
):
    user_id = uuid4()
    article_id = uuid4()
    analysis_id = uuid4()
    event_group_id = uuid4()
    article = DeliveryArticle(
        article_id=article_id,
        title="Story",
        summary=None,
        canonical_url="https://example.com/story",
        source_name="Example",
        published_at=datetime(2026, 1, 1, tzinfo=UTC),
        article_analysis_id=analysis_id,
        event_group_id=event_group_id,
        normalized_text="Full normalized article body used for grounding.",
    )
    repository = _RecordingRepository(candidate_ids=(article_id,), articles=(article,))
    ranker = _RecordingRanker(
        _ranking_result(user_id=user_id, records=_selected_records((article_id,)))
    )

    service = PersonalNewsService(
        repository,
        _RecordingEvaluator(),
        ranker,
        StaticRankingConfigurationProvider(),
        FixedClock(),
        candidate_limit=10,
    )

    selection = await service.select_for_user(user_id, "request-1", 1, 10)

    delivered = selection.items[0].article
    assert delivered.article_analysis_id == analysis_id
    assert delivered.event_group_id == event_group_id
    assert (
        delivered.normalized_text == "Full normalized article body used for grounding."
    )
    # No explicit summary was supplied, so grounding falls back to normalized text.
    assert (
        delivered.grounded_summary == "Full normalized article body used for grounding."
    )


def test_delivery_article_grounded_summary_prefers_existing_summary() -> None:
    article = DeliveryArticle(
        article_id=uuid4(),
        title="Story",
        summary="A concise human summary.",
        canonical_url="https://example.com/story",
        source_name="Example",
        published_at=datetime(2026, 1, 1, tzinfo=UTC),
        normalized_text="A very long normalized article body that should not be used.",
    )

    assert article.grounded_summary == "A concise human summary."


def test_delivery_article_grounded_summary_falls_back_to_bounded_normalized_text() -> (
    None
):
    long_text = "x" * (GROUNDED_SUMMARY_MAX_CHARS + 500)
    article = DeliveryArticle(
        article_id=uuid4(),
        title="Story",
        summary=None,
        canonical_url="https://example.com/story",
        source_name="Example",
        published_at=datetime(2026, 1, 1, tzinfo=UTC),
        normalized_text=long_text,
    )

    assert article.grounded_summary == long_text[:GROUNDED_SUMMARY_MAX_CHARS]
    assert len(article.grounded_summary) == GROUNDED_SUMMARY_MAX_CHARS


def test_delivery_article_grounded_summary_defaults_empty_without_source_text() -> None:
    article = DeliveryArticle(
        article_id=uuid4(),
        title="Story",
        summary=None,
        canonical_url="https://example.com/story",
        source_name="Example",
        published_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert article.grounded_summary == ""


def test_delivery_article_grounded_summary_explicit_value_is_preserved() -> None:
    article = DeliveryArticle(
        article_id=uuid4(),
        title="Story",
        summary=None,
        canonical_url="https://example.com/story",
        source_name="Example",
        published_at=datetime(2026, 1, 1, tzinfo=UTC),
        normalized_text="Should not be used because grounded_summary is explicit.",
        grounded_summary="Explicit grounding text.",
    )

    assert article.grounded_summary == "Explicit grounding text."
