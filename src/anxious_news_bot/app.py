import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from anxious_news_bot.config import Settings
from anxious_news_bot.logging import configure_logging

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
    application = Application.builder().token(settings.telegram_bot_token).build()
    application.add_handler(CommandHandler("start", start))
    application.add_error_handler(handle_error)
    return application


def main() -> None:
    configure_logging()
    settings = Settings.from_env()
    application = build_application(settings)
    LOGGER.info("telegram_bot_starting")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

