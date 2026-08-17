from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import httpx
from telegram import Bot
from telegram.request import HTTPXRequest

from anxious_news_bot.config import Settings
from anxious_news_bot.digest.domain import RetrySchedule, validate_local_time
from anxious_news_bot.digest.infrastructure.llm import StructuredDigestComposer
from anxious_news_bot.digest.infrastructure.persistence import (
    SQLAlchemyDigestRepository,
)
from anxious_news_bot.digest.services.execute import DigestExecutionService
from anxious_news_bot.digest.services.history import DigestHistoryFilter
from anxious_news_bot.digest.services.material_updates import MaterialUpdatePolicy
from anxious_news_bot.digest.services.retention import DigestRetentionService
from anxious_news_bot.infrastructure.structured_model import StructuredModelTransport
from anxious_news_bot.infrastructure.users import (
    ApplicationUserProvisioner,
    DigestDefaults,
)
from anxious_news_bot.logging import configure_logging
from anxious_news_bot.news.infrastructure.database import Database
from anxious_news_bot.preferences.infrastructure.repository import (
    SystemClock as Clock,
)
from anxious_news_bot.ranking.infrastructure.llm import (
    ARTICLE_EVALUATION_PROMPT_VERSION,
    STRUCTURED_EVALUATOR_NAME,
    STRUCTURED_EVALUATOR_VERSION,
    StructuredArticlePreferenceEvaluator,
)
from anxious_news_bot.ranking.infrastructure.persistence import (
    SQLAlchemyRankingRepository,
)
from anxious_news_bot.ranking.infrastructure.persistence import (
    SystemClock as RankingClock,
)
from anxious_news_bot.ranking.services.configuration import (
    ValidatedRankingConfigurationProvider,
)
from anxious_news_bot.ranking.services.evaluate import ArticleEvaluationService
from anxious_news_bot.ranking.services.news import PersonalNewsService
from anxious_news_bot.ranking.services.rank import PersonalRankingService
from anxious_news_bot.ranking.services.score import DeterministicRankingScorer
from anxious_news_bot.telegram.digest import TelegramDigestDelivery

LOGGER = logging.getLogger(__name__)

_INITIAL_DELAY_SECONDS = 15
_RETENTION_INTERVAL_SECONDS = 86_400


def _runtime_limit(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8").strip()[:100]
    except OSError:
        return None


def _build_execution_service(
    settings: Settings,
    client: httpx.AsyncClient,
    database: Database,
    delivery: TelegramDigestDelivery,
) -> DigestExecutionService:
    user_provisioner = ApplicationUserProvisioner(
        DigestDefaults(
            count=settings.digest_default_count,
            local_time=validate_local_time(settings.digest_default_local_time),
            timezone_name=settings.digest_default_timezone,
        )
    )
    digest_repository = SQLAlchemyDigestRepository(
        database,
        user_provisioner=user_provisioner,
    )
    ranking_repository = SQLAlchemyRankingRepository(database)
    ranking_evaluator = StructuredArticlePreferenceEvaluator(
        client,
        base_url=settings.ranking_model_base_url,
        api_key=settings.ranking_model_api_key,
        model=settings.ranking_model_name,
        timeout_seconds=settings.ranking_model_timeout_seconds,
        retry_attempts=settings.ranking_model_retry_attempts,
        max_response_bytes=settings.ranking_model_max_response_bytes,
    )
    article_evaluation_service = ArticleEvaluationService(
        ranking_repository,
        ranking_evaluator,
        Clock(),
        evaluator_name=STRUCTURED_EVALUATOR_NAME,
        evaluator_version=STRUCTURED_EVALUATOR_VERSION,
        prompt_version=ARTICLE_EVALUATION_PROMPT_VERSION,
        retry_attempts=settings.ranking_evaluation_retry_attempts,
    )
    ranking_configuration_provider = (
        ValidatedRankingConfigurationProvider.from_settings(settings)
    )
    personal_ranking_service = PersonalRankingService(
        ranking_repository,
        ranking_configuration_provider,
        DeterministicRankingScorer(),
        RankingClock(),
    )
    personal_news_service = PersonalNewsService(
        ranking_repository,
        article_evaluation_service,
        personal_ranking_service,
        ranking_configuration_provider,
        RankingClock(),
        candidate_limit=settings.news_command_candidate_limit,
        evaluation_concurrency=settings.news_command_evaluation_concurrency,
    )
    digest_model_transport = StructuredModelTransport(
        client,
        base_url=settings.ranking_model_base_url,
        api_key=settings.ranking_model_api_key,
        model=settings.ranking_model_name,
        timeout_seconds=settings.ranking_model_timeout_seconds,
        retry_attempts=settings.ranking_model_retry_attempts,
        max_response_bytes=settings.ranking_model_max_response_bytes,
    )
    return DigestExecutionService(
        config_repository=digest_repository,
        execution_repository=digest_repository,
        personal_news_selector=personal_news_service,
        composer=StructuredDigestComposer(digest_model_transport),
        delivery=delivery,
        candidate_filter=DigestHistoryFilter(
            digest_repository,
            policy=MaterialUpdatePolicy(
                version=settings.digest_material_update_policy_version,
                novelty_threshold=settings.digest_material_update_novelty_threshold,
                max_content_similarity=(
                    settings.digest_material_update_max_content_similarity
                ),
                min_text_chars=settings.digest_material_update_min_text_chars,
            ),
        ),
        clock=Clock(),
        retry_schedule=RetrySchedule(
            base_seconds=settings.digest_retry_base_seconds,
            max_seconds=settings.digest_retry_max_seconds,
            max_attempts=settings.digest_max_attempts,
        ),
        user_concurrency=settings.digest_user_concurrency,
        candidate_limit=settings.digest_candidate_limit,
        renderer_version=settings.digest_renderer_version,
        claim_batch_size=settings.digest_claim_batch_size,
        max_claims_per_tick=settings.digest_max_claims_per_tick,
        claim_time_budget_seconds=settings.digest_claim_time_budget_seconds,
        content_max_input_chars=settings.digest_content_max_input_chars,
    )


def _build_retention_service(
    settings: Settings, database: Database
) -> DigestRetentionService:
    user_provisioner = ApplicationUserProvisioner(
        DigestDefaults(
            count=settings.digest_default_count,
            local_time=validate_local_time(settings.digest_default_local_time),
            timezone_name=settings.digest_default_timezone,
        )
    )
    return DigestRetentionService(
        SQLAlchemyDigestRepository(database, user_provisioner=user_provisioner),
        Clock(),
        history_retention_days=settings.digest_history_retention_days,
    )


async def _run_due_cycle(
    execution_service: DigestExecutionService, clock: Clock
) -> None:
    now = clock.now()
    try:
        due_result = await execution_service.run_due_cycle(now)
        if due_result.claimed_count > 0:
            LOGGER.info(
                "digest_due_cycle_complete",
                extra={
                    "digest": {
                        "claimed": due_result.claimed_count,
                        "completed": due_result.completed_count,
                        "failed": due_result.failed_count,
                    }
                },
            )
    except asyncio.CancelledError:
        raise
    except Exception:
        LOGGER.exception("digest_due_cycle_error")

    try:
        retry_result = await execution_service.retry_due(now)
        if retry_result.retried_count > 0:
            LOGGER.info(
                "digest_retry_cycle_complete",
                extra={
                    "digest": {
                        "retried": retry_result.retried_count,
                        "completed": retry_result.completed_count,
                        "failed": retry_result.failed_count,
                    }
                },
            )
    except asyncio.CancelledError:
        raise
    except Exception:
        LOGGER.exception("digest_retry_cycle_error")


async def run(settings: Settings) -> None:
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.ranking_model_timeout_seconds)
    )
    bot = Bot(
        token=settings.telegram_bot_token,
        request=HTTPXRequest(connection_pool_size=4),
    )
    delivery = TelegramDigestDelivery(bot)
    database = Database(settings.database_url)
    execution_service = _build_execution_service(settings, client, database, delivery)
    retention_service = _build_retention_service(settings, database)
    clock = Clock()

    LOGGER.info(
        "digest_executor_starting",
        extra={
            "digest": {
                "scan_interval_seconds": settings.digest_scan_interval_seconds,
                "user_concurrency": settings.digest_user_concurrency,
                "candidate_limit": settings.digest_candidate_limit,
                "logical_cpu_count": os.cpu_count(),
                "cgroup_cpu_limit": _runtime_limit("/sys/fs/cgroup/cpu.max"),
                "cgroup_memory_limit": _runtime_limit("/sys/fs/cgroup/memory.max"),
            }
        },
    )

    last_retention_run: float = 0.0

    try:
        await asyncio.sleep(_INITIAL_DELAY_SECONDS)
        while True:
            await _run_due_cycle(execution_service, clock)
            loop_time = asyncio.get_event_loop().time()
            if loop_time - last_retention_run >= _RETENTION_INTERVAL_SECONDS:
                try:
                    await retention_service.run_cleanup()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    LOGGER.exception("digest_retention_cycle_error")
                last_retention_run = asyncio.get_event_loop().time()
            await asyncio.sleep(settings.digest_scan_interval_seconds)
    except asyncio.CancelledError:
        LOGGER.info("digest_executor_stopping")
    finally:
        await client.aclose()
        await database.close()


def main() -> None:
    configure_logging()
    settings = Settings.from_env()
    asyncio.run(run(settings))
