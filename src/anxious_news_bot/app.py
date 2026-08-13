import logging
from decimal import Decimal

import httpx
from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from anxious_news_bot.config import Settings
from anxious_news_bot.logging import configure_logging
from anxious_news_bot.news.domain import SourceType
from anxious_news_bot.news.infrastructure.database import Database
from anxious_news_bot.news.infrastructure.feeds import FeedFetcher
from anxious_news_bot.news.infrastructure.persistence import SQLAlchemyNewsRepository
from anxious_news_bot.news.infrastructure.scheduling import AggregationScheduler
from anxious_news_bot.news.services.aggregate import DefaultNewsAggregator, SystemClock
from anxious_news_bot.news.services.canonicalize import CanonicalURLPolicy
from anxious_news_bot.news.services.deduplicate import (
    DeterministicArticleDeduplicator,
)
from anxious_news_bot.news.services.event_grouping import DeterministicEventGrouper
from anxious_news_bot.news.services.normalize import DeterministicArticleNormalizer
from anxious_news_bot.news.services.source_catalog import (
    SourceAdapterRegistry,
    SourceAdapterRouter,
)
from anxious_news_bot.preferences.infrastructure.llm import (
    StructuredPreferenceModelAdapter,
)
from anxious_news_bot.preferences.infrastructure.persistence import (
    SQLAlchemyPreferenceRepository,
)
from anxious_news_bot.preferences.infrastructure.repository import (
    SystemClock as PreferenceClock,
)
from anxious_news_bot.preferences.infrastructure.retention import (
    PreferenceRetentionScheduler,
)
from anxious_news_bot.preferences.services.apply_changes import (
    DeterministicPreferenceChangeValidator,
)
from anxious_news_bot.preferences.services.duplicates import (
    PreferenceDuplicateDetector,
)
from anxious_news_bot.preferences.services.questionnaire_quality import (
    DeterministicQuestionnaireQualityValidator,
)
from anxious_news_bot.preferences.services.repetition import (
    SubstantialRepetitionDetector,
)
from anxious_news_bot.preferences.services.retention import (
    PreferenceRetentionService,
)
from anxious_news_bot.preferences.services.tokens import SecureCallbackTokenFactory
from anxious_news_bot.preferences.services.tune import PreferenceTuningService
from anxious_news_bot.telegram.tune import CALLBACK_PREFIX, TuneTelegramAdapter

LOGGER = logging.getLogger(__name__)
START_MESSAGE = "The bot is running. News features will be added soon."


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    del context
    if update.message is None:
        LOGGER.warning("start_command_without_message")
        return
    await update.message.reply_text(START_MESSAGE)


async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
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
            title_threshold=Decimal(str(settings.news_near_duplicate_title_threshold)),
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
            geography_weight=Decimal(str(settings.news_event_geography_weight)),
            anchor_threshold=Decimal(str(settings.news_event_anchor_threshold)),
            assignment_threshold=Decimal(str(settings.news_event_assignment_threshold)),
            review_threshold=Decimal(str(settings.news_event_review_threshold)),
        ),
        event_window_hours=settings.news_event_window_hours,
        max_concurrency=settings.news_max_concurrency,
        configuration_version=settings.news_url_policy_version,
    )
    preference_repository = SQLAlchemyPreferenceRepository(
        database,
        history_context_limit=settings.preferences_history_question_limit,
        duplicate_threshold=settings.preferences_duplicate_review_threshold,
    )
    preference_model = StructuredPreferenceModelAdapter(
        client,
        base_url=settings.preferences_model_base_url,
        api_key=settings.preferences_model_api_key,
        model=settings.preferences_model_name,
        timeout_seconds=settings.preferences_model_timeout_seconds,
        retry_attempts=settings.preferences_model_retry_attempts,
        max_response_bytes=settings.preferences_model_max_response_bytes,
    )
    preference_clock = PreferenceClock()
    tuning_service = PreferenceTuningService(
        preference_repository,
        preference_model,
        DeterministicQuestionnaireQualityValidator(
            repetition_threshold=settings.preferences_repetition_threshold
        ),
        DeterministicPreferenceChangeValidator(),
        SecureCallbackTokenFactory(),
        preference_clock,
        duplicate_detector=PreferenceDuplicateDetector(
            preference_model,
            candidate_threshold=settings.preferences_duplicate_review_threshold,
        ),
        repetition_detector=SubstantialRepetitionDetector(
            threshold=settings.preferences_repetition_threshold
        ),
    )
    tune_adapter = TuneTelegramAdapter(tuning_service)
    retention_service = PreferenceRetentionService(
        preference_repository,
        preference_clock,
        questionnaire_days=settings.preferences_questionnaire_retention_days,
        history_days=settings.preferences_change_history_retention_days,
        batch_size=settings.preferences_retention_batch_size,
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
        retention_scheduler = PreferenceRetentionScheduler(
            application.job_queue,
            retention_service,
            interval_seconds=settings.preferences_retention_scan_interval_seconds,
        )
        application.bot_data["preference_retention_scheduler"] = retention_scheduler
        retention_scheduler.start()

    async def post_shutdown(application: Application) -> None:
        scheduler = application.bot_data.pop("news_scheduler", None)
        if scheduler is not None:
            scheduler.stop()
        retention_scheduler = application.bot_data.pop(
            "preference_retention_scheduler", None
        )
        if retention_scheduler is not None:
            retention_scheduler.stop()
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
    application.add_handler(CommandHandler("tune", tune_adapter.command))
    application.add_handler(
        CallbackQueryHandler(
            tune_adapter.callback,
            pattern=rf"^{CALLBACK_PREFIX}",
        )
    )
    application.add_error_handler(handle_error)
    return application


def main() -> None:
    configure_logging()
    settings = Settings.from_env()
    application = build_application(settings)
    LOGGER.info("telegram_bot_starting")
    application.run_polling(allowed_updates=Update.ALL_TYPES)
