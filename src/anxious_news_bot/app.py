import logging
import os
from pathlib import Path

import httpx
from apscheduler.jobstores.base import JobLookupError
from telegram import BotCommand, Update
from telegram.error import NetworkError, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)
from telegram.request import HTTPXRequest

from anxious_news_bot.config import Settings
from anxious_news_bot.digest.domain import validate_local_time
from anxious_news_bot.digest.infrastructure.persistence import (
    SQLAlchemyDigestRepository,
)
from anxious_news_bot.digest.services.configuration import DigestConfigurationService
from anxious_news_bot.infrastructure.users import (
    ApplicationUserProvisioner,
    DigestDefaults,
)
from anxious_news_bot.logging import configure_logging
from anxious_news_bot.news.infrastructure.database import Database
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
from anxious_news_bot.telegram.count import CountTelegramAdapter
from anxious_news_bot.telegram.help import HelpTelegramAdapter
from anxious_news_bot.telegram.language import (
    CALLBACK_PREFIX as LANGUAGE_CALLBACK_PREFIX,
)
from anxious_news_bot.telegram.language import LanguageTelegramAdapter
from anxious_news_bot.telegram.my import MyTelegramAdapter
from anxious_news_bot.telegram.news import NewsTelegramAdapter
from anxious_news_bot.telegram.news_translation import StructuredNewsTitleTranslator
from anxious_news_bot.telegram.specify import SpecifyTelegramAdapter
from anxious_news_bot.telegram.tune import CALLBACK_PREFIX, TuneTelegramAdapter

LOGGER = logging.getLogger(__name__)
START_MESSAGE = "The bot is running. Tune your preferences with /tune command, set language with /language command."

_BOT_COMMANDS = [
    BotCommand("start", "Get started with the bot"),
    BotCommand("language", "Set your language"),
    BotCommand("news", "Get personalized news"),
    BotCommand("tune", "Customize your preferences"),
    BotCommand("specify", "Add an explicit preference"),
    BotCommand("my", "View my preferences"),
    BotCommand("count", "Set digest size (5-20)"),
    BotCommand("help", "Show available commands"),
]


def _runtime_limit(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8").strip()[:100]
    except OSError:
        return None


def _stop_scheduler(scheduler: object | None) -> None:
    if scheduler is None:
        return
    try:
        scheduler.stop()
    except JobLookupError:
        # Application.stop() may already have removed JobQueue jobs.
        LOGGER.debug("scheduler_job_already_removed")


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
    user_provisioner = ApplicationUserProvisioner(
        DigestDefaults(
            count=settings.digest_default_count,
            local_time=validate_local_time(settings.digest_default_local_time),
            timezone_name=settings.digest_default_timezone,
        )
    )
    preference_repository = SQLAlchemyPreferenceRepository(
        database,
        history_context_limit=settings.preferences_history_question_limit,
        duplicate_threshold=settings.preferences_duplicate_review_threshold,
        explicit_history_limit=settings.preferences_explicit_history_limit,
        user_provisioner=user_provisioner,
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
    help_adapter = HelpTelegramAdapter(language_service)
    specify_adapter = SpecifyTelegramAdapter(
        specify_service,
        language_service,
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
    ranking_retention_service = RankingRetentionService(
        ranking_repository,
        RankingClock(),
        raw_response_days=settings.ranking_raw_response_retention_days,
        detail_days=settings.ranking_detail_retention_days,
        batch_size=settings.ranking_retention_batch_size,
    )

    # Digest module (configuration only — execution runs in digest_app.py)
    digest_repository = SQLAlchemyDigestRepository(
        database,
        user_provisioner=user_provisioner,
    )
    digest_clock = PreferenceClock()
    digest_config_service = DigestConfigurationService(digest_repository, digest_clock)
    count_adapter = CountTelegramAdapter(
        digest_config_service,
        language_service,
    )
    my_adapter = MyTelegramAdapter(preference_repository, language_service)
    news_adapter = NewsTelegramAdapter(
        personal_news_service,
        language_service,
        news_title_translator,
        digest_config_service,
    )

    async def post_init(application: Application) -> None:
        LOGGER.info(
            "runtime_configuration",
            extra={
                "news": {
                    "command_candidate_limit": settings.news_command_candidate_limit,
                    "command_evaluation_concurrency": (
                        settings.news_command_evaluation_concurrency
                    ),
                    "logical_cpu_count": os.cpu_count(),
                    "cgroup_cpu_limit": _runtime_limit("/sys/fs/cgroup/cpu.max"),
                    "cgroup_memory_limit": _runtime_limit("/sys/fs/cgroup/memory.max"),
                },
                "ranking": {
                    "event": "runtime_configuration",
                    "stage": "startup",
                    "status": "configured",
                    "configuration_version": settings.ranking_configuration_version,
                    "maximum_candidates": settings.ranking_maximum_candidates,
                    "minimum_source_quality": str(
                        settings.ranking_minimum_source_quality
                    ),
                    "event_cap": settings.ranking_event_cap,
                    "topic_cap": settings.ranking_topic_cap,
                    "source_cap": settings.ranking_source_cap,
                    "explicit_weight_threshold": str(
                        settings.ranking_explicit_weight_threshold
                    ),
                    "explicit_relevance_threshold": str(
                        settings.ranking_explicit_relevance_threshold
                    ),
                },
            },
        )
        try:
            await application.bot.set_my_commands(_BOT_COMMANDS)
            LOGGER.info("Bot commands registered (%d)", len(_BOT_COMMANDS))
        except (NetworkError, TelegramError) as e:
            LOGGER.warning("Failed to register bot commands: %s", e)
        if application.job_queue is None:
            raise RuntimeError("Telegram JobQueue is required")
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
        retention_scheduler = application.bot_data.pop(
            "preference_retention_scheduler", None
        )
        _stop_scheduler(retention_scheduler)
        ranking_retention_scheduler = application.bot_data.pop(
            "ranking_retention_scheduler",
            None,
        )
        _stop_scheduler(ranking_retention_scheduler)
        await client.aclose()
        await database.close()

    application = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .request(
            HTTPXRequest(
                connection_pool_size=8,
                connect_timeout=settings.telegram_connect_timeout_seconds,
                read_timeout=settings.telegram_read_timeout_seconds,
                write_timeout=settings.telegram_write_timeout_seconds,
                pool_timeout=settings.telegram_pool_timeout_seconds,
            )
        )
        .get_updates_request(
            HTTPXRequest(
                connection_pool_size=2,
                connect_timeout=settings.telegram_connect_timeout_seconds,
                read_timeout=settings.telegram_read_timeout_seconds,
                write_timeout=settings.telegram_write_timeout_seconds,
                pool_timeout=settings.telegram_pool_timeout_seconds,
            )
        )
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("language", language_adapter.command))
    application.add_handler(CommandHandler("help", help_adapter.command))
    application.add_handler(CommandHandler("news", news_adapter.command))
    application.add_handler(CommandHandler("tune", tune_adapter.command))
    application.add_handler(CommandHandler("specify", specify_adapter.command))
    application.add_handler(CommandHandler("count", count_adapter.command))
    application.add_handler(CommandHandler("my", my_adapter.command))
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
    application.bot_data["digest_repository"] = digest_repository
    application.bot_data["digest_configuration_service"] = digest_config_service
    return application


def main() -> None:
    configure_logging()
    settings = Settings.from_env()
    application = build_application(settings)
    LOGGER.info("telegram_bot_starting")
    application.run_polling(allowed_updates=Update.ALL_TYPES)
