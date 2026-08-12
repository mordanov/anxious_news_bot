import logging

import httpx
from decimal import Decimal
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from anxious_news_bot.config import Settings
from anxious_news_bot.logging import configure_logging
from anxious_news_bot.news.infrastructure.database import Database
from anxious_news_bot.news.infrastructure.feeds import FeedFetcher
from anxious_news_bot.news.infrastructure.persistence import SQLAlchemyNewsRepository
from anxious_news_bot.news.infrastructure.scheduling import AggregationScheduler
from anxious_news_bot.news.domain import SourceType
from anxious_news_bot.news.services.aggregate import DefaultNewsAggregator, SystemClock
from anxious_news_bot.news.services.canonicalize import CanonicalURLPolicy
from anxious_news_bot.news.services.normalize import DeterministicArticleNormalizer
from anxious_news_bot.news.services.deduplicate import (
    DeterministicArticleDeduplicator,
)
from anxious_news_bot.news.services.event_grouping import DeterministicEventGrouper
from anxious_news_bot.news.services.source_catalog import (
    SourceAdapterRegistry,
    SourceAdapterRouter,
)

LOGGER = logging.getLogger(__name__)
START_MESSAGE = "The bot is running. News features will be added soon."


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    del context
    if update.message is None:
        LOGGER.warning("start_command_without_message")
        return
    await update.message.reply_text(START_MESSAGE)


async def handle_error(
    update: object, context: ContextTypes.DEFAULT_TYPE
) -> None:
    LOGGER.error(
        "telegram_update_failed",
        exc_info=(
            type(context.error),
            context.error,
            context.error.__traceback__,
        )
        if context.error
        else None,
    )


def build_application(settings: Settings) -> Application:
    database = Database(settings.database_url)
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.news_fetch_timeout_seconds)
    )
    repository = SQLAlchemyNewsRepository(database)
    feed_adapter = FeedFetcher(
        client,
        retry_attempts=settings.news_fetch_retry_attempts,
    )
    source_adapters = SourceAdapterRegistry(
        {
            SourceType.RSS: feed_adapter,
            SourceType.ATOM: feed_adapter,
        }
    )
    fetcher = SourceAdapterRouter(source_adapters)
    normalizer = DeterministicArticleNormalizer(
        CanonicalURLPolicy(
            version=settings.news_url_policy_version,
            tracking_parameters=settings.news_tracking_parameters,
        )
    )
    aggregator = DefaultNewsAggregator(
        repository,
        fetcher,
        normalizer,
        SystemClock(),
        deduplicator=DeterministicArticleDeduplicator(
            title_threshold=Decimal(
                str(settings.news_near_duplicate_title_threshold)
            ),
            content_threshold=Decimal(
                str(settings.news_near_duplicate_content_threshold)
            ),
            review_threshold=Decimal(
                str(settings.news_near_duplicate_review_threshold)
            ),
        ),
        duplicate_candidate_minimum_similarity=(
            settings.news_near_duplicate_review_threshold
        ),
        event_grouper=DeterministicEventGrouper(
            window_hours=settings.news_event_window_hours,
            title_weight=Decimal(str(settings.news_event_title_weight)),
            content_weight=Decimal(str(settings.news_event_content_weight)),
            topic_weight=Decimal(str(settings.news_event_topic_weight)),
            geography_weight=Decimal(
                str(settings.news_event_geography_weight)
            ),
            anchor_threshold=Decimal(
                str(settings.news_event_anchor_threshold)
            ),
            assignment_threshold=Decimal(
                str(settings.news_event_assignment_threshold)
            ),
            review_threshold=Decimal(
                str(settings.news_event_review_threshold)
            ),
        ),
        event_window_hours=settings.news_event_window_hours,
        max_concurrency=settings.news_max_concurrency,
        configuration_version=settings.news_url_policy_version,
    )

    async def post_init(application: Application) -> None:
        if application.job_queue is None:
            raise RuntimeError("Telegram JobQueue is required")
        scheduler = AggregationScheduler(
            application.job_queue,
            aggregator,
            interval_seconds=settings.news_scheduler_interval_seconds,
        )
        application.bot_data["news_scheduler"] = scheduler
        scheduler.start()

    async def post_shutdown(application: Application) -> None:
        scheduler = application.bot_data.pop("news_scheduler", None)
        if scheduler is not None:
            scheduler.stop()
        await client.aclose()
        await database.close()

    application = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    application.add_handler(CommandHandler("start", start))
    application.add_error_handler(handle_error)
    return application


def main() -> None:
    configure_logging()
    settings = Settings.from_env()
    application = build_application(settings)
    LOGGER.info("telegram_bot_starting")
    application.run_polling(allowed_updates=Update.ALL_TYPES)
