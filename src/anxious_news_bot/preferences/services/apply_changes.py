from __future__ import annotations

import hashlib
import json

from anxious_news_bot.preferences.domain import PreferenceOrigin, ProfileSnapshot
from anxious_news_bot.preferences.errors import PreferenceProposalInvalid
from anxious_news_bot.preferences.schemas import (
    AdjustChangeSchema,
    CreateChangeSchema,
    DeactivateChangeSchema,
    PreferenceChangesSchema,
    ReactivateChangeSchema,
    RefineChangeSchema,
)


def proposal_hash(proposal: PreferenceChangesSchema) -> str:
    value = proposal.model_dump(mode="json")
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(payload.encode()).hexdigest()


class DeterministicPreferenceChangeValidator:
    def validate(
        self,
        proposal: PreferenceChangesSchema,
        profile: ProfileSnapshot,
        questionnaire_id,
    ) -> PreferenceChangesSchema:
        if proposal.questionnaire_id != questionnaire_id:
            raise PreferenceProposalInvalid("questionnaire id does not match")
        if proposal.base_profile_revision != profile.revision:
            raise PreferenceProposalInvalid("base profile revision does not match")

        by_id = {parameter.id: parameter for parameter in profile.parameters}
        by_key = {parameter.semantic_key: parameter for parameter in profile.parameters}
        for change in proposal.changes:
            if isinstance(change, CreateChangeSchema):
                if change.semantic_key in by_key:
                    raise PreferenceProposalInvalid(
                        "equivalent preference parameter already exists"
                    )
                continue
            parameter = by_id.get(change.parameter_id)
            if parameter is None:
                raise PreferenceProposalInvalid("unknown preference parameter")
            if parameter.origin is not PreferenceOrigin.QUESTIONNAIRE:
                raise PreferenceProposalInvalid(
                    "questionnaire batches may mutate only questionnaire parameters"
                )
            if (
                isinstance(change, AdjustChangeSchema)
                and change.weight == parameter.weight
            ):
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
                raise PreferenceProposalInvalid("parameter is already inactive")
            if isinstance(change, ReactivateChangeSchema) and parameter.active:
                raise PreferenceProposalInvalid("parameter is already active")
        return proposal
