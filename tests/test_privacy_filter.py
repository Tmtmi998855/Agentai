import pytest
from app.services.search_privacy_filter import SearchPrivacyFilter, PrivacyViolationException


def test_crm_private_data_blocked_from_search_query():
    """Part G-17: CRM·개인정보가 검색 요청에 유입되지 않음."""
    # 1. Clean public search query should pass
    clean_query = SearchPrivacyFilter.sanitize_search_query("현대렌탈", "신규 사업장 사옥 이전")
    assert clean_query == "현대렌탈 신규 사업장 사옥 이전"

    # 2. Query containing PII (Phone number) raises PrivacyViolationException
    with pytest.raises(PrivacyViolationException):
        SearchPrivacyFilter.validate_query("현대렌탈 담당자 010-1234-5678 사옥 이전")

    # 3. Query containing PII (Email address) raises PrivacyViolationException
    with pytest.raises(PrivacyViolationException):
        SearchPrivacyFilter.validate_query("현대렌탈 john@example.com 미팅 메모")

    # 4. Query containing sensitive CRM keyword (계약금액, 주민번호 등) raises PrivacyViolationException
    with pytest.raises(PrivacyViolationException):
        SearchPrivacyFilter.validate_query("현대렌탈 계약금액 5000만원 조건")


def test_create_public_search_request_structural_isolation():
    """Structural isolation test: MeetingContext past_notes cannot enter SearchRequest queries."""
    # 1. SearchRequest is created using ONLY public company name and approved search topics
    search_req = SearchPrivacyFilter.create_public_search_request(
        company_name="현대렌탈",
        approved_topics=["시설 투자", "채용 공시"]
    )

    assert search_req.company_name == "현대렌탈"
    assert len(search_req.queries) == 2
    # Ensure past_notes string is COMPLETELY ABSENT from all queries!
    for q in search_req.queries:
        assert "3000만원" not in q.query
        assert "past_notes" not in q.query
        assert "CRM" not in q.query
        assert "유휴" not in q.query

    # 2. Passing company name with CRM data raises PrivacyViolationException
    with pytest.raises(PrivacyViolationException):
        SearchPrivacyFilter.create_public_search_request(
            company_name="현대렌탈 담당자메모 010-9999-8888",
            approved_topics=["공시"]
        )
