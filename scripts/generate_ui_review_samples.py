"""
오프라인 UI/UX 검토용 JSON 샘플 생성 스크립트.

기존 서비스, Pydantic 도메인 모델, Mock/가상 fixture를 활용하여
docs/ui-review/samples/ 디렉터리에 UI 검토용 표준 JSON 파일 6종 및 manifest.json을 생성한다.

산출물:
- success.json (BriefingObject, HTTP 200 OK)
- insufficient_evidence.json (BriefingObject, HTTP 200 OK)
- entity_ambiguous.json (BriefingObject, HTTP 200 OK)
- provider_auth_error.json (ErrorResponse, HTTP 502 Bad Gateway)
- provider_timeout.json (ErrorResponse, HTTP 504 Gateway Timeout)
- invalid_citation.json (ErrorResponse, HTTP 422 Unprocessable Entity)
- manifest.json (오프라인 가상 Provenance 및 PRD 해시 정보)
"""

import asyncio
import json
from pathlib import Path

from fastapi import Request

from app.core.exceptions import (
    CitationIntegrityException,
    ProviderAuthException,
    ProviderTimeoutException,
)
from app.domain.models import (
    CompanyEntity,
    ErrorResponse,
    EvidencePack,
    ProviderResult,
    SalesProfile,
    BriefingObject,
)
from app.domain.pipeline_models import P3Input
from app.domain.search_models import RawSearchItem
from app.main import ah_there_exception_handler
from app.providers.mock import MockReasoningProvider
from app.services.briefing_composer import BriefingComposerService
from app.services.evidence_builder import EvidenceBuilder
from app.services.pipeline_services import (
    DemandReasonerService,
    ProfileCompilerService,
    RetrievalPlannerService,
)
from app.services.rule_engine import HypothesisScorer


class SampleBriefingProvider:
    """오프라인 샘플 데이터 생성을 위한 Mock ReasoningProvider."""

    def __init__(self, payload: dict):
        self.payload = payload

    async def generate_structured(self, **kwargs):
        return ProviderResult(
            provider="offline-sample-generator",
            requested_model=kwargs.get("model", "mock-model"),
            actual_model="offline-sample-generator",
            structured_data=self.payload,
        )


def _sales_profile() -> SalesProfile:
    return SalesProfile(
        company="가상솔루션",
        industry="IT/SaaS",
        product_service="기업용 차량 관리 SaaS",
        target_customer="중견/대기업",
        sales_goal="법인 차량 관리 솔루션 제안",
    )


def _company_high() -> CompanyEntity:
    return CompanyEntity(
        name="가상테스트고객A",
        resolved_name="가상테스트고객A 주식회사",
        entity_confidence="HIGH",
        industry="장기렌탈업",
        region="서울",
    )


def _company_low() -> CompanyEntity:
    return CompanyEntity(
        name="가상테스트고객B",
        resolved_name=None,
        entity_confidence="LOW",
        candidate_entities=["가상테스트고객B 알파 주식회사", "가상테스트고객B 베타 주식회사"],
        industry="제조/유통",
        region="부산",
    )


def _search_fixtures() -> list[RawSearchItem]:
    return [
        RawSearchItem(
            item_id="search-1",
            query="가상테스트고객A 신규 사옥 이전 공시",
            title="가상테스트고객A 강남 신사옥 이전 및 사업장 확장 공시",
            snippet="가상테스트고객A는 사업 확장을 위해 강남 신사옥 이전을 완료했습니다.",
            url="https://dart.example.com/001",
            publisher="가상 전자공시시스템",
            published_at="2026-09-01",
        ),
        RawSearchItem(
            item_id="search-2",
            query="가상테스트고객A 영업 채용 공고",
            title="가상테스트고객A 하반기 영업/기획 인력 대규모 채용",
            snippet="가상테스트고객A는 하반기 영업 및 사업 기획 인력을 대규모 채용 중입니다.",
            url="https://news.example.com/002",
            publisher="가상 경제뉴스",
            published_at="2026-09-10",
        ),
    ]


async def generate_samples(output_dir: Path | str | None = None) -> dict[str, str]:
    if output_dir is None:
        target_dir = Path(__file__).resolve().parent.parent / "docs" / "ui-review" / "samples"
    else:
        target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    results = {}

    sales_profile = _sales_profile()
    company_high = _company_high()

    # P1 및 P2 명시적 가상 fixture 주입을 통한 입력 유지
    p1_payload = {
        "version": "1.0.0",
        "company_name": company_high.name,
        "resolved_name": company_high.resolved_name,
        "industry": company_high.industry,
        "product_service": sales_profile.product_service,
        "target_customer": sales_profile.target_customer,
        "sales_goal": sales_profile.sales_goal,
        "focus_topics": ["사옥 이전", "채용 확대"],
        "compiled_at": "2026-09-22T00:00:00Z",
    }
    p1 = await ProfileCompilerService(
        SampleBriefingProvider(p1_payload)
    ).compile_profile(sales_profile, company_high)

    p2_payload = {
        "version": "1.0.0",
        "company_name": company_high.name,
        "approved_topics": ["사옥 이전", "채용 확대"],
        "search_queries": [
            {"query": f"{company_high.name} 사옥 이전 공시", "max_results": 5},
            {"query": f"{company_high.name} 영업 채용 공고", "max_results": 5},
        ],
        "planned_at": "2026-09-22T00:00:00Z",
    }
    p2 = await RetrievalPlannerService(
        SampleBriefingProvider(p2_payload)
    ).plan_retrieval(p1)
    assert p1.company_name == p2.company_name == company_high.name

    # 1. SUCCESS Briefing Sample
    evidence_pack = EvidenceBuilder.build_evidences(company_high.name, _search_fixtures())
    for ev in evidence_pack.evidences:
        if "REVIEW_REQUIRED" in ev.relevance_tags:
            ev.relevance_tags.remove("REVIEW_REQUIRED")
        ev.status = "RAW_VERIFIED"
        ev.verify_raw(f"가상 원문: {ev.claim}")
        ev.confirm_fact(
            target_claim=ev.claim,
            supporting_excerpt=ev.claim,
            verification_method="EXACT_EXCERPT_MATCH",
        )

    p3_response = {
        "status": "SUCCESS",
        "drafts": [
            {
                "title": "사옥 이전 및 채용 확대에 따른 업무용 차량 관리 수요",
                "reason": f"{company_high.name}의 강남 신사옥 이전과 영업 인력 채용으로 업무 이동용 차량 관리 솔루션 수요 가능성",
                "reasoning_chain": [
                    "E01 FACT: 강남 신사옥 이전 공시",
                    "E02 FACT: 영업 인력 채용 보도",
                    "인력 이동 및 Fleet 관리 솔루션 수요 도출",
                ],
                "supporting_evidence": ["E01", "E02"],
                "contradicting_evidence": [],
                "questions": ["신규 사옥 이전 후 직원 외근 차량 관리 체계가 수립되었나요?"],
                "status": "ACTIVE",
            }
        ],
        "reasoning_summary": "확정 FACT 2건 기반 수요 가설 도출 완료",
    }

    p3_output = await DemandReasonerService(
        MockReasoningProvider(default_response=p3_response)
    ).reason_demand(P3Input(compiled_profile=p1, evidence_pack=evidence_pack))

    scored_hypotheses = [
        HypothesisScorer().score_hypothesis(draft, evidence_pack) for draft in p3_output.drafts
    ]

    p4_payload = {
        "company_snapshot": {
            "summary": (
                f"{company_high.name}은 강남 신사옥 이전을 완료하고 하반기 영업 인력을 채용 중입니다.\n"
                "사업장 확장과 인력 증원이 함께 진행되는 시점입니다.\n"
                "미팅에서 업무 이동 및 차량 관리 운용 계획을 확인할 수 있습니다."
            ),
            "evidence_ids": ["E01", "E02"],
        },
        "small_talk": [
            {
                "topic": "신사옥 이전 축하",
                "talking_point": "최근 강남 신사옥 이전을 축하드립니다.",
                "evidence_ids": ["E01"],
            }
        ],
        "demand_hypotheses": [scored_hypotheses[0].model_dump()],
        "meeting_questions": [
            "신규 사옥 이전 이후 직원분들의 업무용 이동수단 관리는 어떻게 진행하고 계신가요?",
            "하반기 채용 인력 증가에 맞춘 Fleet 확장 계획이 있으신가요?",
            "현재 차량 관리 시 가장 큰 페인포인트는 무엇인가요?",
        ],
        "warnings": [],
    }

    briefing_success = await BriefingComposerService(
        SampleBriefingProvider(p4_payload)
    ).compose(company_high, evidence_pack, scored_hypotheses)

    success_json = json.dumps(briefing_success.model_dump(), indent=2, ensure_ascii=False)
    BriefingObject.model_validate_json(success_json)
    (target_dir / "success.json").write_text(success_json, encoding="utf-8")
    results["success.json"] = success_json

    # 2. INSUFFICIENT_EVIDENCE Briefing Sample
    empty_pack = EvidencePack(company_name=company_high.name, evidences=[])
    briefing_insufficient = await BriefingComposerService(
        SampleBriefingProvider({})
    ).compose(company_high, empty_pack, [])

    insufficient_json = json.dumps(
        briefing_insufficient.model_dump(), indent=2, ensure_ascii=False
    )
    BriefingObject.model_validate_json(insufficient_json)
    (target_dir / "insufficient_evidence.json").write_text(insufficient_json, encoding="utf-8")
    results["insufficient_evidence.json"] = insufficient_json

    # 3. ENTITY_AMBIGUOUS Briefing Sample
    company_low = _company_low()
    briefing_ambiguous = await BriefingComposerService(
        SampleBriefingProvider({})
    ).compose(company_low, empty_pack, [])

    ambiguous_json = json.dumps(
        briefing_ambiguous.model_dump(), indent=2, ensure_ascii=False
    )
    BriefingObject.model_validate_json(ambiguous_json)
    (target_dir / "entity_ambiguous.json").write_text(ambiguous_json, encoding="utf-8")
    results["entity_ambiguous.json"] = ambiguous_json

    # 실제 예외 처리기(ah_there_exception_handler)를 호출하여 오류 response 생성
    req = Request({"type": "http", "method": "GET", "path": "/"})

    # 4. PROVIDER_AUTH_ERROR ErrorResponse Sample (HTTP 502)
    auth_exc = ProviderAuthException(
        message="P1 profile compiler provider authentication failed: HTTP 401 Unauthorized",
        detail={"error_code": "PROVIDER_AUTH_ERROR", "error": "HTTP 401 Unauthorized"},
    )
    res_auth = await ah_there_exception_handler(req, auth_exc)
    assert res_auth.status_code == 502
    auth_json = json.dumps(json.loads(bytes(res_auth.body).decode("utf-8")), indent=2, ensure_ascii=False)
    ErrorResponse.model_validate_json(auth_json)
    (target_dir / "provider_auth_error.json").write_text(auth_json, encoding="utf-8")
    results["provider_auth_error.json"] = auth_json

    # 5. PROVIDER_TIMEOUT ErrorResponse Sample (HTTP 504)
    timeout_exc = ProviderTimeoutException(
        message="P1 profile compiler provider call timed out: after 30 seconds",
        detail={"error_code": "PROVIDER_TIMEOUT", "error": "timed out after 30 seconds"},
    )
    res_timeout = await ah_there_exception_handler(req, timeout_exc)
    assert res_timeout.status_code == 504
    timeout_json = json.dumps(json.loads(bytes(res_timeout.body).decode("utf-8")), indent=2, ensure_ascii=False)
    ErrorResponse.model_validate_json(timeout_json)
    (target_dir / "provider_timeout.json").write_text(timeout_json, encoding="utf-8")
    results["provider_timeout.json"] = timeout_json

    # 6. INVALID_CITATION ErrorResponse Sample (HTTP 422) - P3 Mock 인용 오류 경로에서 실제 예외 획득
    invalid_p3_response = {
        "status": "SUCCESS",
        "drafts": [
            {
                "title": "잘못된 인용 가설",
                "reason": "잘못된 인용 검증 테스트",
                "reasoning_chain": ["논리1"],
                "supporting_evidence": ["E01", "E99"],
                "contradicting_evidence": [],
                "questions": ["질문?"],
                "status": "ACTIVE",
            }
        ],
        "reasoning_summary": "잘못된 인용 가설 생성 시도",
    }
    try:
        await DemandReasonerService(
            MockReasoningProvider(default_response=invalid_p3_response)
        ).reason_demand(P3Input(compiled_profile=p1, evidence_pack=evidence_pack))
        raise RuntimeError("Expected CitationIntegrityException was not raised")
    except CitationIntegrityException as exc:
        res_citation = await ah_there_exception_handler(req, exc)
        assert res_citation.status_code == 422
        citation_json = json.dumps(json.loads(bytes(res_citation.body).decode("utf-8")), indent=2, ensure_ascii=False)
        ErrorResponse.model_validate_json(citation_json)
        (target_dir / "invalid_citation.json").write_text(citation_json, encoding="utf-8")
        results["invalid_citation.json"] = citation_json

    # 오프라인 Provenance 및 PRD 메타데이터 매니페스트 생성
    manifest = {
        "prd_provenance": {
            "source": "Master PRD Drive v1",
            "version": "Draft v1",
            "date": "2026-09-22",
            "hash": "A9B9EF2A86120C8710ACEF9A435AAB57CB532FFCE3B3D503BE7764BD3D2D1E9F",
        },
        "samples_provenance": "MOCK_VIRTUAL",
        "samples": {
            "success.json": {
                "status_code": 200,
                "contract_model": "BriefingObject",
                "briefing_status": "SUCCESS",
                "description": "정상 브리핑 생성 성공 샘플",
            },
            "insufficient_evidence.json": {
                "status_code": 200,
                "contract_model": "BriefingObject",
                "briefing_status": "INSUFFICIENT_EVIDENCE",
                "description": "확정 근거 부족 응답 샘플",
            },
            "entity_ambiguous.json": {
                "status_code": 200,
                "contract_model": "BriefingObject",
                "briefing_status": "ENTITY_AMBIGUOUS",
                "description": "기업 식별 신뢰도 LOW 응답 샘플",
            },
            "provider_auth_error.json": {
                "status_code": 502,
                "contract_model": "ErrorResponse",
                "error_code": "PROVIDER_AUTH_ERROR",
                "description": "공급자 인증 실패 응답 샘플",
            },
            "provider_timeout.json": {
                "status_code": 504,
                "contract_model": "ErrorResponse",
                "error_code": "PROVIDER_TIMEOUT",
                "description": "공급자 응답 시간 초과 응답 샘플",
            },
            "invalid_citation.json": {
                "status_code": 422,
                "contract_model": "ErrorResponse",
                "error_code": "INVALID_CITATION",
                "description": "잘못된 인용 검증 실패 응답 샘플",
            },
        },
    }
    manifest_json = json.dumps(manifest, indent=2, ensure_ascii=False)
    (target_dir / "manifest.json").write_text(manifest_json, encoding="utf-8")
    results["manifest.json"] = manifest_json

    return results


def main():
    asyncio.run(generate_samples())
    print("UI review JSON samples generated successfully under docs/ui-review/samples/")


if __name__ == "__main__":
    main()
