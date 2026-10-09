import pytest
from pydantic import ValidationError
from app.domain.models import (
    SalesProfile,
    CompanyEntity,
    Evidence,
    DemandHypothesisDraft,
    ScoredDemandHypothesis,
    score_hypothesis,
)


def test_valid_domain_models():
    """PRD Test 1: 핵심 Pydantic 모델 정상 입력."""
    profile = SalesProfile(
        company="틈트미",
        industry="B2B SaaS",
        product_service="영업 미팅 브리핑 솔루션",
        target_customer="B2B 영업팀",
        sales_goal="신규 고객사 미팅 준비 시간 단축"
    )
    assert profile.company == "틈트미"

    entity = CompanyEntity(
        name="현대렌탈",
        resolved_name="현대렌탈케어 주식회사",
        entity_confidence="HIGH",
        website="https://example.com",
        industry="렌탈 서비스",
        region="서울"
    )
    assert entity.entity_confidence == "HIGH"

    evidence = Evidence(
        evidence_id="E01",
        claim="신규 사옥 확전 공시",
        publisher="금융감독원",
        url="https://dart.fss.or.kr",
        source_tier="A"
    )
    assert evidence.evidence_id == "E01"


def test_missing_required_fields_fails():
    """PRD Test 2: 필수 필드 누락 시 검증 실패."""
    with pytest.raises(ValidationError):
        SalesProfile(
            product_service="솔루션",
            target_customer="고객",
            sales_goal="목표"
        )

    with pytest.raises(ValidationError):
        CompanyEntity(name="테스트")


def test_fact_and_hypothesis_separation():
    """PRD Test 4: FACT와 HYPOTHESIS 구조 분리."""
    evidence = Evidence(
        evidence_id="E01",
        claim="테스트기업 2026년 3분기 공장 신축 공시",
        publisher="공시시스템",
        url="https://example.com/e01",
        source_tier="A"
    )

    draft = DemandHypothesisDraft(
        title="생산 설비 및 운송 차량 추가 수요",
        reason="공장 신축에 따른 물류 이동 증가 가능성",
        reasoning_chain=["공장 신축 공시 (FACT)", "운영 물류 증가 예상 (INTERPRETATION)", "차량 수요 발생 가설 (DEMAND)"],
        supporting_evidence=["E01"],
        contradicting_evidence=[],
        questions=["신규 공장 가동에 따라 운송 차량 라인업 조정 계획이 있으신가요?"]
    )

    assert evidence.source_tier == "A"
    assert draft.supporting_evidence == ["E01"]
    assert not hasattr(draft, "signal_level") or "signal_level" not in draft.model_fields


def test_strict_extra_fields_forbidden():
    """Verify that extra undefined fields raise ValidationError (strict validation)."""
    with pytest.raises(ValidationError):
        SalesProfile(
            company="틈트미",
            industry="IT",
            product_service="SaaS",
            target_customer="B2B",
            sales_goal="성장",
            unknown_extra_field="invalid"
        )


def test_llm_draft_with_signal_level_raises_validation_error():
    """A-2 Requirement: LLM 초안에 'signal_level'을 넣으면 extra='forbid'로 인해 ValidationError 발생."""
    with pytest.raises(ValidationError):
        DemandHypothesisDraft(
            title="가설",
            reason="이유",
            reasoning_chain=["단계1"],
            supporting_evidence=["E01"],
            signal_level="VERY_STRONG"  # Forbidden extra field for Draft!
        )


def test_scored_hypothesis_requires_signal_level_and_explicit_transform():
    """A-2 Requirement: Scored 모델은 signal_level 필수 & Draft -> Scored 명시적 전환."""
    draft = DemandHypothesisDraft(
        title="가설",
        reason="이유",
        reasoning_chain=["단계1"],
        supporting_evidence=["E01"]
    )

    # Scored model requires signal_level
    with pytest.raises(ValidationError):
        ScoredDemandHypothesis(
            title="가설",
            reason="이유",
            reasoning_chain=["단계1"],
            supporting_evidence=["E01"]
        )

    # Explicit server transformation
    scored = score_hypothesis(draft, "STRONG")
    assert scored.signal_level == "STRONG"
    assert scored.title == draft.title


def test_evidence_duplicate_and_conflict_check():
    """Verify detection of duplicate evidence_ids and supporting/contradicting conflict."""
    with pytest.raises(ValidationError, match="Duplicate evidence_id"):
        DemandHypothesisDraft(
            title="가설",
            reason="이유",
            reasoning_chain=["단계"],
            supporting_evidence=["E01", "E01"]
        )

    with pytest.raises(ValidationError, match="Conflict"):
        DemandHypothesisDraft(
            title="가설",
            reason="이유",
            reasoning_chain=["단계"],
            supporting_evidence=["E01"],
            contradicting_evidence=["E01"]
        )
