"""듀얼 리서치: 기업 레벨(최근 6개월 이슈) + 산업 레벨(시장 동향·원가/규제·공통 과제) 공개 검색 쿼리.

쿼리는 고객사 공개 식별자와 산업명만으로 만든다. 영업 메모·CRM 정보는 시그니처상 들어올 수 없다.
"""

from app.domain.models import Evidence, EvidencePack
from app.domain.search_models import RawSearchItem, SearchQuery
from app.domain.strategic_questions import EvidenceScope
from app.services.evidence_builder import EvidenceBuilder
from app.services.search_privacy_filter import SearchPrivacyFilter

COMPANY_TOPICS = ("최근 6개월 주요 뉴스 공시", "시설 증설 투자", "신규 채용")
INDUSTRY_TOPICS = ("최신 시장 동향", "원가 규제 이슈", "업계 공통 과제")
SCOPE_TAG_PREFIX = "scope:"


def build_company_queries(company_name: str) -> list[SearchQuery]:
    return [
        SearchQuery(query=SearchPrivacyFilter.sanitize_search_query(company_name, topic), time_range="6m")
        for topic in COMPANY_TOPICS
    ]


def build_industry_queries(industry: str) -> list[SearchQuery]:
    return [
        SearchQuery(query=SearchPrivacyFilter.sanitize_search_query(f"{industry} 산업", topic), time_range="6m")
        for topic in INDUSTRY_TOPICS
    ]


def scope_tag(scope: EvidenceScope) -> str:
    return f"{SCOPE_TAG_PREFIX}{scope.lower()}"


def evidence_scope(evidence: Evidence) -> EvidenceScope | None:
    if scope_tag("INDUSTRY") in evidence.relevance_tags:
        return "INDUSTRY"
    if scope_tag("COMPANY") in evidence.relevance_tags:
        return "COMPANY"
    return None


def tag_evidence_scopes(
    evidence_pack: EvidencePack,
    raw_items: list[RawSearchItem],
    industry_queries: list[SearchQuery],
) -> None:
    """원 검색 쿼리를 기준으로 각 Evidence에 기업/산업 범위 태그를 붙인다.

    산업 쿼리로 수집된 항목만 INDUSTRY, 그 외는 COMPANY로 본다.
    """
    industry_query_texts = {q.query for q in industry_queries}
    scope_by_url: dict[str, EvidenceScope] = {}
    for item in raw_items:
        url = EvidenceBuilder._normalize_url(item.url)
        if url and url not in scope_by_url:
            scope_by_url[url] = "INDUSTRY" if item.query in industry_query_texts else "COMPANY"

    for evidence in evidence_pack.evidences:
        scope = scope_by_url.get(evidence.url, "COMPANY")
        tag = scope_tag(scope)
        if tag not in evidence.relevance_tags:
            evidence.relevance_tags.append(tag)
