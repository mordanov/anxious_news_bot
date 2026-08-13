from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from anxious_news_bot.preferences.domain import PreferenceOrigin, PreferenceParameter

_AUTHORITY_ORDER = {
    PreferenceOrigin.SYSTEM: 0,
    PreferenceOrigin.INFERENCE: 1,
    PreferenceOrigin.QUESTIONNAIRE: 2,
    PreferenceOrigin.EXPLICIT: 3,
}
_GENERIC_TOKENS = frozenset(
    {
        "about",
        "again",
        "article",
        "articles",
        "briefing",
        "city",
        "coverage",
        "explicit",
        "for",
        "from",
        "less",
        "local",
        "more",
        "much",
        "must",
        "near",
        "need",
        "news",
        "of",
        "please",
        "prefer",
        "prefers",
        "preference",
        "preferences",
        "relevant",
        "report",
        "reporting",
        "show",
        "specific",
        "stories",
        "story",
        "that",
        "the",
        "this",
        "topic",
        "topics",
        "updates",
        "want",
        "wants",
        "with",
    }
)
_TOKEN_PATTERN = re.compile(r"[\w']+")
_CYRILLIC_TRANSLITERATION = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "yo",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "kh",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "shch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
    "і": "i",
    "ї": "yi",
    "є": "ye",
    "ґ": "g",
}


def _transliterate_cyrillic(value: str) -> str:
    return "".join(
        _CYRILLIC_TRANSLITERATION.get(character, character) for character in value
    )


def _add_semantic_token(tokens: set[str], token: str) -> None:
    if len(token) < 3 or token in _GENERIC_TOKENS:
        return
    tokens.add(token)
    transliterated = _transliterate_cyrillic(token)
    if (
        transliterated != token
        and len(transliterated) >= 3
        and transliterated not in _GENERIC_TOKENS
    ):
        tokens.add(transliterated)


def derive_effective_authority(
    origin: PreferenceOrigin,
    evidence_sources: Iterable[PreferenceOrigin],
) -> PreferenceOrigin:
    candidates = tuple(evidence_sources)
    if not candidates:
        return origin
    return max(candidates, key=_AUTHORITY_ORDER.__getitem__)


def semantic_tokens(*values: str) -> frozenset[str]:
    tokens: set[str] = set()
    for value in values:
        normalized = unicodedata.normalize("NFKC", value).casefold()
        for token in _TOKEN_PATTERN.findall(normalized):
            _add_semantic_token(tokens, token)
    return frozenset(tokens)


def statement_matches_parameter(statement: str, parameter: PreferenceParameter) -> bool:
    return bool(
        semantic_tokens(statement)
        & semantic_tokens(
            parameter.semantic_key.replace("_", " "),
            parameter.name,
            parameter.description,
            parameter.evaluation_instructions,
        )
    )


def statement_matches_create(
    statement: str,
    *,
    semantic_key: str,
    name: str,
    description: str,
    instructions: str,
) -> bool:
    return bool(
        semantic_tokens(statement)
        & semantic_tokens(
            semantic_key.replace("_", " "),
            name,
            description,
            instructions,
        )
    )
