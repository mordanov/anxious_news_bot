from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def generated_questionnaire() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "questions": [
            {
                "ordinal": ordinal,
                "dimension_key": f"dimension_{ordinal}",
                "text": f"Which coverage style do you prefer for topic {ordinal}?",
                "options": [
                    {"ordinal": option, "label": f"Preference {option}"}
                    for option in range(1, 5)
                ],
            }
            for ordinal in range(1, 11)
        ],
    }


class FixedClock:
    value = datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self.value


class FakeModel:
    def __init__(
        self,
        questionnaire: dict[str, Any],
        proposal: dict[str, Any] | None = None,
    ) -> None:
        self.questionnaire = questionnaire
        self.proposal = proposal
        self.context = None

    async def generate(self, context):
        self.context = context
        return self.questionnaire

    async def propose(self, profile, questionnaire_id, answers):
        del profile, questionnaire_id, answers
        if self.proposal is None:
            raise RuntimeError("no proposal configured")
        return self.proposal

    async def classify(self, proposal, candidates):
        del proposal, candidates
        return {
            "schema_version": "1.0",
            "outcome": "distinct",
            "candidate_parameter_id": None,
            "confidence": 1.0,
            "reason": "Distinct dimension",
        }
