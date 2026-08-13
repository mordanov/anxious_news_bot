from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from uuid import UUID

from anxious_news_bot.preferences.domain import PreferenceOrigin
from anxious_news_bot.ranking.domain import (
    ArticleEvaluation,
    EvaluationStatus,
    RankingArticleSnapshot,
    RankingConfiguration,
    RankingPreference,
    RankingRecord,
    SelectionOutcome,
    SelectionReason,
)
from anxious_news_bot.ranking.services.configuration import relaxation_vectors

ZERO = Decimal("0")
_CAP_REJECTION_REASONS = (
    SelectionReason.REJECTED_EVENT_CAP,
    SelectionReason.REJECTED_TOPIC_CAP,
    SelectionReason.REJECTED_SOURCE_CAP,
)
_MAX_REJECTION_SAMPLES = 10


@dataclass(frozen=True, slots=True)
class ExplicitSignalClassification:
    protected: bool
    veto: bool


@dataclass(frozen=True, slots=True)
class DiversityRejectionSummary:
    reason: SelectionReason
    count: int
    sample_article_ids: tuple[UUID, ...] = ()

    def __post_init__(self) -> None:
        if self.reason not in _CAP_REJECTION_REASONS:
            raise ValueError("rejection summary reason must be a cap rejection")
        if self.count < 0:
            raise ValueError("rejection count must be non-negative")


@dataclass(frozen=True, slots=True)
class DiversityPassSummary:
    pass_number: int
    cap_vector: tuple[int, int, int]
    selected_count: int
    rejections: tuple[DiversityRejectionSummary, ...] = ()
    reached_target: bool = False
    exhausted_pool: bool = False

    def __post_init__(self) -> None:
        if self.pass_number <= 0:
            raise ValueError("pass_number must be positive")
        if len(self.cap_vector) != 3 or any(value <= 0 for value in self.cap_vector):
            raise ValueError("cap_vector must contain three positive values")
        if self.selected_count < 0:
            raise ValueError("selected_count must be non-negative")


@dataclass(frozen=True, slots=True)
class DiversitySelection:
    records: tuple[RankingRecord, ...]
    passes: tuple[DiversityPassSummary, ...]
    selected_cap_vector: tuple[int, int, int]
    unsatisfied_limits: tuple[str, ...] = ()
    selected_pass: int = 1

    def __post_init__(self) -> None:
        if not self.passes:
            raise ValueError("passes must not be empty")
        if len(self.selected_cap_vector) != 3 or any(
            value <= 0 for value in self.selected_cap_vector
        ):
            raise ValueError("selected_cap_vector must contain three positive caps")
        if self.selected_pass <= 0:
            raise ValueError("selected_pass must be positive")


def _complete_relevance_map(
    evaluation: ArticleEvaluation | None,
    *,
    article_snapshot: RankingArticleSnapshot,
) -> dict[object, Decimal]:
    if evaluation is None or evaluation.status is not EvaluationStatus.COMPLETE:
        return {}
    if (
        evaluation.identity.article_id != article_snapshot.article_id
        or evaluation.identity.article_analysis_id
        != article_snapshot.article_analysis_id
    ):
        return {}
    return {item.parameter_id: item.relevance for item in evaluation.relevances}


def _explicit_alignment(
    preference: RankingPreference,
    relevance: Decimal,
) -> Decimal:
    return relevance if preference.weight >= ZERO else -relevance


def classify_explicit_signals(
    configuration: RankingConfiguration,
    preferences: Sequence[RankingPreference],
    evaluation: ArticleEvaluation | None,
    *,
    article_snapshot: RankingArticleSnapshot,
) -> ExplicitSignalClassification:
    evaluation_map = _complete_relevance_map(
        evaluation,
        article_snapshot=article_snapshot,
    )
    protected = False
    veto = False
    for preference in preferences:
        if not preference.active:
            continue
        if preference.effective_authority is not PreferenceOrigin.EXPLICIT:
            continue
        if abs(preference.weight) < configuration.explicit_weight_threshold:
            continue
        relevance = evaluation_map.get(preference.id)
        if relevance is None:
            continue
        alignment = _explicit_alignment(preference, relevance)
        if alignment <= -configuration.explicit_relevance_threshold:
            veto = True
        if alignment >= configuration.explicit_relevance_threshold:
            protected = True
    return ExplicitSignalClassification(
        protected=protected and not veto,
        veto=veto,
    )


class DeterministicDiversitySelector:
    def select(
        self,
        records: Sequence[RankingRecord],
        *,
        requested_count: int,
        configuration: RankingConfiguration,
    ) -> DiversitySelection:
        if requested_count <= 0:
            raise ValueError("requested_count must be positive")

        ordered_records = tuple(records)
        eligible_records = tuple(
            record for record in ordered_records if record.eligible
        )
        protected_records = tuple(
            record for record in eligible_records if record.explicit_protected
        )
        ordinary_records = tuple(
            record for record in eligible_records if not record.explicit_protected
        )
        candidate_groups = protected_records + ordinary_records
        vectors = relaxation_vectors(configuration)
        base_vector = vectors[0]
        pass_summaries: list[DiversityPassSummary] = []

        for pass_number, cap_vector in enumerate(vectors, start=1):
            selected_ids: list[UUID] = []
            selections: dict[UUID, SelectionOutcome] = {}
            event_counts: Counter[UUID] = Counter()
            topic_counts: Counter[str] = Counter()
            source_counts: Counter[UUID] = Counter()
            rejected_ids: dict[SelectionReason, list[UUID]] = {
                reason: [] for reason in _CAP_REJECTION_REASONS
            }

            for record in candidate_groups:
                if len(selected_ids) >= requested_count:
                    break
                rejection = _cap_rejection_reason(
                    record,
                    event_counts=event_counts,
                    topic_counts=topic_counts,
                    source_counts=source_counts,
                    cap_vector=cap_vector,
                )
                if rejection is not None:
                    rejected_ids[rejection].append(record.article_id)
                    selections[record.article_id] = SelectionOutcome(
                        selected=False,
                        reason=rejection,
                        explicit_protected=record.explicit_protected,
                    )
                    continue

                position = len(selected_ids) + 1
                selected_ids.append(record.article_id)
                _increment_counts(
                    record,
                    event_counts=event_counts,
                    topic_counts=topic_counts,
                    source_counts=source_counts,
                )
                selections[record.article_id] = SelectionOutcome(
                    selected=True,
                    reason=SelectionReason.SELECTED,
                    position=position,
                    explicit_protected=record.explicit_protected,
                    diversity_pass=pass_number,
                )

            reached_target = len(selected_ids) >= requested_count
            exhausted_pool = not reached_target and not any(rejected_ids.values())
            pass_summaries.append(
                DiversityPassSummary(
                    pass_number=pass_number,
                    cap_vector=cap_vector,
                    selected_count=len(selected_ids),
                    rejections=tuple(
                        DiversityRejectionSummary(
                            reason=reason,
                            count=len(rejected_ids[reason]),
                            sample_article_ids=tuple(
                                rejected_ids[reason][:_MAX_REJECTION_SAMPLES]
                            ),
                        )
                        for reason in _CAP_REJECTION_REASONS
                        if rejected_ids[reason]
                    ),
                    reached_target=reached_target,
                    exhausted_pool=exhausted_pool,
                )
            )
            is_last_vector = pass_number == len(vectors)
            if reached_target or exhausted_pool or is_last_vector:
                return DiversitySelection(
                    records=_finalize_records(ordered_records, selections),
                    passes=tuple(pass_summaries),
                    selected_cap_vector=cap_vector,
                    unsatisfied_limits=_unsatisfied_limits(base_vector, cap_vector),
                    selected_pass=pass_number,
                )

        raise AssertionError("diversity selection did not terminate")


def _cap_rejection_reason(
    record: RankingRecord,
    *,
    event_counts: Counter[UUID],
    topic_counts: Counter[str],
    source_counts: Counter[UUID],
    cap_vector: tuple[int, int, int],
) -> SelectionReason | None:
    event_cap, topic_cap, source_cap = cap_vector
    if (
        record.event_group_id is not None
        and event_counts[record.event_group_id] >= event_cap
    ):
        return SelectionReason.REJECTED_EVENT_CAP
    if record.topic_key is not None and topic_counts[record.topic_key] >= topic_cap:
        return SelectionReason.REJECTED_TOPIC_CAP
    if source_counts[record.source_id] >= source_cap:
        return SelectionReason.REJECTED_SOURCE_CAP
    return None


def _increment_counts(
    record: RankingRecord,
    *,
    event_counts: Counter[UUID],
    topic_counts: Counter[str],
    source_counts: Counter[UUID],
) -> None:
    if record.event_group_id is not None:
        event_counts[record.event_group_id] += 1
    if record.topic_key is not None:
        topic_counts[record.topic_key] += 1
    source_counts[record.source_id] += 1


def _finalize_records(
    records: tuple[RankingRecord, ...],
    selections: dict[UUID, SelectionOutcome],
) -> tuple[RankingRecord, ...]:
    finalized: list[RankingRecord] = []
    for record in records:
        if not record.eligible:
            selection = SelectionOutcome(
                selected=False,
                reason=SelectionReason.INELIGIBLE,
                explicit_protected=record.explicit_protected,
            )
        else:
            selection = selections.get(
                record.article_id,
                SelectionOutcome(
                    selected=False,
                    reason=SelectionReason.NOT_EVALUATED,
                    explicit_protected=record.explicit_protected,
                ),
            )
        finalized.append(replace(record, selection=selection))
    return tuple(finalized)


def _unsatisfied_limits(
    base_vector: tuple[int, int, int],
    selected_vector: tuple[int, int, int],
) -> tuple[str, ...]:
    base_event, base_topic, base_source = base_vector
    selected_event, selected_topic, selected_source = selected_vector
    unsatisfied: list[str] = []
    if selected_source != base_source:
        unsatisfied.append("source")
    if selected_topic != base_topic:
        unsatisfied.append("topic")
    if selected_event != base_event:
        unsatisfied.append("event")
    return tuple(unsatisfied)


__all__ = [
    "DeterministicDiversitySelector",
    "DiversityPassSummary",
    "DiversityRejectionSummary",
    "DiversitySelection",
    "ExplicitSignalClassification",
    "classify_explicit_signals",
]
