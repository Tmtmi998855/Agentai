"""Stage-specific Mock response fixtures for offline pipeline execution.

Preserves user's input company name and sales profile across P1, P2, Search, WebFetcher, P3, and P4
without overwriting them with static hardcoded company names. Uses virtual official domains under example.com.
"""

import html
import urllib.parse
from typing import Any
from app.domain.job_models import BriefingCreateRequest
from app.domain.models import CompanyEntity
from app.domain.search_models import RawSearchItem
from app.domain.pipeline_models import Evidence, PROMPT_VERSION_P1, PROMPT_VERSION_P2, PROMPT_VERSION_P3, PROMPT_VERSION_P4
from app.services.evidence_builder import EvidenceBuilder


MOCK_VIRTUAL_OFFICIAL_DOMAINS = {"official.example.com", "news.example.com"}


def build_mock_company_entity(company_name: str, sales_profile_industry: str) -> CompanyEntity:
    safe_path = urllib.parse.quote(company_name.lower().replace(" ", "-"))
    return CompanyEntity(
        name=company_name,
        resolved_name=f"{company_name} 주식회사",
        entity_confidence="HIGH",
        industry=sales_profile_industry,
        website=f"https://example.com/company/{safe_path}",
        region="서울",
    )


def build_mock_p1_data(request_data: BriefingCreateRequest) -> dict[str, Any]:
    cp = request_data.company_name
    sp = request_data.sales_profile
    return {
        "version": PROMPT_VERSION_P1,
        "company_name": cp,
        "resolved_name": f"{cp} 주식회사",
        "industry": sp.industry,
        "product_service": sp.product_service,
        "target_customer": sp.target_customer,
        "sales_goal": sp.sales_goal,
        "focus_topics": ["사업장 확장", "시설 투자", "채용"],
        "compiled_at": "2026-09-27T00:00:00Z",
    }


def build_mock_p2_data(company_name: str) -> dict[str, Any]:
    return {
        "version": PROMPT_VERSION_P2,
        "company_name": company_name,
        "approved_topics": ["사업장 확장", "시설 투자"],
        "search_queries": [
            {"query": f"{company_name} 신규 사업장 개설 공시", "max_results": 5},
            {"query": f"{company_name} 하반기 영업 채용 공고", "max_results": 5},
        ],
        "planned_at": "2026-09-27T00:00:00Z",
    }


def build_mock_search_items(company_name: str) -> list[RawSearchItem]:
    return [
        RawSearchItem(
            item_id="mock-search-1",
            query=f"{company_name} 신규 사업장 개설 공시",
            title=f"{company_name} 신규 사업장 개설 및 시설 투자 공시",
            snippet=f"{company_name}은(는) 사업 확장을 위해 신규 사업장을 개설하고 시설 투자를 진행합니다.",
            url="https://official.example.com/dart/001",
            publisher="가상 금융감독원 전자공시",
            published_at="2026-09-01",
        ),
        RawSearchItem(
            item_id="mock-search-2",
            query=f"{company_name} 하반기 영업 채용 공고",
            title=f"{company_name} 하반기 영업 및 기획 인력 채용",
            snippet=f"{company_name}은(는) 사업 확장에 따른 하반기 영업 인력을 대규모 채용합니다.",
            url="https://news.example.com/virtual-news/002",
            publisher="가상 매일경제",
            published_at="2026-09-10",
        ),
    ]


MOCK_INDUSTRY_URL = "https://news.example.com/virtual-industry/101"
MOCK_INDUSTRY_ITEM_ID = "mock-industry-1"


def _mock_industry_title_snippet(industry: str) -> tuple[str, str]:
    return (
        f"{industry} 업계 원가 부담 확대",
        f"{industry} 업계는 원자재 가격과 물류비 상승으로 운영 비용 관리가 공통 과제로 떠올랐습니다.",
    )


def build_mock_industry_search_items(industry: str, industry_query: str) -> list[RawSearchItem]:
    """듀얼 리서치 산업 레벨 Mock 검색 결과. query는 산업 쿼리 원문과 같아야 scope 태깅이 된다."""
    title, snippet = _mock_industry_title_snippet(industry)
    return [
        RawSearchItem(
            item_id=MOCK_INDUSTRY_ITEM_ID,
            query=industry_query,
            title=title,
            snippet=snippet,
            url=MOCK_INDUSTRY_URL,
            publisher="가상 산업 전문지",
            published_at="2026-09-05",
        )
    ]


def build_mock_industry_virtual_html(industry: str, identifier: str) -> tuple[str, str] | None:
    """산업 Mock 항목에 대한 exact 매칭 가상 원문."""
    if identifier not in (MOCK_INDUSTRY_URL, MOCK_INDUSTRY_ITEM_ID):
        return None
    title, snippet = _mock_industry_title_snippet(industry)
    claim = EvidenceBuilder._extract_clean_claim(title, snippet)
    escaped_title, escaped_snippet = _mock_industry_title_snippet(html.escape(industry))
    escaped_claim = EvidenceBuilder._extract_clean_claim(escaped_title, escaped_snippet)
    return f"<html><body><h1>산업 동향</h1><p>{escaped_claim}</p></body></html>", claim


def build_mock_virtual_html(company_name: str, identifier: str) -> tuple[str, str] | None:
    """URL 또는 item_id의 exact 매칭에 대해서만 (virtual_html_body, target_claim) 튜플을 반환한다.
    
    'dart.fss.or.kr' in identifier 등의 부분 문자열 일치를 사용하지 않으며 exact match만 허용한다.
    알 수 없는 identifier 또는 룩어라이크 URL은 None을 반환한다.
    """
    escaped_cp = html.escape(company_name)
    if identifier in ("https://official.example.com/dart/001", "mock-search-1"):
        title = f"{company_name} 신규 사업장 개설 및 시설 투자 공시"
        snippet = f"{company_name}은(는) 사업 확장을 위해 신규 사업장을 개설하고 시설 투자를 진행합니다."
        claim = EvidenceBuilder._extract_clean_claim(title, snippet)
        escaped_title = f"{escaped_cp} 신규 사업장 개설 및 시설 투자 공시"
        escaped_snippet = f"{escaped_cp}은(는) 사업 확장을 위해 신규 사업장을 개설하고 시설 투자를 진행합니다."
        escaped_claim = EvidenceBuilder._extract_clean_claim(escaped_title, escaped_snippet)
        html_body = f"<html><body><h1>공시</h1><p>{escaped_claim}</p></body></html>"
        return html_body, claim
    elif identifier in ("https://news.example.com/virtual-news/002", "mock-search-2"):
        title = f"{company_name} 하반기 영업 및 기획 인력 채용"
        snippet = f"{company_name}은(는) 사업 확장에 따른 하반기 영업 인력을 대규모 채용합니다."
        claim = EvidenceBuilder._extract_clean_claim(title, snippet)
        escaped_title = f"{escaped_cp} 하반기 영업 및 기획 인력 채용"
        escaped_snippet = f"{escaped_cp}은(는) 사업 확장에 따른 하반기 영업 인력을 대규모 채용합니다."
        escaped_claim = EvidenceBuilder._extract_clean_claim(escaped_title, escaped_snippet)
        html_body = f"<html><body><h1>뉴스</h1><p>{escaped_claim}</p></body></html>"
        return html_body, claim
    else:
        return None


def build_mock_p3_data(
    company_name: str,
    product_service: str,
    confirmed_evidences: list[Evidence],
) -> dict[str, Any]:
    """확정된 Evidence 목록에 기반하여 P3 Demand Reasoner 모의 응답을 생성한다."""
    if not confirmed_evidences:
        return {
            "version": PROMPT_VERSION_P3,
            "status": "INSUFFICIENT_EVIDENCE",
            "drafts": [],
            "reasoning_summary": f"확정된 FACT가 부족하여 {company_name} 대상 가설을 생성하지 않았습니다.",
            "evaluated_at": "2026-09-27T00:00:00Z",
        }
    eids = [e.evidence_id for e in confirmed_evidences]
    reasoning_chain = [f"{e.evidence_id} FACT: {e.claim}" for e in confirmed_evidences] + [
        f"{product_service} 도입 검토 수요 도출"
    ]
    drafts = [
        {
            "title": f"사업장에 따른 {product_service} 도입 수요",
            "reason": f"{company_name}의 정보 확장에 따른 {product_service} 필요성",
            "reasoning_chain": reasoning_chain,
            "supporting_evidence": eids,
            "contradicting_evidence": [],
            "questions": [
                f"{company_name}의 운영 관리에 있어 {product_service} 관리 체계는 어떻게 준비하고 계신가요?"
            ],
            "status": "ACTIVE",
        }
    ]
    return {
        "version": PROMPT_VERSION_P3,
        "status": "SUCCESS",
        "drafts": drafts,
        "reasoning_summary": f"확정된 FACT {len(confirmed_evidences)}건에 기초하여 {company_name} 대상 가설 도출 완료",
        "evaluated_at": "2026-09-27T00:00:00Z",
    }


def build_mock_p4_payload(
    company_name: str,
    product_service: str,
    scored_hypotheses: list[dict[str, Any]],
    confirmed_evidences: list[Evidence],
) -> dict[str, Any]:
    """확정된 Evidence 목록 및 scored_hypotheses에 기반하여 P4 Briefing Composer 모의 응답을 생성한다."""
    if not confirmed_evidences:
        summary_lines = [
            f"{company_name}은(는) 조회된 공개 공시 및 뉴스 근거가 부족합니다.",
            "현재 수집된 정보만으로는 기업 현황을 판단할 수 없습니다.",
            "추가 검증 후 브리핑을 업데이트하세요.",
        ]
        return {
            "version": PROMPT_VERSION_P4,
            "company_snapshot": {
                "summary": "\n".join(summary_lines),
                "evidence_ids": [],
            },
            "small_talk": [],
            "demand_hypotheses": [],
            "meeting_questions": [
                "최근 주요 사업 변화가 있었나요?",
                "현재 가장 우선순위가 높은 운영 과제는 무엇인가요?",
                "관련 계획의 일정과 의사결정 기준은 무엇인가요?",
            ],
            "warnings": ["MOCK_VIRTUAL: 오프라인 가상 파이프라인에서 생성된 결과입니다."],
        }

    eids = [e.evidence_id for e in confirmed_evidences]
    summary_lines = [
        f"{company_name}은(는) 사업 확장을 추진 중입니다.",
    ]
    for e in confirmed_evidences:
        summary_lines.append(f"확정 근거({e.evidence_id}): {e.claim[:60]}")
    summary_lines.append(f"미팅에서 {product_service} 관련 수요 및 운영 계획을 논의할 수 있습니다.")
    if len(summary_lines) > 5:
        summary_lines = summary_lines[:5]
    elif len(summary_lines) < 3:
        summary_lines.append("추가 세부 사항은 미팅에서 확인할 필요가 있습니다.")

    small_talk = [
        {
            "topic": "사업 확장",
            "talking_point": f"{company_name}의 신규 소식에 대해 축하드립니다.",
            "evidence_ids": [confirmed_evidences[0].evidence_id],
        }
    ]

    return {
        "version": PROMPT_VERSION_P4,
        "company_snapshot": {
            "summary": "\n".join(summary_lines),
            "evidence_ids": eids,
        },
        "small_talk": small_talk,
        "demand_hypotheses": scored_hypotheses,
        "meeting_questions": [
            f"{company_name}의 운영 계획 및 추진 일정은 어떻게 되시나요?",
            f"조직 확장에 따라 {product_service} 관리 체계 도입을 검토 중이신가요?",
            "현재 가장 우선순위가 높은 운영 과제 및 의사결정 기준은 무엇인가요?",
        ],
        "warnings": ["MOCK_VIRTUAL: 오프라인 가상 파이프라인에서 생성된 결과입니다."],
    }
