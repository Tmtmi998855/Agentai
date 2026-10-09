import re
from app.core.exceptions import AhThereException
from app.domain.search_models import SearchRequest, SearchQuery


class PrivacyViolationException(AhThereException):
    """Raised when sensitive private CRM data or PII is detected in a search query."""
    def __init__(self, message: str = "Search query contains prohibited private data", detail: dict | None = None):
        super().__init__(message, error_code="PRIVACY_VIOLATION", detail=detail)


PII_PATTERNS = [
    (r"01[016789]-?\d{3,4}-?\d{4}", "Phone Number"),
    (r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "Email Address"),
    (r"\d{6}-[1-4]\d{6}", "Resident Registration Number"),
    (r"(비밀|기밀|계약서|계약금|계약금액|단가|특약|담당자메모|과거메모|미팅메모|내부메모|CRM|고객사메모|개인폰|주민번호|past_notes)", "CRM/Private Keyword"),
]


class SearchPrivacyFilter:
    """Validator preventing private CRM notes, personal information, and secrets from entering search queries."""

    @staticmethod
    def validate_query(query: str) -> None:
        """Validates that a search query does not contain prohibited private details."""
        if not query:
            return

        for pattern, label in PII_PATTERNS:
            if re.search(pattern, query, re.IGNORECASE):
                raise PrivacyViolationException(
                    message=f"Search query contains prohibited private information: {label}",
                    detail={"query": query, "violation_type": label}
                )

    @staticmethod
    def sanitize_search_query(company_name: str, topic_keyword: str) -> str:
        """Constructs a clean public search query using only public company identity and search topics."""
        clean_company = re.sub(r"[^\w\s가-힣a-zA-Z0-9.-]", "", company_name).strip()
        clean_topic = re.sub(r"[^\w\s가-힣a-zA-Z0-9.-]", "", topic_keyword).strip()

        safe_query = f"{clean_company} {clean_topic}".strip()
        SearchPrivacyFilter.validate_query(safe_query)
        return safe_query

    @staticmethod
    def create_public_search_request(
        company_name: str,
        approved_topics: list[str]
    ) -> SearchRequest:
        """
        Structurally guarantees SearchRequest is constructed ONLY from public company identity
        and approved public search topics.
        CRM strings are structurally excluded from signature.
        """
        # Validate company_name
        SearchPrivacyFilter.validate_query(company_name)

        if not approved_topics:
            approved_topics = ["최신 대표이사 사업장 시설 투자 채용 공시"]

        queries: list[SearchQuery] = []
        for topic in approved_topics:
            safe_q = SearchPrivacyFilter.sanitize_search_query(company_name, topic)
            queries.append(SearchQuery(query=safe_q))

        return SearchRequest(
            company_name=company_name,
            queries=queries,
        )
