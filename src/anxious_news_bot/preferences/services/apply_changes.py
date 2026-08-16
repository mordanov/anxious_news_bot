from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Mapping
from uuid import UUID

from anxious_news_bot.preferences.domain import PreferenceOrigin, ProfileSnapshot
from anxious_news_bot.preferences.errors import PreferenceProposalInvalid
from anxious_news_bot.preferences.schemas import (
    AdjustChangeSchema,
    CreateChangeSchema,
    DeactivateChangeSchema,
    ExplicitPreferenceChangesSchema,
    PreferenceChangesSchema,
    ReactivateChangeSchema,
    RefineChangeSchema,
)
from anxious_news_bot.preferences.services.authority import (
    statement_matches_create,
    statement_matches_parameter,
)
from anxious_news_bot.preferences.services.duplicates import (
    normalize_semantic_key,
    rewrite_equivalent_create,
)


def proposal_hash(
    proposal: PreferenceChangesSchema | ExplicitPreferenceChangesSchema,
) -> str:
    value = proposal.model_dump(mode="json")
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(payload.encode()).hexdigest()


class DeterministicPreferenceChangeValidator:
    def validate(
        self,
        proposal: PreferenceChangesSchema | ExplicitPreferenceChangesSchema,
        profile: ProfileSnapshot,
        source_request_id: UUID,
        *,
        statement: str | None = None,
        duplicate_matches: Mapping[int, UUID] | None = None,
    ) -> PreferenceChangesSchema | ExplicitPreferenceChangesSchema:
        if proposal.source_request_id != source_request_id:
            if proposal.source is PreferenceOrigin.QUESTIONNAIRE:
                raise PreferenceProposalInvalid("questionnaire id does not match")
            raise PreferenceProposalInvalid("request id does not match")
        if proposal.base_profile_revision != profile.revision:
            raise PreferenceProposalInvalid("base profile revision does not match")

        if proposal.source is PreferenceOrigin.QUESTIONNAIRE:
            return self._validate_questionnaire(proposal, profile)
        if statement is None or not statement.strip():
            raise PreferenceProposalInvalid("explicit statement is required")
        return self._validate_explicit(
            proposal,
            profile,
            statement,
            duplicate_matches or {},
        )

    @staticmethod
    def _validate_questionnaire(
        proposal: PreferenceChangesSchema,
        profile: ProfileSnapshot,
    ) -> PreferenceChangesSchema:
        by_id = {parameter.id: parameter for parameter in profile.parameters}
        by_key = {parameter.semantic_key: parameter for parameter in profile.parameters}
        valid_changes = []
        for change in proposal.changes:
            if isinstance(change, CreateChangeSchema):
                if change.semantic_key in by_key:
                    raise PreferenceProposalInvalid(
                        "equivalent preference parameter already exists"
                    )
                valid_changes.append(change)
                continue
            parameter = by_id.get(change.parameter_id)
            if parameter is None:
                raise PreferenceProposalInvalid("unknown preference parameter")
            if parameter.origin is not PreferenceOrigin.QUESTIONNAIRE:
                raise PreferenceProposalInvalid(
                    "questionnaire batches may mutate only questionnaire parameters"
                )
            try:
                DeterministicPreferenceChangeValidator._validate_mutation(
                    change, parameter
                )
                valid_changes.append(change)
            except PreferenceProposalInvalid:
                pass  # drop no-op mutations silently
        if len(valid_changes) == len(proposal.changes):
            return proposal
        return PreferenceChangesSchema.model_construct(
            schema_version=proposal.schema_version,
            questionnaire_id=proposal.questionnaire_id,
            base_profile_revision=proposal.base_profile_revision,
            changes=tuple(valid_changes),
        )

    def _validate_explicit(
        self,
        proposal: ExplicitPreferenceChangesSchema,
        profile: ProfileSnapshot,
        statement: str,
        duplicate_matches: Mapping[int, UUID],
    ) -> ExplicitPreferenceChangesSchema:
        by_id = {parameter.id: parameter for parameter in profile.parameters}
        resolved_changes = []
        for index, change in enumerate(proposal.changes):
            if isinstance(change, CreateChangeSchema):
                if not statement_matches_create(
                    statement,
                    semantic_key=change.semantic_key,
                    name=change.name,
                    description=change.description,
                    instructions=change.evaluation_instructions,
                ):
                    raise PreferenceProposalInvalid(
                        "explicit request must preserve specific intent"
                    )
                duplicate_id = duplicate_matches.get(index)
                if duplicate_id is None:
                    duplicate_id = self._exact_duplicate_id(change, profile)
                if duplicate_id is None:
                    resolved_changes.append(change)
                    continue
                parameter = by_id.get(duplicate_id)
                if parameter is None:
                    raise PreferenceProposalInvalid(
                        "duplicate resolution points to an unknown parameter"
                    )
                resolved_changes.extend(rewrite_equivalent_create(change, parameter))
                continue

            parameter = by_id.get(change.parameter_id)
            if parameter is None:
                raise PreferenceProposalInvalid("unknown preference parameter")
            if not statement_matches_parameter(statement, parameter):
                if parameter.origin is PreferenceOrigin.EXPLICIT:
                    raise PreferenceProposalInvalid(
                        "explicit batch may not mutate unrelated explicit parameters"
                    )
                raise PreferenceProposalInvalid(
                    "explicit request must preserve specific intent"
                )
            self._validate_mutation(change, parameter)
            resolved_changes.append(change)

        if not resolved_changes:
            raise PreferenceProposalInvalid("request would not change preferences")
        return ExplicitPreferenceChangesSchema.model_construct(
            schema_version=proposal.schema_version,
            request_id=proposal.request_id,
            base_profile_revision=proposal.base_profile_revision,
            changes=tuple(resolved_changes),
        )

    @staticmethod
    def _validate_mutation(change, parameter) -> None:
        if isinstance(change, AdjustChangeSchema) and change.weight == parameter.weight:
            raise PreferenceProposalInvalid("adjust must change the weight")
        if isinstance(change, RefineChangeSchema) and all(
            (
                change.name in (None, parameter.name),
                change.description in (None, parameter.description),
                change.evaluation_instructions
                in (None, parameter.evaluation_instructions),
            )
        ):
            raise PreferenceProposalInvalid("refine must change descriptive data")
        if isinstance(change, DeactivateChangeSchema) and not parameter.active:
            raise PreferenceProposalInvalid("deactivate must change the active state")
        if isinstance(change, ReactivateChangeSchema) and parameter.active:
            raise PreferenceProposalInvalid("reactivate must change the active state")

    @staticmethod
    def _exact_duplicate_id(
        change: CreateChangeSchema,
        profile: ProfileSnapshot,
    ) -> UUID | None:
        normalized_key = normalize_semantic_key(change.semantic_key)
        normalized_name = DeterministicPreferenceChangeValidator._normalize(change.name)
        for parameter in profile.parameters:
            if (
                normalize_semantic_key(parameter.semantic_key) == normalized_key
                or DeterministicPreferenceChangeValidator._normalize(parameter.name)
                == normalized_name
            ):
                return parameter.id
        return None

    @staticmethod
    def _normalize(value: str) -> str:
        return " ".join(unicodedata.normalize("NFKC", value).casefold().split())
