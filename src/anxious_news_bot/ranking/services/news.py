from __future__ import annotations

import asyncio
from uuid import UUID

from anxious_news_bot.ranking.domain import (
    EvaluationStatus,
    PersonalNewsSelection,
    RankedNewsItem,
    RankingConfiguration,
    RankingResult,
)
from anxious_news_bot.ranking.errors import EvaluationError, RankingRunError
from anxious_news_bot.ranking.ports import (
    CandidateFilter,
    Clock,
    RankingConfigurationProvider,
    RankingRepository,
)
from anxious_news_bot.ranking.services.evaluate import ArticleEvaluationService
from anxious_news_bot.ranking.services.rank import PersonalRankingService


class PersonalNewsService:
    def __init__(
        self,
        repository: RankingRepository,
        evaluator: ArticleEvaluationService,
        ranker: PersonalRankingService,
        configuration_provider: RankingConfigurationProvider,
        clock: Clock,
        *,
        candidate_limit: int = 30,
        evaluation_concurrency: int = 5,
    ) -> None:
        if candidate_limit < 10:
            raise ValueError("candidate_limit must be at least 10")
        if evaluation_concurrency < 1:
            raise ValueError("evaluation_concurrency must be positive")
        self._repository = repository
        self._evaluator = evaluator
        self._ranker = ranker
        self._configuration_provider = configuration_provider
        self._clock = clock
        self._candidate_limit = candidate_limit
        self._evaluation_concurrency = evaluation_concurrency

    async def top(
        self,
        telegram_user_id: int,
        request_id: str,
        *,
        count: int = 10,
    ) -> tuple[RankedNewsItem, ...]:
        user_id = await self._repository.resolve_user_id(telegram_user_id)
        if user_id is None:
            raise RankingRunError("user profile is missing", code="missing_user")

        selection = await self.select_for_user(
            user_id,
            request_id,
            count,
            self._candidate_limit,
        )
        return selection.items

    async def select_for_user(
        self,
        user_id: UUID,
        request_id: str,
        count: int,
        candidate_limit: int,
        candidate_filter: CandidateFilter | None = None,
    ) -> PersonalNewsSelection:
        configuration = self._configuration_provider.current()
        self._validate_candidate_limit(candidate_limit, count, configuration)

        ranking_at = self._clock.now()
        candidate_ids = await self._repository.prepare_delivery_candidates(
            limit=candidate_limit,
            ranking_at=ranking_at,
            freshness_horizon_seconds=configuration.freshness_horizon_seconds,
        )

        if candidate_filter is not None:
            filtered = await candidate_filter.filter(user_id, candidate_ids, ranking_at)
            candidate_ids = tuple(filtered.eligible_article_ids)

        if not candidate_ids:
            profile_revision = await self._repository.resolve_profile_revision(user_id)
            return PersonalNewsSelection(
                ranking_run_id=None,
                profile_revision=profile_revision,
                ranking_at=ranking_at,
                items=(),
            )

        if await self._repository.has_active_nonzero_preferences(user_id):
            await self._evaluate_candidates(user_id, candidate_ids)

        result = await self._ranker.rank(
            user_id,
            request_id,
            candidate_ids,
            requested_count=count,
            ranking_at=ranking_at,
        )
        items = await self._load_ranked_items(result)
        return PersonalNewsSelection(
            ranking_run_id=result.ranking_run_id,
            profile_revision=result.identity.profile_revision,
            ranking_at=ranking_at,
            items=items,
        )

    @staticmethod
    def _validate_candidate_limit(
        candidate_limit: int,
        count: int,
        configuration: RankingConfiguration,
    ) -> None:
        if candidate_limit <= 0:
            raise ValueError("candidate_limit must be positive")
        if candidate_limit < count:
            raise ValueError("candidate_limit must be at least count")
        if candidate_limit > configuration.maximum_candidate_count:
            raise ValueError("candidate_limit must not exceed the ranking maximum")

    async def _load_ranked_items(
        self, result: RankingResult
    ) -> tuple[RankedNewsItem, ...]:
        selected = tuple(
            sorted(
                (record for record in result.records if record.selection.selected),
                key=lambda record: record.selection.position or 0,
            )
        )
        articles = await self._repository.load_delivery_articles(
            tuple(record.article_id for record in selected)
        )
        articles_by_id = {article.article_id: article for article in articles}
        return tuple(
            RankedNewsItem(
                article=articles_by_id[record.article_id],
                position=record.selection.position or index,
                score=record.final_score,
            )
            for index, record in enumerate(selected, start=1)
            if record.article_id in articles_by_id
        )

    async def _evaluate_candidates(self, user_id, candidate_ids) -> None:
        semaphore = asyncio.Semaphore(self._evaluation_concurrency)

        async def evaluate(article_id) -> None:
            async with semaphore:
                try:
                    result = await self._evaluator.evaluate(user_id, article_id)
                    if result.status is not EvaluationStatus.COMPLETE:
                        return
                except EvaluationError:
                    return

        await asyncio.gather(*(evaluate(article_id) for article_id in candidate_ids))
