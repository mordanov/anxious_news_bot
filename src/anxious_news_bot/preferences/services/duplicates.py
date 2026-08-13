from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from uuid import UUID

from anxious_news_bot.preferences.domain import ProfileSnapshot
from anxious_news_bot.preferences.errors import PreferenceProposalInvalid
from anxious_news_bot.preferences.ports import PreferenceEquivalenceClassifier
from anxious_news_bot.preferences.schemas import CreateChangeSchema, EquivalenceSchema


def normalize_semantic_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", normalized)).strip("-")


@dataclass(frozen=True, slots=True)
class DuplicateResolution:
    equivalent_parameter_id: UUID | None
    checked_by_model: bool = False


class PreferenceDuplicateDetector:
    def __init__(
        self,
        classifier: PreferenceEquivalenceClassifier,
        *,
        candidate_threshold: float = 0.72,
    ) -> None:
        self._classifier = classifier
        self._candidate_threshold = candidate_threshold

    async def resolve(
        self, proposal: CreateChangeSchema, profile: ProfileSnapshot
    ) -> DuplicateResolution:
        key = normalize_semantic_key(proposal.semantic_key)
        exact = tuple(
            parameter
            for parameter in profile.parameters
            if normalize_semantic_key(parameter.semantic_key) == key
            or self._normalize(parameter.name) == self._normalize(proposal.name)
        )
        if exact:
            return DuplicateResolution(exact[0].id)

        candidates = tuple(
            parameter
            for parameter in profile.parameters
            if max(
                SequenceMatcher(
                    None,
                    self._normalize(proposal.name),
                    self._normalize(parameter.name),
                ).ratio(),
                SequenceMatcher(
                    None,
                    self._normalize(proposal.description),
                    self._normalize(parameter.description),
                ).ratio(),
            )
            >= self._candidate_threshold
        )
        if not candidates:
            return DuplicateResolution(None)

        candidate_snapshot = ProfileSnapshot(
            user_id=profile.user_id,
            revision=profile.revision,
            parameters=candidates,
        )
        raw = await self._classifier.classify(proposal, candidate_snapshot)
        result = EquivalenceSchema.model_validate_json(
            json.dumps(raw, separators=(",", ":")),
            strict=True,
        )
        if result.outcome == "distinct":
            return DuplicateResolution(None, checked_by_model=True)
        if result.candidate_parameter_id not in {
            parameter.id for parameter in candidates
        }:
            raise PreferenceProposalInvalid(
                "classifier selected a parameter outside candidate scope"
            )
        return DuplicateResolution(result.candidate_parameter_id, checked_by_model=True)

    @staticmethod
    def _normalize(value: str) -> str:
        return " ".join(unicodedata.normalize("NFKC", value).casefold().split())
