import pytest

from app.domain.models import CompanyEntity, EvidencePack, SalesProfile
from app.domain.search_models import RawSearchItem
from app.domain.models import ProviderResult
from app.providers.mock import MockReasoningProvider
from app.services.briefing_composer import BriefingComposerService
from app.services.evidence_builder import EvidenceBuilder
from app.services.pipeline_services import (
    DemandReasonerService,
    ProfileCompilerService,
    RetrievalPlannerService,
)
from app.services.rule_engine import HypothesisScorer


class E2EBriefingProvider:
    def __init__(self, payload: dict):
        self.payload = payload

    async def generate_structured(self, **kwargs):
        return ProviderResult(
            provider="offline-e2e",
            requested_model=kwargs["model"],
            actual_model="offline-e2e",
            structured_data=self.payload,
        )


def _sales_profile() -> SalesProfile:
    return SalesProfile(
        company="테스트기업",
        industry="IT 솔루션",
        product_service="기업용 차량 관리 SaaS",
        target_customer="중견기업",
        sales_goal="신규 수주",
    )


def _company() -> CompanyEntity:
    return CompanyEntity(
        name="테스트기업",
        resolved_name="테스트기업 주식회사",
        entity_confidence="HIGH",
        industry="IT 솔루션",
    )


def _search_fixture() -> list[RawSearchItem]:
    return [
        RawSearchItem(
            item_id="search-1",
            query="테스트기업 사옥 이전 공시",
            title="테스트기업 신규 사업장 개설 공시",
            snippet="테스트기업은 서울 신규 사업장을 개설했습니다.",
            url="https://dart.fss.or.kr/example/001",
            publisher="금융감독원 전자공시",
            published_at="2026-09-01",
        ),
        RawSearchItem(
            item_id="search-2",
            query="테스트기업 채용 공고",
            title="테스트기업 하반기 영업 인력 채용",
            snippet="테스트기업은 하반기 영업 인력을 채용합니다.",
            url="https://www.mk.co.kr/news/example/002",
            publisher="매일경제",
            published_at="2026-09-10",
        ),
    ]


def _p4_payload(scored):
    return {
        "company_snapshot": {
            "summary": "테스트기업은 신규 사업장을 개설했습니다.\n영업 인력 채용도 확인됩니다.\n운영 확대 계획을 미팅에서 확인합니다.",
            "evidence_ids": ["E01", "E02"],
        },
        "small_talk": [
            {
                "topic": "신규 사업장",
                "talking_point": "신규 사업장 개설 계획을 여쭤봅니다.",
                "evidence_ids": ["E01"],
            }
        ],
        "demand_hypotheses": [scored.model_dump()],
        "meeting_questions": [
            "신규 사업장 운영 계획은 무엇인가요?",
            "영업 인력 확충의 우선 과제는 무엇인가요?",
            "차량 관리 운영 기준은 어떻게 정하고 계신가요?",
        ],
        "warnings": [],
    }


@pytest.mark.asyncio
async def test_offline_pipeline_runs_from_sales_profile_to_briefing_json():
    """명백한 fixture로 Sales Profile부터 P4 Briefing JSON까지 연결한다."""
    sales_profile = _sales_profile()
    company = _company()

    p1 = await ProfileCompilerService(MockReasoningProvider()).compile_profile(sales_profile, company)
    p2 = await RetrievalPlannerService(MockReasoningProvider()).plan_retrieval(p1)
    assert p1.company_name == "테스트기업"
    assert p2.search_queries

    evidence_pack = EvidenceBuilder.build_evidences("테스트기업", _search_fixture())
    for evidence in evidence_pack.evidences:
        evidence.verify_raw(f"원문: {evidence.claim}")
        evidence.confirm_fact(
            target_claim=evidence.claim,
            supporting_excerpt=evidence.claim,
            verification_method="EXACT_EXCERPT_MATCH",
        )

    p3_response = {
        "status": "SUCCESS",
        "drafts": [
            {
                "title": "확장에 따른 차량 관리 수요",
                "reason": "사업장 개설과 채용으로 운영 수요가 늘어날 가능성",
                "reasoning_chain": ["E01/E02 FACT", "운영 확대", "차량 관리 수요"],
                "supporting_evidence": ["E01", "E02"],
                "contradicting_evidence": [],
                "questions": ["차량 운영 계획은 무엇인가요?"],
                "status": "ACTIVE",
            }
        ],
        "reasoning_summary": "확정 FACT 기반 가설",
    }
    # P3Input은 strict 모델이므로 dict 경계에서 명시적으로 파싱한다.
    from app.domain.pipeline_models import P3Input
    p3 = await DemandReasonerService(MockReasoningProvider(default_response=p3_response)).reason_demand(
        P3Input(compiled_profile=p1, evidence_pack=evidence_pack)
    )
    scored = [HypothesisScorer().score_hypothesis(draft, evidence_pack) for draft in p3.drafts]
    briefing = await BriefingComposerService(E2EBriefingProvider(_p4_payload(scored[0]))).compose(
        company, evidence_pack, scored
    )

    source_ids = {source.evidence_id for source in briefing.sources}
    assert briefing.status == "SUCCESS"
    assert briefing.demand_hypotheses
    assert len(briefing.sources) == 2
    assert set(briefing.company_snapshot.evidence_ids) <= source_ids
    assert all(
        set(item.evidence_ids) <= source_ids for item in briefing.small_talk
    )
    assert all(
        set(hypothesis.supporting_evidence + hypothesis.contradicting_evidence) <= source_ids
        for hypothesis in briefing.demand_hypotheses
    )
    assert briefing.model_dump_json()


@pytest.mark.asyncio
async def test_offline_pipeline_returns_insufficient_briefing_without_confirmed_evidence():
    """검색 결과가 있어도 사실 확정이 없으면 빈 가설과 경고로 종료한다."""
    from app.domain.pipeline_models import CompiledProfile, P3Input
    from app.domain.models import Evidence

    profile = CompiledProfile(
        company_name="테스트기업",
        resolved_name="테스트기업 주식회사",
        industry="IT",
        product_service="SaaS",
        target_customer="기업",
        sales_goal="영업",
    )
    unconfirmed = Evidence(
        evidence_id="E01",
        claim="검색 스니펫",
        publisher="검색 출처",
        url="https://example.com/e01",
        source_tier="A",
    )
    pack = EvidencePack(company_name="테스트기업", evidences=[unconfirmed])
    p3 = await DemandReasonerService(MockReasoningProvider()).reason_demand(
        P3Input(compiled_profile=profile, evidence_pack=pack)
    )
    briefing = await BriefingComposerService(E2EBriefingProvider({})).compose(
        _company(), pack, []
    )

    assert p3.status == "INSUFFICIENT_EVIDENCE"
    assert p3.drafts == []
    assert briefing.demand_hypotheses == []
    assert briefing.sources == []
    assert briefing.warnings
