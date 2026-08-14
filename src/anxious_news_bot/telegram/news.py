from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.exc import SQLAlchemyError
from telegram import Update
from telegram.ext import ContextTypes

from anxious_news_bot.digest.services.configuration import DigestConfigurationService
from anxious_news_bot.preferences.domain import SupportedLanguage
from anxious_news_bot.preferences.services.language import UserLanguageService
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
    },
    SupportedLanguage.ENGLISH: {
        "processing": "Selecting news for you...",
        "empty": "There are no suitable fresh articles yet.",
        "failed": "I couldn't prepare your news selection. Please try again later.",
        "header": "Your top news",
    },
    SupportedLanguage.SPANISH: {
        "processing": "Seleccionando noticias para ti...",
        "empty": "Todavía no hay noticias recientes adecuadas.",
        "failed": "No pude preparar tus noticias. Inténtalo de nuevo más tarde.",
        "header": "Tus noticias principales",
    },
}


class NewsTelegramAdapter:
    def __init__(
        self,
        service: PersonalNewsService,
        language_service: UserLanguageService,
        translator: NewsTitleTranslator,
        configuration_service: DigestConfigurationService,
    ) -> None:
        self._service = service
        self._language_service = language_service
        self._translator = translator
        self._configuration_service = configuration_service

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

        chunks = self._chunks(text["header"], items, translated_titles)
        await status_message.edit_text(chunks[0])
        for chunk in chunks[1:]:
            await message.reply_text(chunk)

    @classmethod
    def _chunks(
        cls,
        header: str,
        items: tuple[RankedNewsItem, ...],
        translated_titles: tuple[str, ...] | None = None,
    ) -> tuple[str, ...]:
        if translated_titles is not None and len(translated_titles) != len(items):
            raise ValueError("translated title count must match news item count")
        chunks: list[str] = []
        current = header
        titles = translated_titles or tuple(item.article.title for item in items)
        for item, title in zip(items, titles, strict=True):
            block = cls._item_text(item, title)
            if len(current) + len(block) + 2 > 3900:
                chunks.append(current)
                current = block
            else:
                current = f"{current}\n\n{block}"
        chunks.append(current)
        return tuple(chunks)

    @staticmethod
    def _item_text(item: RankedNewsItem, translated_title: str) -> str:
        title = " ".join(translated_title.split())[:240]
        source = " ".join(item.article.source_name.split())[:80]
        published = NewsTelegramAdapter._date(item.article.published_at)
        url = item.article.canonical_url[:1000]
        return f"{item.position}. {title}\n{source} · {published}\n{url}"

    @staticmethod
    def _date(value: datetime) -> str:
        return value.date().isoformat()
