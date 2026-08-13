from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from anxious_news_bot.preferences.domain import (
    PreferenceOrigin,
    PreferenceParameter,
    ProfileSnapshot,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)
USER_ID = uuid4()


def _parameter(
    *,
    semantic_key: str,
    name: str,
    description: str,
    instructions: str,
    weight: str = "0.40",
    origin: PreferenceOrigin = PreferenceOrigin.QUESTIONNAIRE,
    active: bool = True,
) -> PreferenceParameter:
    return PreferenceParameter(
        id=uuid4(),
        user_id=USER_ID,
        semantic_key=semantic_key,
        name=name,
        description=description,
        evaluation_instructions=instructions,
        weight=Decimal(weight),
        origin=origin,
        active=active,
        created_at=NOW,
        updated_at=NOW,
    )


def _profile(*parameters: PreferenceParameter, revision: int = 3) -> ProfileSnapshot:
    return ProfileSnapshot(USER_ID, revision, parameters)


@dataclass(frozen=True, slots=True)
class ReviewedSpecificityCase:
    slug: str
    statement: str
    profile: ProfileSnapshot
    proposal_change: dict[str, object]
    expected_specific_semantic_key: str
    expected_actions: frozenset[str]
    duplicate_matches: tuple[tuple[int, UUID], ...] = ()


@dataclass(frozen=True, slots=True)
class ReviewedEquivalenceCase:
    slug: str
    statement: str
    profile: ProfileSnapshot
    proposal_change: dict[str, object]
    expected_actions: frozenset[str]
    exact_match: bool
    duplicate_matches: tuple[tuple[int, UUID], ...] = ()


_BROAD_RUSSIA = _parameter(
    semantic_key="russia_news",
    name="Russia news",
    description="Broad reporting about Russia.",
    instructions="Prefer broad reporting about Russia.",
    weight="0.35",
)
_SPECIFIC_KIROV = _parameter(
    semantic_key="kirov_city_news",
    name="Kirov city news",
    description="Specific city reporting about Kirov.",
    instructions="Prefer relevant Kirov city reporting.",
    weight="0.55",
)
_INACTIVE_KIROV = _parameter(
    semantic_key="kirov_city_news",
    name="Kirov city news",
    description="Specific city reporting about Kirov.",
    instructions="Prefer relevant Kirov city reporting.",
    weight="0.40",
    active=False,
)
_SYSTEM_TRANSPORT = _parameter(
    semantic_key="kirov_transport",
    name="Kirov transport",
    description="Specific municipal transport reporting about Kirov.",
    instructions="Prefer articles about Kirov transport projects.",
    weight="0.45",
    origin=PreferenceOrigin.SYSTEM,
)
_QUESTIONNAIRE_BUDGET = _parameter(
    semantic_key="kirov_city_budget",
    name="Kirov city budget",
    description="Specific municipal budget reporting about Kirov.",
    instructions="Prefer coverage of the Kirov city budget.",
    weight="0.30",
    origin=PreferenceOrigin.QUESTIONNAIRE,
)

REVIEWED_SPECIFICITY_CASES = (
    ReviewedSpecificityCase(
        slug="create-specific-over-broad",
        statement="Please show me more Kirov city news.",
        profile=_profile(_BROAD_RUSSIA),
        proposal_change={
            "action": "create",
            "semantic_key": "kirov_city_news",
            "name": "Kirov city news",
            "description": "Specific city reporting about Kirov.",
            "evaluation_instructions": "Prefer relevant Kirov city reporting.",
            "target_weight": "0.80",
            "reason": "User explicitly asked for more Kirov city news.",
        },
        expected_specific_semantic_key="kirov_city_news",
        expected_actions=frozenset({"create"}),
    ),
    ReviewedSpecificityCase(
        slug="adjust-existing-specific-alongside-broad",
        statement="I want more Kirov city news coverage.",
        profile=_profile(_BROAD_RUSSIA, _SPECIFIC_KIROV),
        proposal_change={
            "action": "adjust",
            "parameter_id": _SPECIFIC_KIROV.id,
            "target_weight": "0.80",
            "reason": "User explicitly asked for more Kirov city news.",
        },
        expected_specific_semantic_key="kirov_city_news",
        expected_actions=frozenset({"adjust"}),
    ),
    ReviewedSpecificityCase(
        slug="reactivate-inactive-specific-equivalent",
        statement="Bring back Kirov city reporting for me.",
        profile=_profile(_BROAD_RUSSIA, _INACTIVE_KIROV),
        proposal_change={
            "action": "create",
            "semantic_key": "kirov_city_news",
            "name": "Kirov city news",
            "description": "Specific city reporting about Kirov.",
            "evaluation_instructions": "Prefer relevant Kirov city reporting.",
            "target_weight": "0.70",
            "reason": "User explicitly requested the same topic again.",
        },
        expected_specific_semantic_key="kirov_city_news",
        expected_actions=frozenset({"reactivate", "adjust"}),
        duplicate_matches=((0, _INACTIVE_KIROV.id),),
    ),
    ReviewedSpecificityCase(
        slug="refine-existing-system-specific",
        statement="Please focus Kirov transport coverage on municipal projects.",
        profile=_profile(_SYSTEM_TRANSPORT),
        proposal_change={
            "action": "refine",
            "parameter_id": _SYSTEM_TRANSPORT.id,
            "description": "Specific municipal transport reporting about Kirov projects.",
            "evaluation_instructions": "Prefer articles about Kirov municipal transport projects.",
            "reason": "User explicitly narrowed the Kirov transport topic.",
        },
        expected_specific_semantic_key="kirov_transport",
        expected_actions=frozenset({"refine"}),
    ),
    ReviewedSpecificityCase(
        slug="strengthen-questionnaire-specific",
        statement="I need more Kirov city budget reporting.",
        profile=_profile(_QUESTIONNAIRE_BUDGET),
        proposal_change={
            "action": "adjust",
            "parameter_id": _QUESTIONNAIRE_BUDGET.id,
            "target_weight": "0.75",
            "reason": "User explicitly asked for more Kirov city budget reporting.",
        },
        expected_specific_semantic_key="kirov_city_budget",
        expected_actions=frozenset({"adjust"}),
    ),
)

_EQUIVALENT_ACTIVE = _parameter(
    semantic_key="kirov_civic_news",
    name="Kirov civic news",
    description="Specific civic reporting about Kirov.",
    instructions="Prefer detailed Kirov civic reporting.",
    weight="0.45",
)
_EQUIVALENT_INACTIVE = _parameter(
    semantic_key="kirov_civic_news",
    name="Kirov civic news",
    description="Specific civic reporting about Kirov.",
    instructions="Prefer detailed Kirov civic reporting.",
    weight="0.35",
    active=False,
)
_EQUIVALENT_SYSTEM = _parameter(
    semantic_key="kirov_municipal_reporting",
    name="Kirov municipal reporting",
    description="Specific reporting about Kirov municipal affairs.",
    instructions="Prefer Kirov municipal affairs coverage.",
    weight="0.30",
    origin=PreferenceOrigin.SYSTEM,
)
_EQUIVALENT_ARTS = _parameter(
    semantic_key="kirov_arts_news",
    name="Kirov arts news",
    description="Specific arts and culture reporting from Kirov.",
    instructions="Prefer arts and culture reporting from Kirov.",
    weight="0.50",
)

REVIEWED_EQUIVALENCE_CASES = (
    ReviewedEquivalenceCase(
        slug="exact-key-active-adjust",
        statement="Please give me more Kirov civic news.",
        profile=_profile(_EQUIVALENT_ACTIVE),
        proposal_change={
            "action": "create",
            "semantic_key": "kirov_civic_news",
            "name": "Kirov civic news",
            "description": "Specific civic reporting about Kirov.",
            "evaluation_instructions": "Prefer detailed Kirov civic reporting.",
            "target_weight": "0.80",
            "reason": "User explicitly asked for more Kirov civic news.",
        },
        expected_actions=frozenset({"adjust"}),
        exact_match=True,
    ),
    ReviewedEquivalenceCase(
        slug="exact-key-inactive-reactivate",
        statement="Please bring back Kirov civic news.",
        profile=_profile(_EQUIVALENT_INACTIVE),
        proposal_change={
            "action": "create",
            "semantic_key": "kirov_civic_news",
            "name": "Kirov civic news",
            "description": "Specific civic reporting about Kirov.",
            "evaluation_instructions": "Prefer detailed Kirov civic reporting.",
            "target_weight": "0.70",
            "reason": "User explicitly asked for the same topic again.",
        },
        expected_actions=frozenset({"reactivate", "adjust"}),
        exact_match=True,
    ),
    ReviewedEquivalenceCase(
        slug="exact-name-refine",
        statement="Please refine my Kirov municipal reporting preference.",
        profile=_profile(_EQUIVALENT_SYSTEM),
        proposal_change={
            "action": "create",
            "semantic_key": "kirov_city_reporting",
            "name": "Kirov municipal reporting",
            "description": "Specific municipal governance reporting about Kirov.",
            "evaluation_instructions": "Prefer detailed Kirov municipal governance reporting.",
            "target_weight": "0.30",
            "reason": "User explicitly restated the same topic with narrower wording.",
        },
        expected_actions=frozenset({"refine"}),
        exact_match=True,
    ),
    ReviewedEquivalenceCase(
        slug="exact-name-reactivate-and-refine",
        statement="Please restore Kirov arts news with a stronger local focus.",
        profile=_profile(
            _parameter(
                semantic_key="kirov_arts_news",
                name="Kirov arts news",
                description="Specific arts and culture reporting from Kirov.",
                instructions="Prefer arts and culture reporting from Kirov.",
                weight="0.45",
                active=False,
            )
        ),
        proposal_change={
            "action": "create",
            "semantic_key": "kirov_arts_and_culture",
            "name": "Kirov arts news",
            "description": "Specific local arts and culture reporting from Kirov.",
            "evaluation_instructions": "Prefer local arts and culture reporting from Kirov.",
            "target_weight": "0.65",
            "reason": "User explicitly asked for the same topic again.",
        },
        expected_actions=frozenset({"reactivate", "adjust", "refine"}),
        exact_match=True,
    ),
    ReviewedEquivalenceCase(
        slug="reviewed-equivalent-municipal-briefing",
        statement="Please send more municipal briefings from Kirov.",
        profile=_profile(_EQUIVALENT_SYSTEM),
        proposal_change={
            "action": "create",
            "semantic_key": "kirov_city_briefings",
            "name": "Municipal briefings from Kirov",
            "description": "Specific Kirov municipal briefings and city governance coverage.",
            "evaluation_instructions": "Prefer Kirov municipal briefings and city governance coverage.",
            "target_weight": "0.60",
            "reason": "User explicitly asked for more Kirov municipal briefings.",
        },
        expected_actions=frozenset({"adjust", "refine"}),
        exact_match=False,
        duplicate_matches=((0, _EQUIVALENT_SYSTEM.id),),
    ),
    ReviewedEquivalenceCase(
        slug="reviewed-equivalent-civic-coverage",
        statement="Please prioritize civic coverage from Kirov again.",
        profile=_profile(_EQUIVALENT_ACTIVE),
        proposal_change={
            "action": "create",
            "semantic_key": "kirov_city_civic_coverage",
            "name": "Civic coverage from Kirov",
            "description": "Specific civic coverage from Kirov.",
            "evaluation_instructions": "Prefer civic coverage from Kirov.",
            "target_weight": "0.75",
            "reason": "User explicitly restated the same civic topic.",
        },
        expected_actions=frozenset({"adjust", "refine"}),
        exact_match=False,
        duplicate_matches=((0, _EQUIVALENT_ACTIVE.id),),
    ),
    ReviewedEquivalenceCase(
        slug="reviewed-equivalent-neighborhood-transport",
        statement="Please bring back neighborhood transport stories from Kirov.",
        profile=_profile(_SYSTEM_TRANSPORT),
        proposal_change={
            "action": "create",
            "semantic_key": "kirov_neighborhood_transport",
            "name": "Neighborhood transport stories from Kirov",
            "description": "Specific neighborhood transport reporting about Kirov.",
            "evaluation_instructions": "Prefer Kirov neighborhood transport stories.",
            "target_weight": "0.70",
            "reason": "User explicitly restated the same transport topic.",
        },
        expected_actions=frozenset({"adjust", "refine"}),
        exact_match=False,
        duplicate_matches=((0, _SYSTEM_TRANSPORT.id),),
    ),
    ReviewedEquivalenceCase(
        slug="reviewed-equivalent-arts-desk",
        statement="Please send more arts desk coverage from Kirov.",
        profile=_profile(_EQUIVALENT_ARTS),
        proposal_change={
            "action": "create",
            "semantic_key": "kirov_arts_desk",
            "name": "Arts desk coverage from Kirov",
            "description": "Specific arts desk coverage from Kirov.",
            "evaluation_instructions": "Prefer arts desk coverage from Kirov.",
            "target_weight": "0.80",
            "reason": "User explicitly restated the same arts topic.",
        },
        expected_actions=frozenset({"adjust", "refine"}),
        exact_match=False,
        duplicate_matches=((0, _EQUIVALENT_ARTS.id),),
    ),
)

__all__ = [
    "REVIEWED_EQUIVALENCE_CASES",
    "REVIEWED_SPECIFICITY_CASES",
    "ReviewedEquivalenceCase",
    "ReviewedSpecificityCase",
]
