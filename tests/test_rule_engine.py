import pytest

from app.domain.models import DemandHypothesisDraft, Evidence, EvidencePack
from app.services.rule_engine import HypothesisScorer, score_hypothesis


def _confirmed(
    evidence_id: str,
    tier: str = "B",
    group: str | None = None,
    published_at: str | None = "2026-09-01",
) -> Evidence:
    evidence = Evidence(
        evidence_id=evidence_id,
        claim=f"확정 사실 {evidence_id}",
        publisher="공식 출처",
        url=f"https://example.com/{evidence_id}",
        source_tier=tier,
        duplicate_group_id=group,
        published_at=published_at,
    )
    evidence.verify_raw(evidence.claim)
    evidence.confirm_fact(
        target_claim=evidence.claim,
        supporting_excerpt=evidence.claim,
        verification_method="EXACT_EXCERPT_MATCH",
    )
    return evidence


def _draft(
    supporting: list[str],
    contradicting: list[str] | None = None,
) -> DemandHypothesisDraft:
    return DemandHypothesisDraft(
        title="수요 가설",
        reason="확정 사실에 기반한 가설",
        reasoning_chain=["FACT", "INTERPRETATION", "DEMAND"],
        supporting_evidence=supporting,
        contradicting_evidence=contradicting or [],
    )


def test_rule_engine_ignores_unconfirmed_evidence_and_marks_insufficient():
    """확정 FACT가 없으면 신호 없음과 근거 부족을 함께 구분한다."""
    evidence = Evidence(
        evidence_id="E01",
        claim="미확정 사실",
        publisher="출처",
        url="https://example.com/e01",
        source_tier="A",
    )

    scored = score_hypothesis(
        _draft(["E01"]), EvidencePack(company_name="테스트", evidences=[evidence])
    )

    assert scored.signal_level == "NONE"
    assert scored.status == "INSUFFICIENT_EVIDENCE"


def test_rule_engine_deduplicates_duplicate_group_as_one_independent_source():
    """같은 duplicate_group_id의 여러 기사는 하나의 독립 근거로 계산한다."""
    pack = EvidencePack(
        company_name="테스트",
        evidences=[
            _confirmed("E01", "B", "grp-1"),
            _confirmed("E02", "B", "grp-1"),
            _confirmed("E03", "B", "grp-2"),
        ],
    )

    scored = HypothesisScorer().score_hypothesis(_draft(["E01", "E02", "E03"]), pack)

    assert scored.signal_level == "MODERATE"
    assert scored.status == "ACTIVE"


def test_rule_engine_caps_tier_c_only_hypothesis_at_moderate():
    """Tier C만으로는 STRONG 이상을 부여하지 않는다."""
    pack = EvidencePack(
        company_name="테스트",
        evidences=[
            _confirmed("E01", "C", "grp-1"),
            _confirmed("E02", "C", "grp-2"),
            _confirmed("E03", "C", "grp-3"),
            _confirmed("E04", "C", "grp-4"),
        ],
    )

    scored = score_hypothesis(_draft(["E01", "E02", "E03", "E04"]), pack)

    assert scored.signal_level == "MODERATE"


def test_rule_engine_contradicting_fact_reduces_signal_level():
    """확정 반대 근거는 계산 점수를 감점한다."""
    pack = EvidencePack(
        company_name="테스트",
        evidences=[
            _confirmed("E01", "A"),
            _confirmed("E02", "B"),
            _confirmed("E03", "A"),
        ],
    )

    scored = score_hypothesis(_draft(["E01", "E02"], ["E03"]), pack)

    assert scored.signal_level == "MODERATE"


def test_rule_engine_distinguishes_low_signal_from_insufficient_evidence():
    """확정 근거가 있으나 반대 근거로 점수가 0이면 ACTIVE/NONE으로 구분한다."""
    pack = EvidencePack(
        company_name="테스트",
        evidences=[_confirmed("E01", "B"), _confirmed("E02", "A")],
    )

    scored = score_hypothesis(_draft(["E01"], ["E02"]), pack)

    assert scored.signal_level == "NONE"
    assert scored.status == "ACTIVE"


def test_rule_engine_missing_published_at_gets_no_recency_bonus():
    """published_at이 없는 FACT는 최신성 판단에 사용되지 않는다."""
    pack = EvidencePack(
        company_name="테스트",
        evidences=[
            _confirmed("E01", "B", published_at=None),
            _confirmed("E02", "B", published_at=None),
        ],
    )

    scored = score_hypothesis(_draft(["E01", "E02"]), pack)

    assert scored.signal_level == "MODERATE"
