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
from anxious_news_bot.preferences.services.language import UserLanguageService
from anxious_news_bot.preferences.services.questionnaire_quality import (
    DeterministicQuestionnaireQualityValidator,
)
from anxious_news_bot.preferences.services.repetition import (
    SubstantialRepetitionDetector,
)
from anxious_news_bot.preferences.services.retention import (
    PreferenceRetentionService,
)
from anxious_news_bot.preferences.services.specify import ExplicitPreferenceService
from anxious_news_bot.preferences.services.tokens import SecureCallbackTokenFactory
from anxious_news_bot.preferences.services.tune import PreferenceTuningService
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
from anxious_news_bot.ranking.infrastructure.retention import (
    RankingRetentionScheduler,
)
from anxious_news_bot.ranking.services.configuration import (
    ValidatedRankingConfigurationProvider,
)
from anxious_news_bot.ranking.services.evaluate import ArticleEvaluationService
from anxious_news_bot.ranking.services.explain import (
    DeterministicRankingExplainer,
)
from anxious_news_bot.ranking.services.news import PersonalNewsService
from anxious_news_bot.ranking.services.rank import PersonalRankingService
from anxious_news_bot.ranking.services.retention import RankingRetentionService
from anxious_news_bot.ranking.services.score import DeterministicRankingScorer
from anxious_news_bot.telegram.language import (
    CALLBACK_PREFIX as LANGUAGE_CALLBACK_PREFIX,
)
from anxious_news_bot.telegram.language import LanguageTelegramAdapter
from anxious_news_bot.telegram.news import NewsTelegramAdapter
from anxious_news_bot.telegram.news_translation import StructuredNewsTitleTranslator
from anxious_news_bot.telegram.specify import SpecifyTelegramAdapter
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
        explicit_history_limit=settings.preferences_explicit_history_limit,
    )
    preference_model = StructuredPreferenceModelAdapter(
        client,
        base_url=settings.preferences_model_base_url,
        api_key=settings.preferences_model_api_key,
        model=settings.preferences_model_name,
        timeout_seconds=settings.preferences_model_timeout_seconds,
        retry_attempts=settings.preferences_model_retry_attempts,
        max_response_bytes=settings.preferences_model_max_response_bytes,
        explicit_history_limit=settings.preferences_explicit_history_limit,
    )
    preference_clock = PreferenceClock()
    change_validator = DeterministicPreferenceChangeValidator()
    duplicate_detector = PreferenceDuplicateDetector(
        preference_model,
        candidate_threshold=settings.preferences_duplicate_review_threshold,
    )
    tuning_service = PreferenceTuningService(
        preference_repository,
        preference_model,
        DeterministicQuestionnaireQualityValidator(
            repetition_threshold=settings.preferences_repetition_threshold
        ),
        change_validator,
        SecureCallbackTokenFactory(),
        preference_clock,
        duplicate_detector=duplicate_detector,
        repetition_detector=SubstantialRepetitionDetector(
            threshold=settings.preferences_repetition_threshold
        ),
        generation_attempts=settings.preferences_questionnaire_generation_attempts,
        interpretation_attempts=settings.preferences_interpretation_attempts,
    )
    language_service = UserLanguageService(preference_repository, preference_clock)
    specify_service = ExplicitPreferenceService(
        preference_repository,
        preference_model,
        change_validator,
        preference_clock,
        duplicate_detector=duplicate_detector,
        stale_retry_limit=settings.preferences_explicit_stale_retry_limit,
        max_statement_length=settings.preferences_explicit_request_max_length,
    )
    tune_adapter = TuneTelegramAdapter(tuning_service, language_service)
    language_adapter = LanguageTelegramAdapter(language_service)
    specify_adapter = SpecifyTelegramAdapter(
        specify_service,
        max_text_length=settings.preferences_explicit_request_max_length,
    )
    retention_service = PreferenceRetentionService(
        preference_repository,
        preference_clock,
        questionnaire_days=settings.preferences_questionnaire_retention_days,
        history_days=settings.preferences_change_history_retention_days,
        batch_size=settings.preferences_retention_batch_size,
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
        preference_clock,
        evaluator_name=STRUCTURED_EVALUATOR_NAME,
        evaluator_version=STRUCTURED_EVALUATOR_VERSION,
        prompt_version=ARTICLE_EVALUATION_PROMPT_VERSION,
        retry_attempts=settings.ranking_evaluation_retry_attempts,
    )
    ranking_configuration_provider = (
        ValidatedRankingConfigurationProvider.from_settings(settings)
    )
    ranking_scorer = DeterministicRankingScorer()
    ranking_explainer = DeterministicRankingExplainer()
    personal_ranking_service = PersonalRankingService(
        ranking_repository,
        ranking_configuration_provider,
        ranking_scorer,
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
    news_title_translator = StructuredNewsTitleTranslator(
        client,
        base_url=settings.ranking_model_base_url,
        api_key=settings.ranking_model_api_key,
        model=settings.ranking_model_name,
        timeout_seconds=settings.ranking_model_timeout_seconds,
        retry_attempts=settings.ranking_model_retry_attempts,
        max_response_bytes=settings.ranking_model_max_response_bytes,
    )
    news_adapter = NewsTelegramAdapter(
        personal_news_service,
        language_service,
        news_title_translator,
    )
    ranking_retention_service = RankingRetentionService(
        ranking_repository,
        RankingClock(),
        raw_response_days=settings.ranking_raw_response_retention_days,
        detail_days=settings.ranking_detail_retention_days,
        batch_size=settings.ranking_retention_batch_size,
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
        ranking_retention_scheduler = RankingRetentionScheduler(
            application.job_queue,
            ranking_retention_service,
            interval_seconds=settings.ranking_retention_scan_interval_seconds,
        )
        application.bot_data["ranking_retention_scheduler"] = (
            ranking_retention_scheduler
        )
        ranking_retention_scheduler.start()

    async def post_shutdown(application: Application) -> None:
        scheduler = application.bot_data.pop("news_scheduler", None)
        if scheduler is not None:
            scheduler.stop()
        retention_scheduler = application.bot_data.pop(
            "preference_retention_scheduler", None
        )
        if retention_scheduler is not None:
            retention_scheduler.stop()
        ranking_retention_scheduler = application.bot_data.pop(
            "ranking_retention_scheduler",
            None,
        )
        if ranking_retention_scheduler is not None:
            ranking_retention_scheduler.stop()
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
    application.add_handler(CommandHandler("language", language_adapter.command))
    application.add_handler(CommandHandler("news", news_adapter.command))
    application.add_handler(CommandHandler("tune", tune_adapter.command))
    application.add_handler(CommandHandler("specify", specify_adapter.command))
    application.add_handler(
        CallbackQueryHandler(
            language_adapter.callback,
            pattern=rf"^{LANGUAGE_CALLBACK_PREFIX}",
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            tune_adapter.callback,
            pattern=rf"^{CALLBACK_PREFIX}",
        )
    )
    application.add_error_handler(handle_error)
    application.bot_data["article_evaluation_service"] = article_evaluation_service
    application.bot_data["ranking_configuration_provider"] = (
        ranking_configuration_provider
    )
    application.bot_data["ranking_scorer"] = ranking_scorer
    application.bot_data["ranking_explainer"] = ranking_explainer
    application.bot_data["personal_ranking_service"] = personal_ranking_service
    application.bot_data["personal_news_service"] = personal_news_service
    application.bot_data["ranking_repository"] = ranking_repository
    application.bot_data["ranking_evaluator"] = ranking_evaluator
    return application


def main() -> None:
    configure_logging()
    settings = Settings.from_env()
    application = build_application(settings)
    LOGGER.info("telegram_bot_starting")
    application.run_polling(allowed_updates=Update.ALL_TYPES)
