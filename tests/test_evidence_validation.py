import pytest
from app.domain.models import (
    BriefingObject,
    BriefingSource,
    CompanyEntity,
    CompanySnapshot,
    SmallTalk,
    DemandHypothesisDraft,
    score_hypothesis,
    Evidence,
)
from app.services.briefing_service import BriefingService
from app.core.exceptions import CitationIntegrityException


def test_confirm_fact_exact_excerpt_match_success():
    """Stage 1 raw verification + Stage 2 exact excerpt match fact confirmation success."""
    evidence = Evidence(
        evidence_id="E01",
        claim="테스트기업 강남 사옥 이전 완료 공시",
        publisher="금융감독원",
        url="https://dart.fss.or.kr/001",
        source_tier="A",
    )

    # Stage 1: Verify raw content
    evidence.verify_raw("금융감독원 전자공시: 테스트기업이 서울 강남구 소재 신사옥으로 이전을 완료했습니다.")
    assert evidence.status == "RAW_VERIFIED"
    assert evidence.is_confirmed_fact is False

    # Stage 2: Confirm fact with exact excerpt
    evidence.confirm_fact(
        target_claim="테스트기업 강남 사옥 이전 완료 공시",
        supporting_excerpt="테스트기업이 서울 강남구 소재 신사옥으로 이전을 완료했습니다.",
        verification_method="EXACT_EXCERPT_MATCH",
    )

    assert evidence.status == "FACT_CONFIRMED"
    assert evidence.is_confirmed_fact is True
    assert evidence.verification_record is not None
    assert evidence.verification_record.verification_method == "EXACT_EXCERPT_MATCH"
    assert evidence.verification_record.supporting_excerpt == "테스트기업이 서울 강남구 소재 신사옥으로 이전을 완료했습니다."
    assert evidence.verification_record.excerpt_found is True
    assert evidence.verification_record.claim_confirmed is True
    assert evidence.verification_record.review_decision == "APPROVED"


def test_briefing_source_exposes_only_confirmed_customer_fields():
    """확정 Evidence를 고객용 출처로 바꾸면 감사 필드가 노출되지 않는다."""
    evidence = Evidence(
        evidence_id="E09",
        claim="고객용 확인 사실",
        publisher="공식 출처",
        url="https://example.com/e09",
        source_tier="A",
    )
    evidence.verify_raw(evidence.claim)
    evidence.confirm_fact(
        target_claim=evidence.claim,
        supporting_excerpt=evidence.claim,
        verification_method="EXACT_EXCERPT_MATCH",
    )

    source = BriefingSource.from_evidence(evidence)

    assert set(source.model_dump()) == {
        "evidence_id",
        "claim",
        "publisher",
        "url",
        "published_at",
        "source_tier",
        "scope",
    }


def test_briefing_source_rejects_unconfirmed_evidence():
    """미확정 Evidence는 고객용 출처로 전환할 수 없다."""
    evidence = Evidence(
        evidence_id="E10",
        claim="미확정 사실",
        publisher="검색 출처",
        url="https://example.com/e10",
        source_tier="A",
    )

    with pytest.raises(ValueError, match="FACT_CONFIRMED"):
        BriefingSource.from_evidence(evidence)


def test_confirm_fact_rejects_excerpt_missing_from_verified_raw_content():
    """Case A: Excerpt not present in verified raw content raises ValueError."""
    evidence = Evidence(
        evidence_id="E02",
        claim="테스트기업 사옥 이전",
        publisher="테스트 출처",
        url="https://example.com/e02",
        source_tier="B",
    )
    evidence.verify_raw("테스트기업은 서울 사옥으로 이전했습니다.")

    with pytest.raises(ValueError, match="not found in verified raw content"):
        evidence.confirm_fact(
            target_claim="테스트기업 사옥 이전",
            supporting_excerpt="확인되지 않은 엉뚱한 문장",
            verification_method="EXACT_EXCERPT_MATCH",
        )

    # Status remains RAW_VERIFIED (unconfirmed)
    assert evidence.status == "RAW_VERIFIED"
    assert evidence.is_confirmed_fact is False


def test_confirm_fact_manual_review_creates_verification_record():
    """Case C: Manual review confirmation creates FactVerificationRecord."""
    evidence = Evidence(
        evidence_id="E03",
        claim="테스트기업 신규 사업장",
        publisher="테스트 출처",
        url="https://example.com/e03",
        source_tier="B",
    )

    evidence.confirm_fact(
        target_claim="테스트기업 신규 사업장",
        supporting_excerpt="원문을 사람이 확인함",
        verification_method="MANUAL_REVIEW",
        verified_by="reviewer-1",
        verification_notes="원문과 claim의 의미가 일치함",
    )

    assert evidence.status == "FACT_CONFIRMED"
    assert evidence.is_confirmed_fact is True
    assert evidence.verification_record is not None
    assert evidence.verification_record.verification_method == "MANUAL_REVIEW"
    assert evidence.verification_record.verified_by == "reviewer-1"


def test_manual_review_rejects_excerpt_that_does_not_support_claim():
    """원문 구절이 존재해도 claim을 지지하지 않으면 수동 검토 거절로 확정하지 않는다."""
    evidence = Evidence(
        evidence_id="E05",
        claim="테스트기업이 신규 공장을 가동함",
        publisher="테스트 출처",
        url="https://example.com/e05",
        source_tier="B",
    )
    evidence.verify_raw("테스트기업은 신규 사무실을 임차했습니다.")

    with pytest.raises(ValueError, match="rejected"):
        evidence.confirm_fact(
            target_claim="테스트기업이 신규 공장을 가동함",
            supporting_excerpt="테스트기업은 신규 사무실을 임차했습니다.",
            verification_method="MANUAL_REVIEW",
            verified_by="reviewer-2",
            verification_notes="구절은 원문에 있으나 공장 가동 claim을 지지하지 않음",
            review_decision="REJECTED",
        )

    assert evidence.status == "RAW_VERIFIED"
    assert evidence.verification_record is None


def test_manual_review_pending_does_not_promote_fact():
    """수동 검토가 PENDING이면 FACT_CONFIRMED로 승격하지 않는다."""
    evidence = Evidence(
        evidence_id="E06",
        claim="테스트기업 신규 사업",
        publisher="테스트 출처",
        url="https://example.com/e06",
        source_tier="B",
    )

    evidence.confirm_fact(
        target_claim="테스트기업의 사업이 확대됨",
        supporting_excerpt="사업 확대를 검토 중입니다.",
        verification_method="MANUAL_REVIEW",
        verified_by="reviewer-3",
        verification_notes="의역 claim은 추가 검토 필요",
        review_decision="PENDING",
    )

    assert evidence.status == "REVIEW_REQUIRED"
    assert evidence.is_confirmed_fact is False
    assert evidence.verification_record is not None
    assert evidence.verification_record.claim_confirmed is False


def test_confirm_fact_requires_raw_verified_or_manual_classified_state():
    """사실 확정은 RAW_VERIFIED 또는 수동 검토용 CLASSIFIED에서만 허용한다."""
    evidence = Evidence(
        evidence_id="E04",
        claim="테스트기업 확장",
        publisher="테스트 출처",
        url="https://example.com/e04",
        source_tier="B",
        status="RAW_SNIPPET",
    )

    with pytest.raises(ValueError, match="RAW_VERIFIED"):
        evidence.confirm_fact(
            target_claim="테스트기업 확장",
            supporting_excerpt="확장 원문",
            verification_method="EXACT_EXCERPT_MATCH",
        )


def test_detect_invalid_evidence_id_reference():
    """PRD Test 3: 존재하지 않는 'evidence_id' 참조 탐지 (E02/E99 누락 탐지)."""
    evidence = Evidence(
        evidence_id="E01",
        claim="공사 진행 중",
        publisher="보도자료",
        url="https://example.com/e01",
        source_tier="B",
    )
    evidence.verify_raw("공사 진행 중")
    evidence.confirm_fact(
        target_claim="공사 진행 중",
        supporting_excerpt="공사 진행 중",
        verification_method="EXACT_EXCERPT_MATCH",
    )
    from app.domain.models import BriefingSource
    valid_source = BriefingSource.from_evidence(evidence)

    draft_hyp = DemandHypothesisDraft(
        title="가설",
        reason="이유",
        reasoning_chain=["단계"],
        supporting_evidence=["E01", "E02"]  # E02 IS MISSING FROM SOURCES!
    )
    scored_hyp = score_hypothesis(draft_hyp, "MODERATE")

    briefing = BriefingObject(
        company=CompanyEntity(
            name="테스트",
            resolved_name="테스트 주식회사",
            entity_confidence="HIGH"
        ),
        company_snapshot=CompanySnapshot(
            summary="요약",
            evidence_ids=["E01"]
        ),
        small_talk=[
            SmallTalk(
                topic="주제",
                talking_point="소재",
                evidence_ids=["E01"]
            )
        ],
        demand_hypotheses=[scored_hyp],
        sources=[valid_source]  # ONLY E01 is present!
    )

    invalid_citations = briefing.validate_citations()
    assert len(invalid_citations) == 1
    assert "E02" in invalid_citations[0]


def test_briefing_service_citation_validation_raises():
    """Verify BriefingService.validate_briefing_citations raises CitationIntegrityException."""
    briefing = BriefingObject(
        company=CompanyEntity(name="A", resolved_name="A Corp", entity_confidence="HIGH"),
        company_snapshot=CompanySnapshot(summary="요약", evidence_ids=["E01"]),
        sources=[]
    )

    with pytest.raises(CitationIntegrityException) as exc_info:
        BriefingService.validate_briefing_citations(briefing)

    assert exc_info.value.error_code == "INVALID_CITATION"
    assert "invalid citation(s)" in exc_info.value.message


def test_supporting_evidence_missing_from_customer_sources_raises():
    """P4 가설이 sources에 없는 E02를 인용하면 citation 무결성 오류가 난다."""
    source = BriefingSource(
        evidence_id="E01",
        claim="확인된 사실",
        publisher="공식 출처",
        url="https://example.com/e01",
        source_tier="A",
    )
    hypothesis = score_hypothesis(
        DemandHypothesisDraft(
            title="가설",
            reason="근거",
            reasoning_chain=["FACT", "DEMAND"],
            supporting_evidence=["E02"],
        ),
        "WEAK",
    )
    briefing = BriefingObject(
        company=CompanyEntity(name="테스트", resolved_name="테스트", entity_confidence="HIGH"),
        company_snapshot=CompanySnapshot(summary="요약", evidence_ids=[]),
        demand_hypotheses=[hypothesis],
        sources=[source],
    )

    with pytest.raises(CitationIntegrityException, match="invalid citation"):
        BriefingService.validate_briefing_citations(briefing)


def test_exact_match_never_stores_human_reviewer_identity():
    """자동 일치 검증은 사람의 수동 승인으로 저장되지 않는다."""
    evidence = Evidence(
        evidence_id="E07",
        claim="자동 확인 사실",
        publisher="출처",
        url="https://example.com/e07",
        source_tier="A",
    )
    evidence.verify_raw(evidence.claim)
    evidence.confirm_fact(
        target_claim=evidence.claim,
        supporting_excerpt=evidence.claim,
        verification_method="EXACT_EXCERPT_MATCH",
        verified_by="human-reviewer",
    )

    assert evidence.verification_record is not None
    assert evidence.verification_record.verified_by == "SYSTEM_EXACT_MATCH"


def test_manual_review_requires_reviewer_and_notes():
    """수동 검토는 확인자와 검토 메모가 모두 필요하다."""
    evidence = Evidence(
        evidence_id="E08",
        claim="수동 확인 사실",
        publisher="출처",
        url="https://example.com/e08",
        source_tier="A",
    )

    with pytest.raises(ValueError, match="verified_by"):
        evidence.confirm_fact(
            target_claim=evidence.claim,
            supporting_excerpt="사람이 확인한 구절",
            verification_method="MANUAL_REVIEW",
            verification_notes="메모",
        )

    with pytest.raises(ValueError, match="verification_notes"):
        evidence.confirm_fact(
            target_claim=evidence.claim,
            supporting_excerpt="사람이 확인한 구절",
            verification_method="MANUAL_REVIEW",
            verified_by="reviewer",
        )


def test_evidence_broad_claim_replaced_by_approved_target_in_briefing_source():
    """Evidence.claim이 미승인 광범위 주장이더라도 confirm_fact로 승인된 target_claim(APPROVED_NARROW_FACT)으로만 BriefingSource가 생성되고, 미승인 claim은 고객용 출처 dump에 노출되지 않는다."""
    evidence = Evidence(
        evidence_id="E_APPROVED_TEST",
        claim="UNAPPROVED_BROAD_CLAIM",
        publisher="금융감독원",
        url="https://dart.fss.or.kr/999",
        source_tier="A",
    )
    evidence.verify_raw("원문 내용: APPROVED_NARROW_FACT 관련 세부 내용입니다.")
    evidence.confirm_fact(
        target_claim="APPROVED_NARROW_FACT",
        supporting_excerpt="APPROVED_NARROW_FACT",
        verification_method="EXACT_EXCERPT_MATCH",
    )

    source = BriefingSource.from_evidence(evidence)

    assert source.claim == "APPROVED_NARROW_FACT"
    source_dump = source.model_dump()
    assert source_dump["claim"] == "APPROVED_NARROW_FACT"
    assert "UNAPPROVED_BROAD_CLAIM" not in str(source_dump)
