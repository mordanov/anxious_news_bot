from __future__ import annotations

import logging
from datetime import datetime, timedelta
from datetime import timezone as _tz

from sqlalchemy.exc import SQLAlchemyError
from telegram import Update
from telegram.ext import ContextTypes

from anxious_news_bot.digest.services.configuration import DigestConfigurationService
from anxious_news_bot.preferences.domain import SupportedLanguage
from anxious_news_bot.preferences.services.language import UserLanguageService
from anxious_news_bot.preferences.services.timezone import UserTimezoneService
from anxious_news_bot.ranking.domain import RankedNewsItem
from anxious_news_bot.ranking.errors import RankingRunError
from anxious_news_bot.ranking.services.news import PersonalNewsService
from anxious_news_bot.telegram.news_translation import (
    NewsTitleTranslator,
    NewsTranslationError,
)

LOGGER = logging.getLogger(__name__)
MESSAGES = {
    SupportedLanguage.RUSSIAN: {
        "processing": "Подбираю новости для вас...",
        "empty": "Подходящих свежих новостей пока нет.",
        "failed": "Не удалось составить подборку новостей. Попробуйте позже.",
        "header": "Ваши главные новости",
        "shortage": (
            "Получено только {actual} из {requested} новостей. "
            "Запустите /tune, чтобы проверить или обновить предпочтения."
        ),
    },
    SupportedLanguage.ENGLISH: {
        "processing": "Selecting news for you...",
        "empty": "There are no suitable fresh articles yet.",
        "failed": "I couldn't prepare your news selection. Please try again later.",
        "header": "Your top news",
        "shortage": (
            "Only {actual} of {requested} news items were available. "
            "Run /tune to review or update your preferences."
        ),
    },
    SupportedLanguage.SPANISH: {
        "processing": "Seleccionando noticias para ti...",
        "empty": "Todavía no hay noticias recientes adecuadas.",
        "failed": "No pude preparar tus noticias. Inténtalo de nuevo más tarde.",
        "header": "Tus noticias principales",
        "shortage": (
            "Solo había {actual} de {requested} noticias disponibles. "
            "Usa /tune para revisar o actualizar tus preferencias."
        ),
    },
}


class NewsTelegramAdapter:
    def __init__(
        self,
        service: PersonalNewsService,
        language_service: UserLanguageService,
        translator: NewsTitleTranslator,
        configuration_service: DigestConfigurationService,
        timezone_service: UserTimezoneService | None = None,
    ) -> None:
        self._service = service
        self._language_service = language_service
        self._translator = translator
        self._configuration_service = configuration_service
        self._timezone_service = timezone_service

    async def command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        user = update.effective_user
        message = update.message
        if user is None or message is None:
            LOGGER.warning("news_command_missing_user_or_message")
            return
        language = await self._language_service.get(user.id, user.language_code)
        text = MESSAGES[language]
        status_message = await message.reply_text(text["processing"])
        utc_offset = (
            await self._timezone_service.get(user.id)
            if self._timezone_service is not None
            else 0
        )
        try:
            config = await self._configuration_service.get_current(
                user.id,
                user.language_code,
            )
            count = config.digest_count
            items = await self._service.top(
                user.id,
                f"telegram-news:{update.update_id}",
                count=count,
            )
            translated_titles = await self._translator.translate(
                tuple(item.article.title for item in items),
                language,
            )
        except (RankingRunError, SQLAlchemyError):
            await status_message.edit_text(text["failed"])
            return
        except NewsTranslationError as exc:
            LOGGER.warning(
                "news_headline_translation_failed",
                extra={
                    "news": {
                        "stage": "headline_translation",
                        "status": "failed",
                        "exception_type": type(exc).__name__,
                        "language_code": language.value,
                        "article_count": len(items),
                    }
                },
            )
            await status_message.edit_text(text["failed"])
            return
        if not items:
            await status_message.edit_text(text["empty"])
            return

        chunks = self._chunks(text["header"], items, translated_titles, utc_offset)
        await status_message.edit_text(chunks[0])
        for chunk in chunks[1:]:
            await message.reply_text(chunk)
        if len(items) < count:
            await message.reply_text(
                text["shortage"].format(actual=len(items), requested=count)
            )

    @classmethod
    def _chunks(
        cls,
        header: str,
        items: tuple[RankedNewsItem, ...],
        translated_titles: tuple[str, ...] | None = None,
        utc_offset_hours: int = 0,
    ) -> tuple[str, ...]:
        if translated_titles is not None and len(translated_titles) != len(items):
            raise ValueError("translated title count must match news item count")
        chunks: list[str] = []
        current = header
        titles = translated_titles or tuple(item.article.title for item in items)
        for item, title in zip(items, titles, strict=True):
            block = cls._item_text(item, title, utc_offset_hours)
            if len(current) + len(block) + 2 > 3900:
                chunks.append(current)
                current = block
            else:
                current = f"{current}\n\n{block}"
        chunks.append(current)
        return tuple(chunks)

    @staticmethod
    def _item_text(
        item: RankedNewsItem, translated_title: str, utc_offset_hours: int = 0
    ) -> str:
        title = " ".join(translated_title.split())[:240]
        source = " ".join(item.article.source_name.split())[:80]
        published = NewsTelegramAdapter._date(
            item.article.published_at, utc_offset_hours
        )
        url = item.article.canonical_url[:1000]
        return f"{item.position}. {title}\n{source} · {published}\n{url}"

    @staticmethod
    def _date(value: datetime, utc_offset_hours: int = 0) -> str:
        tz = _tz(timedelta(hours=utc_offset_hours))
        local = value.astimezone(tz)
        date_time_str = local.strftime("%Y-%m-%d %H:%M")
        if utc_offset_hours == 0:
            return f"{date_time_str} UTC"
        sign = "+" if utc_offset_hours > 0 else ""
        return f"{date_time_str} UTC{sign}{utc_offset_hours}"
