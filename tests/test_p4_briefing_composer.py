import pytest

from app.core.exceptions import CitationIntegrityException, ProviderAuthException, ProviderException
from app.domain.models import (
    CompanyEntity,
    DemandHypothesisDraft,
    Evidence,
    EvidencePack,
    score_hypothesis,
)
from app.domain.models import ProviderResult
from app.services.briefing_composer import BriefingComposerService
from app.providers.mock import MockReasoningProvider


class StaticProvider:
    def __init__(self, response: dict):
        self.response = response

    async def generate_structured(self, **kwargs):
        return ProviderResult(
            provider="test",
            requested_model=kwargs["model"],
            actual_model="test",
            structured_data=self.response,
        )


def _fact() -> Evidence:
    evidence = Evidence(
        evidence_id="E01",
        claim="테스트기업이 신규 사업장을 개설했다",
        publisher="공식 공시",
        url="https://example.com/e01",
        source_tier="A",
        published_at="2026-09-01",
    )
    evidence.verify_raw(evidence.claim)
    evidence.confirm_fact(
        target_claim=evidence.claim,
        supporting_excerpt=evidence.claim,
        verification_method="EXACT_EXCERPT_MATCH",
    )
    return evidence


def _company() -> CompanyEntity:
    return CompanyEntity(
        name="테스트기업",
        resolved_name="테스트기업 주식회사",
        entity_confidence="HIGH",
    )


from app.services.rule_engine import HypothesisScorer


def _scored(evidence: Evidence):
    draft = DemandHypothesisDraft(
        title="사업장 운영 솔루션 수요",
        reason="신규 사업장 운영 변화 가능성",
        reasoning_chain=["FACT", "INTERPRETATION", "DEMAND"],
        supporting_evidence=[evidence.evidence_id],
        questions=["운영 계획은 어떻게 되나요?"],
    )
    return HypothesisScorer().score_hypothesis(draft, EvidencePack(company_name="테스트기업", evidences=[evidence]))


def _payload(hypothesis):
    return {
        "company_snapshot": {
            "summary": "테스트기업은 신규 사업장을 개설했습니다.\n공식 공시에서 사업 변화를 확인했습니다.\n추가 운영 계획 확인이 필요합니다.",
            "evidence_ids": ["E01"],
        },
        "small_talk": [
            {
                "topic": "신규 사업장 개설",
                "talking_point": "신규 사업장 운영 계획을 여쭤봅니다.",
                "evidence_ids": ["E01"],
            }
        ],
        "demand_hypotheses": [hypothesis.model_dump()],
        "meeting_questions": ["운영 계획은 무엇인가요?", "가장 큰 과제는 무엇인가요?", "일정은 어떻게 되나요?"],
        "warnings": [],
    }


@pytest.mark.asyncio
async def test_p4_composer_keeps_sources_and_server_signal_unchanged():
    """P4는 기존 FACT source와 Rule Engine signal을 그대로 조립한다."""
    evidence = _fact()
    scored = _scored(evidence)
    service = BriefingComposerService(StaticProvider(_payload(scored)))

    briefing = await service.compose(_company(), EvidencePack(company_name="테스트기업", evidences=[evidence]), [scored])

    assert briefing.status == "SUCCESS"
    assert briefing.sources[0].evidence_id == "E01"
    assert briefing.sources[0].source_tier == "A"
    assert set(briefing.sources[0].model_dump()) == {
        "evidence_id",
        "claim",
        "publisher",
        "url",
        "published_at",
        "source_tier",
        "scope",
    }
    assert briefing.sources[0].claim == evidence.claim
    # BriefingSource does not expose internal audit fields (verified_raw_content, verification_record, etc.)
    assert not hasattr(briefing.sources[0], "verified_raw_content")
    assert briefing.demand_hypotheses[0].signal_level == scored.signal_level
    assert len(briefing.meeting_questions) == 3


@pytest.mark.asyncio
async def test_p4_composer_returns_entity_ambiguous_when_confidence_is_low():
    """entity_confidence == LOW인 경우 ENTITY_AMBIGUOUS 상태와 경고를 반환한다."""
    company_low = CompanyEntity(
        name="모호한기업",
        resolved_name="모호한기업 주식회사",
        entity_confidence="LOW"
    )
    evidence = _fact()
    scored = _scored(evidence)
    service = BriefingComposerService(StaticProvider({}))

    briefing = await service.compose(company_low, EvidencePack(company_name="모호한기업", evidences=[evidence]), [scored])

    assert briefing.status == "ENTITY_AMBIGUOUS"
    assert len(briefing.demand_hypotheses) == 0
    assert len(briefing.sources) == 0
    assert "기업 식별 신뢰도가 낮습니다" in briefing.warnings[0]


@pytest.mark.asyncio
async def test_p4_composer_rejects_changed_hypothesis_signal():
    """P4가 가설이나 신호등급을 변경하면 CitationIntegrityException을 낸다."""
    evidence = _fact()
    scored = _scored(evidence)
    changed_payload = _payload(scored)
    changed_payload["demand_hypotheses"][0]["signal_level"] = "VERY_STRONG"
    service = BriefingComposerService(StaticProvider(changed_payload))

    with pytest.raises(CitationIntegrityException, match="changed a demand hypothesis"):
        await service.compose(_company(), EvidencePack(company_name="테스트기업", evidences=[evidence]), [scored])


@pytest.mark.asyncio
async def test_p4_composer_returns_empty_hypotheses_with_warning_when_evidence_is_insufficient():
    """확정 근거가 없으면 provider 호출 없이 빈 가설과 경고를 반환한다."""
    service = BriefingComposerService(StaticProvider({}))
    briefing = await service.compose(
        _company(),
        EvidencePack(company_name="테스트기업", evidences=[]),
        [],
    )

    assert briefing.demand_hypotheses == []
    assert briefing.sources == []
    assert briefing.status == "INSUFFICIENT_EVIDENCE"
    assert briefing.warnings
    assert 3 <= len(briefing.meeting_questions) <= 5


@pytest.mark.asyncio
async def test_p4_composer_distinguishes_ambiguous_entity_from_insufficient_evidence():
    """LOW confidence 엔티티는 근거 부족과 다른 상태와 경고로 반환한다."""
    service = BriefingComposerService(StaticProvider({}))
    briefing = await service.compose(
        CompanyEntity(
            name="테스트기업",
            resolved_name="후보 법인 A",
            entity_confidence="LOW",
        ),
        EvidencePack(company_name="테스트기업", evidences=[]),
        [],
    )

    assert briefing.status == "ENTITY_AMBIGUOUS"
    assert briefing.status != "INSUFFICIENT_EVIDENCE"
    assert "후보 법인을 선택" in briefing.warnings[0]
    assert "후보 법인 A" not in briefing.company_snapshot.summary


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error_code", "expected_exception"),
    [
        ("PROVIDER_AUTH_ERROR", ProviderAuthException),
        ("PROVIDER_BAD_REQUEST", ProviderException),
    ],
)
async def test_p4_provider_failure_uses_code_not_message(error_code, expected_exception):
    evidence = _fact()
    provider = MockReasoningProvider(
        simulate_error=True, error_code=error_code, error_message="upstream 401",
    )
    service = BriefingComposerService(provider)

    with pytest.raises(expected_exception) as error:
        await service.compose(_company(), EvidencePack(company_name="테스트기업", evidences=[evidence]), [])

    assert error.value.error_code == error_code


@pytest.mark.asyncio
async def test_p4_missing_structured_output_is_provider_error():
    evidence = _fact()
    service = BriefingComposerService(StaticProvider({}))

    with pytest.raises(ProviderException) as error:
        await service.compose(_company(), EvidencePack(company_name="테스트기업", evidences=[evidence]), [])

    assert error.value.error_code == "STRUCTURED_OUTPUT_MISSING"


@pytest.mark.asyncio
async def test_p4_invalid_structured_output_is_provider_error():
    evidence = _fact()
    service = BriefingComposerService(StaticProvider({"unexpected": "value"}))

    with pytest.raises(ProviderException) as error:
        await service.compose(_company(), EvidencePack(company_name="테스트기업", evidences=[evidence]), [])

    assert error.value.error_code == "PROVIDER_INVALID_JSON"
