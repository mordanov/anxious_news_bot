from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from anxious_news_bot.preferences.domain import SupportedLanguage
from anxious_news_bot.preferences.services.language import UserLanguageService

LOGGER = logging.getLogger(__name__)

HELP_MESSAGES = {
    SupportedLanguage.RUSSIAN: """🤖 *Помощь* - Доступные команды

/start - Начать работу с ботом
/language - Выбрать язык интерфейса
/timezone - Установить часовой пояс (например, /timezone +3)
/news - Получить персонализированные новости
/tune - Настроить ваши предпочтения
/specify - Добавить явное предпочтение
/my - Показать мои предпочтения
/count - Установить размер дайджеста (5-20)
/help - Показать эту справку

Начните с команды /tune для настройки предпочтений или используйте /language для смены языка.""",
    SupportedLanguage.ENGLISH: """🤖 *Help* - Available Commands

/start - Get started with the bot
/language - Choose your language
/timezone - Set your timezone (e.g. /timezone +3)
/news - Get personalized news
/tune - Customize your preferences
/specify - Add an explicit preference
/my - View my preferences
/count - Set digest size (5-20)
/help - Show this help message

Start with /tune to customize your preferences or use /language to change the language.""",
    SupportedLanguage.SPANISH: """🤖 *Ayuda* - Comandos Disponibles

/start - Comenzar con el bot
/language - Elegir tu idioma
/timezone - Establecer tu zona horaria (ej. /timezone +3)
/news - Obtener noticias personalizadas
/tune - Personalizar tus preferencias
/specify - Añadir una preferencia explícita
/my - Ver mis preferencias
/count - Establecer tamaño del resumen (5-20)
/help - Mostrar esta ayuda

Comienza con /tune para personalizar tus preferencias o usa /language para cambiar el idioma.""",
}


class HelpTelegramAdapter:
    def __init__(self, service: UserLanguageService) -> None:
        self._service = service

    async def command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        if update.effective_user is None or update.message is None:
            LOGGER.warning("help_command_missing_user_or_message")
            return
        language = await self._service.get(
            update.effective_user.id,
            update.effective_user.language_code,
        )
        help_text = HELP_MESSAGES[language]
        await update.message.reply_text(
            help_text,
            parse_mode="Markdown",
        )
