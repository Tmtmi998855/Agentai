"""확정 증거만으로 수요 가설 신호를 계산하는 V0 Rule Engine."""

from app.core.policy import SIGNAL_LEVEL_ORDER, V0_POLICY, RulePolicy
from app.domain.models import (
    DemandHypothesisDraft,
    Evidence,
    EvidencePack,
    ScoredDemandHypothesis,
    SignalLevel,
    score_hypothesis as transform_hypothesis,
)


class HypothesisScorer:
    """서버 정책으로만 DemandHypothesisDraft를 scored 모델로 변환한다."""

    def __init__(self, policy: RulePolicy = V0_POLICY):
        self.policy = policy

    def score_hypothesis(
        self,
        draft: DemandHypothesisDraft,
        evidence_pack: EvidencePack,
    ) -> ScoredDemandHypothesis:
        """확정되고 중복 제거된 근거를 계산해 최종 신호를 부여한다."""
        evidence_by_id = {e.evidence_id: e for e in evidence_pack.evidences}
        supporting = self._independent_confirmed(
            draft.supporting_evidence, evidence_by_id
        )
        contradicting = self._independent_confirmed(
            draft.contradicting_evidence, evidence_by_id
        )

        if not supporting:
            return transform_hypothesis(
                self._with_status(draft, "INSUFFICIENT_EVIDENCE"), "NONE"
            )

        score = sum(self.policy.tier_weights[e.source_tier] for e in supporting)
        score -= self.policy.contradiction_penalty * len(contradicting)
        level = self._level_for_score(score)
        if all(e.source_tier == "C" for e in supporting):
            level = self._cap_level(level, self.policy.tier_c_max_level)

        return transform_hypothesis(draft, level)

    def _independent_confirmed(
        self,
        evidence_ids: list[str],
        evidence_by_id: dict[str, Evidence],
    ) -> list[Evidence]:
        selected: dict[str, Evidence] = {}
        for evidence_id in evidence_ids:
            evidence = evidence_by_id.get(evidence_id)
            if evidence is None or not evidence.is_confirmed_fact:
                continue
            group_key = evidence.duplicate_group_id or evidence.evidence_id
            current = selected.get(group_key)
            if current is None or self._evidence_rank(evidence) > self._evidence_rank(current):
                selected[group_key] = evidence
        return list(selected.values())

    def _evidence_rank(self, evidence: Evidence) -> tuple[int, int, str]:
        return (
            self.policy.tier_weights[evidence.source_tier],
            int(evidence.published_at is not None),
            evidence.published_at or "",
        )

    def _level_for_score(self, score: int) -> SignalLevel:
        if score >= self.policy.very_strong_min_score:
            return "VERY_STRONG"
        if score >= self.policy.strong_min_score:
            return "STRONG"
        if score >= self.policy.moderate_min_score:
            return "MODERATE"
        if score >= self.policy.weak_min_score:
            return "WEAK"
        return "NONE"

    def _cap_level(self, level: SignalLevel, maximum: SignalLevel) -> SignalLevel:
        return SIGNAL_LEVEL_ORDER[
            min(SIGNAL_LEVEL_ORDER.index(level), SIGNAL_LEVEL_ORDER.index(maximum))
        ]

    def _with_status(
        self,
        draft: DemandHypothesisDraft,
        status: str,
    ) -> DemandHypothesisDraft:
        data = draft.model_dump()
        data["status"] = status
        return DemandHypothesisDraft(**data)


def score_hypothesis(
    draft: DemandHypothesisDraft,
    evidence_pack: EvidencePack,
) -> ScoredDemandHypothesis:
    """V0 정책으로만 서버 점수화를 수행하는 공개 진입점."""
    return HypothesisScorer().score_hypothesis(draft, evidence_pack)
