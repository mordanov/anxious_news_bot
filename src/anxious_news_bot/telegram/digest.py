"""Pure structured-digest rendering and Telegram delivery."""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime

import httpx
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TimedOut

from anxious_news_bot.digest.domain import (
    DeliveryAcknowledgement,
    RenderedPart,
    StructuredDigest,
    StructuredDigestItem,
)
from anxious_news_bot.digest.errors import (
    AmbiguousDeliveryError,
    DefiniteTransientDeliveryError,
    PermanentDeliveryError,
)
from anxious_news_bot.preferences.domain import SupportedLanguage

LOGGER = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 3900

DIGEST_HEADERS = {
    SupportedLanguage.RUSSIAN: "Ваш новостной дайджест",
    SupportedLanguage.ENGLISH: "Your news digest",
    SupportedLanguage.SPANISH: "Tu resumen de noticias",
}

TITLE_MAX_DISPLAY = 200
SUMMARY_MAX_DISPLAY = 500
_SPACE = re.compile(r"\s+")


def _language_from_code(code: str) -> SupportedLanguage:
    for lang in SupportedLanguage:
        if lang.value == code:
            return lang
    return SupportedLanguage.ENGLISH


def _render_item(item: StructuredDigestItem) -> str:
    title = _SPACE.sub(" ", item.title).strip()[:TITLE_MAX_DISPLAY]
    summary = _SPACE.sub(" ", item.summary).strip()[:SUMMARY_MAX_DISPLAY]
    date_str = item.published_at.strftime("%Y-%m-%d")
    source = _SPACE.sub(" ", item.source_name).strip()[:100]
    return f"{item.position}. {title}\n{summary}\n{source} - {date_str}\n{item.canonical_url}"


def render_digest(
    digest: StructuredDigest, renderer_version: str
) -> tuple[RenderedPart, ...]:
    """Deterministic rendering of structured digest into message parts."""
    if not renderer_version:
        raise ValueError("renderer_version must not be empty")
    if not digest.items:
        return ()

    language = _language_from_code(digest.language)
    header = f"{DIGEST_HEADERS[language]}\n\n"

    parts: list[RenderedPart] = []
    current_content = header
    current_first = 1
    current_items: list[StructuredDigestItem] = []

    for item in digest.items:
        block = _render_item(item)
        separator = "\n\n" if current_items else ""
        candidate = current_content + separator + block

        if len(candidate) > MAX_MESSAGE_LENGTH and current_items:
            # Finalize current part
            parts.append(
                _create_part(
                    len(parts) + 1,
                    current_content,
                    current_first,
                    current_items[-1].position,
                )
            )
            current_content = block
            current_first = item.position
            current_items = [item]
        else:
            current_content = candidate
            current_items.append(item)

    if current_items:
        parts.append(
            _create_part(
                len(parts) + 1,
                current_content,
                current_first,
                current_items[-1].position,
            )
        )

    return tuple(parts)


def _create_part(
    ordinal: int, content: str, first_pos: int, last_pos: int
) -> RenderedPart:
    h = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return RenderedPart(
        ordinal=ordinal,
        first_item_position=first_pos,
        last_item_position=last_pos,
        content=content,
        content_hash=h,
    )


class TelegramDigestDelivery:
    """Sends rendered digest parts via Telegram bot."""

    def __init__(self, bot: object | None = None) -> None:
        self._bot = bot

    def bind(self, bot: object) -> None:
        self._bot = bot

    def render(
        self, digest: StructuredDigest, renderer_version: str
    ) -> tuple[RenderedPart, ...]:
        return render_digest(digest, renderer_version)

    async def send(
        self, telegram_user_id: int, rendered_part: RenderedPart
    ) -> DeliveryAcknowledgement:
        from datetime import UTC

        if self._bot is None:
            raise RuntimeError("Telegram digest delivery is not bound to a bot")
        try:
            message = await self._bot.send_message(
                chat_id=telegram_user_id,
                text=rendered_part.content,
            )
            accepted_at = getattr(message, "date", None)
            if (
                not isinstance(accepted_at, datetime)
                or accepted_at.tzinfo is None
                or accepted_at.utcoffset() is None
            ):
                accepted_at = datetime.now(UTC)
            return DeliveryAcknowledgement(
                provider_message_id=str(message.message_id),
                accepted_at=accepted_at,
            )
        except BadRequest as exc:
            raise PermanentDeliveryError(
                "Telegram permanently rejected the digest", code="bad_request"
            ) from exc
        except Forbidden as exc:
            raise PermanentDeliveryError(
                "Telegram recipient is unavailable",
                code="forbidden",
            ) from exc
        except RetryAfter as exc:
            raise DefiniteTransientDeliveryError(
                "Telegram requested a bounded retry",
                code="rate_limited",
            ) from exc
        except TimedOut as exc:
            raise AmbiguousDeliveryError(
                "Telegram acknowledgement timed out",
                code="timeout_ambiguous",
            ) from exc
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            raise DefiniteTransientDeliveryError(
                "Telegram connection was not established",
                code="connect_transient",
            ) from exc
        except (httpx.ReadTimeout, httpx.RemoteProtocolError, NetworkError) as exc:
            raise AmbiguousDeliveryError(
                "Telegram delivery acknowledgement is unknown",
                code="transport_ambiguous",
            ) from exc
        except Exception as exc:
            raise DefiniteTransientDeliveryError(
                "Telegram delivery failed before acknowledgement",
                code="send_transient",
            ) from exc
