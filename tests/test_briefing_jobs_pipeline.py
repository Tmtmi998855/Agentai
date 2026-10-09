import pytest
from fastapi.testclient import TestClient

from app.domain.models import CompanyEntity, ProviderResult
from app.domain.search_models import RawSearchItem, SearchRequest, SearchResult
from app.providers.search_base import SearchProvider
from app.main import app, create_app
from app.providers.base import ReasoningProvider
from app.providers.mock import MockReasoningProvider
from app.services.orchestrator import BriefingOrchestrator


def _valid_payload_dict(company_name: str = "가상기업 시나리오") -> dict:
    return {
        "company_name": company_name,
        "sales_profile": {
            "company": "가상기업 세일즈",
            "industry": "IT 솔루션",
            "product_service": "기업용 B2B 세일즈 솔루션",
            "target_customer": "중견기업",
            "sales_goal": "신규 도입 수주",
        },
        "meeting_context": {
            "department": "영업팀",
            "role": "팀장",
            "meeting_purpose": "데모",
            "past_notes": "SECRET_CRM_PAST_NOTE_MARKER",
        },
    }


def test_pipeline_success_with_p1_to_p4_and_citation_integrity():
    """P1부터 P4까지 전체 파이프라인 연동 성공 및 인용 무결성을 검증한다."""
    with TestClient(app) as client:
        res = client.post("/v1/briefings", json=_valid_payload_dict("가상기업 무신사"))
        assert res.status_code == 202
        job_id = res.json()["job_id"]

        for _ in range(20):
            st = client.get(f"/v1/briefing-jobs/{job_id}").json()
            if st["status"] == "COMPLETED":
                break

        briefing_res = client.get(f"/v1/briefings/{job_id}")
        assert briefing_res.status_code == 200
        briefing = briefing_res.json()

        assert briefing["status"] == "SUCCESS"
        assert briefing["company"]["name"] == "가상기업 무신사"
        assert briefing["company"]["resolved_name"] == "가상기업 무신사 주식회사"
        assert len(briefing["sources"]) == 2
        assert "MOCK_VIRTUAL: 오프라인 가상 파이프라인에서 생성된 결과입니다." in briefing["warnings"]

        # 출처 및 인용 무결성 검증
        source_ids = {s["evidence_id"] for s in briefing["sources"]}
        for s in briefing["sources"]:
            assert "example.com" in s["url"]
            assert "가상" in s["publisher"]

        for eid in briefing["company_snapshot"]["evidence_ids"]:
            assert eid in source_ids
        for st_item in briefing["small_talk"]:
            for eid in st_item["evidence_ids"]:
                assert eid in source_ids
        for hyp in briefing["demand_hypotheses"]:
            for eid in hyp["supporting_evidence"] + hyp["contradicting_evidence"]:
                assert eid in source_ids


def test_insufficient_evidence_when_no_confirmed_facts():
    """검색 결과 확정 FACT가 없을 때 브리핑 상태가 INSUFFICIENT_EVIDENCE가 되는지 검증한다."""
    app_instance = create_app()
    with TestClient(app_instance) as client:
        orchestrator = BriefingOrchestrator(search_func=lambda name, queries: [])
        app_instance.state.job_manager.set_orchestrator(orchestrator)

        res = client.post("/v1/briefings", json=_valid_payload_dict("가상기업 팩트없음"))
        job_id = res.json()["job_id"]

        for _ in range(20):
            if client.get(f"/v1/briefing-jobs/{job_id}").json()["status"] == "COMPLETED":
                break

        briefing = client.get(f"/v1/briefings/{job_id}").json()
        assert briefing["status"] == "INSUFFICIENT_EVIDENCE"
        assert briefing["demand_hypotheses"] == []
        assert briefing["sources"] == []
        assert any("확정된 FACT가 부족하여" in w for w in briefing["warnings"])


@pytest.mark.parametrize("confidence", ["LOW", "MEDIUM"])
def test_early_exit_on_low_or_medium_confidence(confidence):
    """기업 식별 신뢰도가 LOW/MEDIUM일 때 P1, 검색, P3, P4가 모두 호출되지 않고 조기 종료되는지 스파이 검증한다."""
    p1_called = False
    search_called = False
    p3_called = False
    p4_called = False

    class SpyReasoningProvider(ReasoningProvider):
        def __init__(self, stage_name: str):
            self.stage_name = stage_name

        async def generate_structured(self, *args, **kwargs) -> ProviderResult:
            nonlocal p1_called, p3_called, p4_called
            if self.stage_name == "p1":
                p1_called = True
            elif self.stage_name == "p3":
                p3_called = True
            elif self.stage_name == "p4":
                p4_called = True
            return ProviderResult(
                provider="spy",
                requested_model="mock",
                actual_model="mock",
                structured_data={},
                success=True,
            )

    def spy_search_func(cp, queries):
        nonlocal search_called
        search_called = True
        return []

    def low_or_medium_resolver(name, ind):
        return CompanyEntity(
            name=name,
            resolved_name=None,
            entity_confidence=confidence,
            candidate_entities=[f"{name} A", f"{name} B"],
        )

    app_instance = create_app()
    with TestClient(app_instance) as client:
        orchestrator = BriefingOrchestrator(
            p1_provider=SpyReasoningProvider("p1"),
            p3_provider=SpyReasoningProvider("p3"),
            p4_provider=SpyReasoningProvider("p4"),
            search_func=spy_search_func,
            entity_resolver=low_or_medium_resolver,
        )
        app_instance.state.job_manager.set_orchestrator(orchestrator)

        res = client.post("/v1/briefings", json=_valid_payload_dict(f"가상기업 {confidence}"))
        job_id = res.json()["job_id"]

        for _ in range(20):
            if client.get(f"/v1/briefing-jobs/{job_id}").json()["status"] == "COMPLETED":
                break

        briefing = client.get(f"/v1/briefings/{job_id}").json()
        assert briefing["status"] == "ENTITY_AMBIGUOUS"
        assert briefing["company"]["entity_confidence"] == confidence
        assert briefing["company"]["resolved_name"] is None
        assert briefing["demand_hypotheses"] == []
        assert p1_called is False
        assert search_called is False
        assert p3_called is False
        assert p4_called is False
        assert any("MOCK_VIRTUAL" in w for w in briefing["warnings"])


def test_search_query_privacy_marker_absent():
    """생성된 검색 쿼리에 meeting_context의 past_notes 마커 등 비공개 정보가 포함되지 않는지 검증한다."""
    captured_queries: list[str] = []

    def spy_search(cp, queries):
        for q in queries:
            captured_queries.append(q.query)
        return []

    app_instance = create_app()
    with TestClient(app_instance) as client:
        orchestrator = BriefingOrchestrator(search_func=spy_search)
        app_instance.state.job_manager.set_orchestrator(orchestrator)

        res = client.post("/v1/briefings", json=_valid_payload_dict("가상기업 프라이버시"))
        job_id = res.json()["job_id"]

        for _ in range(20):
            if client.get(f"/v1/briefing-jobs/{job_id}").json()["status"] == "COMPLETED":
                break

        assert len(captured_queries) > 0
        for q_str in captured_queries:
            assert "SECRET_CRM_PAST_NOTE_MARKER" not in q_str


class InstantErrorProvider(ReasoningProvider):
    def __init__(self, error_code: str | None, return_none_data: bool = False):
        self.error_code = error_code
        self.return_none_data = return_none_data

    async def generate_structured(self, *args, **kwargs) -> ProviderResult:
        if self.return_none_data:
            return ProviderResult(
                provider="test",
                requested_model="mock",
                actual_model="mock",
                structured_data=None,
                success=True,
            )
        return ProviderResult(
            provider="test",
            requested_model="mock",
            actual_model="mock",
            success=False,
            error="Mock provider failure secret payload",
            error_code=self.error_code,
        )


@pytest.mark.parametrize(
    ("stage", "error_code", "return_none", "expected_http", "expected_code"),
    [
        ("p1", "PROVIDER_AUTH_ERROR", False, 502, "PROVIDER_AUTH_ERROR"),
        ("p1", "PROVIDER_TIMEOUT", False, 504, "PROVIDER_TIMEOUT"),
        ("p1", "PROVIDER_ERROR", False, 502, "PROVIDER_ERROR"),
        ("p1", None, True, 502, "STRUCTURED_OUTPUT_MISSING"),
        ("p2", "PROVIDER_AUTH_ERROR", False, 502, "PROVIDER_AUTH_ERROR"),
        ("p2", "PROVIDER_TIMEOUT", False, 504, "PROVIDER_TIMEOUT"),
        ("p2", "PROVIDER_ERROR", False, 502, "PROVIDER_ERROR"),
        ("p2", None, True, 502, "STRUCTURED_OUTPUT_MISSING"),
        ("p3", "PROVIDER_AUTH_ERROR", False, 502, "PROVIDER_AUTH_ERROR"),
        ("p3", "PROVIDER_TIMEOUT", False, 504, "PROVIDER_TIMEOUT"),
        ("p3", "PROVIDER_ERROR", False, 502, "PROVIDER_ERROR"),
        ("p3", None, True, 502, "STRUCTURED_OUTPUT_MISSING"),
        ("p4", "PROVIDER_AUTH_ERROR", False, 502, "PROVIDER_AUTH_ERROR"),
        ("p4", "PROVIDER_TIMEOUT", False, 504, "PROVIDER_TIMEOUT"),
        ("p4", "PROVIDER_ERROR", False, 502, "PROVIDER_ERROR"),
        ("p4", None, True, 502, "STRUCTURED_OUTPUT_MISSING"),
    ],
)
def test_parametrized_pipeline_stage_provider_errors(
    stage, error_code, return_none, expected_http, expected_code
):
    """P1, P2, P3, P4 각각 AUTH/TIMEOUT/GENERIC/STRUCTURED_NONE 4경우 총 16가지 예외 상황 조합을 검증한다."""
    provider = InstantErrorProvider(error_code=error_code, return_none_data=return_none)

    orchestrator = BriefingOrchestrator(
        p1_provider=provider if stage == "p1" else None,
        p2_provider=provider if stage == "p2" else None,
        p3_provider=provider if stage == "p3" else None,
        p4_provider=provider if stage == "p4" else None,
    )

    app_instance = create_app()
    with TestClient(app_instance) as client:
        app_instance.state.job_manager.set_orchestrator(orchestrator)

        res = client.post("/v1/briefings", json=_valid_payload_dict(f"가상기업 {stage}"))
        job_id = res.json()["job_id"]

        for _ in range(20):
            st = client.get(f"/v1/briefing-jobs/{job_id}").json()
            if st["status"] == "FAILED":
                assert st["error_code"] == expected_code
                assert st["error_http_status"] == expected_http
                break

        result_res = client.get(f"/v1/briefings/{job_id}")
        assert result_res.status_code == expected_http
        assert result_res.json()["error_code"] == expected_code
        assert "secret payload" not in result_res.text


def test_fact_verification_with_reordered_and_dropped_sources():
    """검색 항목의 순서 변경 및 일부 drop 발생 시 원문 claim -> 해당 URL -> EID -> reasoning_chain 일치까지 검증한다."""
    app_instance = create_app()

    # 1. 순서 변경 시나리오
    def reordered_search(company_name, queries):
        return [
            RawSearchItem(
                item_id="mock-search-2",
                query="채용 공고",
                title=f"{company_name} 하반기 영업 및 기획 인력 채용",
                snippet=f"{company_name}은(는) 사업 확장에 따른 하반기 영업 인력을 대규모 채용합니다.",
                url="https://news.example.com/virtual-news/002",
                publisher="가상 매일경제",
                published_at="2026-09-10",
            ),
            RawSearchItem(
                item_id="mock-search-1",
                query="공시",
                title=f"{company_name} 신규 사업장 개설 및 시설 투자 공시",
                snippet=f"{company_name}은(는) 사업 확장을 위해 신규 사업장을 개설하고 시설 투자를 진행합니다.",
                url="https://official.example.com/dart/001",
                publisher="가상 금융감독원 전자공시",
                published_at="2026-09-01",
            ),
        ]

    with TestClient(app_instance) as client:
        orchestrator = BriefingOrchestrator(search_func=reordered_search)
        app_instance.state.job_manager.set_orchestrator(orchestrator)

        res = client.post("/v1/briefings", json=_valid_payload_dict("가상기업 순서변경"))
        job_id = res.json()["job_id"]

        for _ in range(20):
            if client.get(f"/v1/briefing-jobs/{job_id}").json()["status"] == "COMPLETED":
                break

        briefing = client.get(f"/v1/briefings/{job_id}").json()
        assert briefing["status"] == "SUCCESS"
        assert len(briefing["sources"]) == 2

        e01_source = briefing["sources"][0]
        e02_source = briefing["sources"][1]

        assert e01_source["evidence_id"] == "E01"
        assert e01_source["url"] == "https://news.example.com/virtual-news/002"
        assert "채용" in e01_source["claim"]

        assert e02_source["evidence_id"] == "E02"
        assert e02_source["url"] == "https://official.example.com/dart/001"
        assert "공시" in e02_source["claim"]

        reasoning_chain = briefing["demand_hypotheses"][0]["reasoning_chain"]
        assert any(
            line.startswith("E01 FACT:") and "채용" in line for line in reasoning_chain
        )
        assert any(
            line.startswith("E02 FACT:") and "공시" in line for line in reasoning_chain
        )

    # 2. 1개 항목 drop 시나리오
    def dropped_search(company_name, queries):
        return [
            RawSearchItem(
                item_id="mock-search-2",
                query="채용 공고",
                title=f"{company_name} 하반기 영업 및 기획 인력 채용",
                snippet=f"{company_name}은(는) 사업 확장에 따른 하반기 영업 인력을 대규모 채용합니다.",
                url="https://news.example.com/virtual-news/002",
                publisher="가상 매일경제",
                published_at="2026-09-10",
            )
        ]

    app_instance2 = create_app()
    with TestClient(app_instance2) as client2:
        orchestrator2 = BriefingOrchestrator(search_func=dropped_search)
        app_instance2.state.job_manager.set_orchestrator(orchestrator2)

        res2 = client2.post("/v1/briefings", json=_valid_payload_dict("가상기업 드롭"))
        job_id2 = res2.json()["job_id"]

        for _ in range(20):
            if client2.get(f"/v1/briefing-jobs/{job_id2}").json()["status"] == "COMPLETED":
                break

        briefing2 = client2.get(f"/v1/briefings/{job_id2}").json()
        assert briefing2["status"] == "SUCCESS"
        assert len(briefing2["sources"]) == 1
        assert briefing2["sources"][0]["evidence_id"] == "E01"
        assert briefing2["company_snapshot"]["evidence_ids"] == ["E01"]
        assert briefing2["demand_hypotheses"][0]["supporting_evidence"] == ["E01"]


def test_bare_search_snippet_unconfirmed_fact_results_in_insufficient_evidence():
    """custom_raw_html이 없어 FACT가 미확정된 경우 INSUFFICIENT_EVIDENCE가 반환되고 P3Provider가 호출되지 않는지 검증한다."""
    p3_called = False

    class TrackingP3Provider(MockReasoningProvider):
        async def generate_structured(self, *args, **kwargs):
            nonlocal p3_called
            p3_called = True
            return await super().generate_structured(*args, **kwargs)

    app_instance = create_app()
    with TestClient(app_instance) as client:
        # raw_html_func가 None을 반환하여 원문 검증에 실패하도록 설정
        orchestrator = BriefingOrchestrator(
            p3_provider=TrackingP3Provider(),
            raw_html_func=lambda cp, ident: None,
        )
        app_instance.state.job_manager.set_orchestrator(orchestrator)

        res = client.post("/v1/briefings", json=_valid_payload_dict("가상기업 원문없음"))
        job_id = res.json()["job_id"]

        for _ in range(20):
            if client.get(f"/v1/briefing-jobs/{job_id}").json()["status"] == "COMPLETED":
                break

        briefing = client.get(f"/v1/briefings/{job_id}").json()
        assert briefing["status"] == "INSUFFICIENT_EVIDENCE"
        assert p3_called is False


def test_all_sources_are_example_com_and_virtual_publisher_with_mock_warning():
    """모든 출처가 example.com 하위 및 가상 publisher이며 MOCK_VIRTUAL warning이 포함되어 있는지 검증한다."""
    with TestClient(app) as client:
        res = client.post("/v1/briefings", json=_valid_payload_dict("가상기업 무신사"))
        job_id = res.json()["job_id"]

        for _ in range(20):
            if client.get(f"/v1/briefing-jobs/{job_id}").json()["status"] == "COMPLETED":
                break

        briefing = client.get(f"/v1/briefings/{job_id}").json()
        assert briefing["status"] == "SUCCESS"
        assert len(briefing["sources"]) > 0
        for s in briefing["sources"]:
            assert "example.com" in s["url"]
            assert "가상" in s["publisher"]
        assert any("MOCK_VIRTUAL" in w for w in briefing["warnings"])


def test_company_name_special_characters_preservation_and_citations():
    """company_name에 &, <>, 따옴표, 두 칸 공백 등이 포함되어 있어도 COMPLETED -> SUCCESS 처리되고 원래 입력명이 보존된다."""
    special_name = "가상 A&B <기업> '특수'  다중공백"
    app_instance = create_app()
    with TestClient(app_instance) as client:
        res = client.post("/v1/briefings", json=_valid_payload_dict(special_name))
        assert res.status_code == 202
        job_id = res.json()["job_id"]

        for _ in range(20):
            st = client.get(f"/v1/briefing-jobs/{job_id}").json()
            if st["status"] == "COMPLETED":
                break

        briefing_res = client.get(f"/v1/briefings/{job_id}")
        assert briefing_res.status_code == 200
        briefing = briefing_res.json()

        assert briefing["status"] == "SUCCESS"
        assert briefing["company"]["name"] == special_name
        assert len(briefing["sources"]) == 2

        # FACT확정인용 검증
        source_ids = {s["evidence_id"] for s in briefing["sources"]}
        for eid in briefing["company_snapshot"]["evidence_ids"]:
            assert eid in source_ids
        for hyp in briefing["demand_hypotheses"]:
            for eid in hyp["supporting_evidence"] + hyp["contradicting_evidence"]:
                assert eid in source_ids


def test_di_search_provider_error_redaction_and_empty_items_insufficient_evidence():
    """DI SearchProvider error='PRIVATE_MARKER' 시 PROVIDER_SEARCH_ERROR 502/P3미호출, items=[] 성공 시 INSUFFICIENT_EVIDENCE 검증."""
    p3_called = False

    class TrackingP3Provider(MockReasoningProvider):
        async def generate_structured(self, *args, **kwargs):
            nonlocal p3_called
            p3_called = True
            return await super().generate_structured(*args, **kwargs)

    class DirectFailSearchProvider(SearchProvider):
        async def search(self, request: SearchRequest) -> SearchResult:
            return SearchResult(
                provider="mock",
                query=request.queries[0].query if request.queries else "",
                items=[],
                total_count=0,
                success=False,
                error="PRIVATE_MARKER",
            )

    # 1. SearchProvider 실패 시나리오
    app_instance = create_app()
    with TestClient(app_instance) as client:
        orchestrator = BriefingOrchestrator(
            search_provider=DirectFailSearchProvider(),
            p3_provider=TrackingP3Provider(),
        )
        app_instance.state.job_manager.set_orchestrator(orchestrator)

        res = client.post("/v1/briefings", json=_valid_payload_dict("가상기업 검색실패"))
        assert res.status_code == 202
        job_id = res.json()["job_id"]

        for _ in range(20):
            st = client.get(f"/v1/briefing-jobs/{job_id}").json()
            if st["status"] == "FAILED":
                assert st["error_code"] == "PROVIDER_SEARCH_ERROR"
                assert st["error_http_status"] == 502
                break

        result_res = client.get(f"/v1/briefings/{job_id}")
        assert result_res.status_code == 502
        data = result_res.json()
        assert data["error_code"] == "PROVIDER_SEARCH_ERROR"
        assert "PRIVATE_MARKER" not in result_res.text
        assert p3_called is False

    # 2. SearchProvider 성공했으나 items=[] 시나리오
    class EmptySearchProvider(SearchProvider):
        async def search(self, request: SearchRequest) -> SearchResult:
            return SearchResult(
                provider="mock",
                query=request.queries[0].query if request.queries else "",
                items=[],
                total_count=0,
                success=True,
                error=None,
            )

    app_instance2 = create_app()
    with TestClient(app_instance2) as client2:
        orchestrator2 = BriefingOrchestrator(search_provider=EmptySearchProvider())
        app_instance2.state.job_manager.set_orchestrator(orchestrator2)

        res2 = client2.post("/v1/briefings", json=_valid_payload_dict("가상기업 검색빈값"))
        assert res2.status_code == 202
        job_id2 = res2.json()["job_id"]

        for _ in range(20):
            st2 = client2.get(f"/v1/briefing-jobs/{job_id2}").json()
            if st2["status"] == "COMPLETED":
                break

        briefing2 = client2.get(f"/v1/briefings/{job_id2}").json()
        assert briefing2["status"] == "INSUFFICIENT_EVIDENCE"


def test_p3_invalid_citation_triggers_http_422_error_response():
    """P3 reasoning provider가 존재하지 않는 E99를 인용한 Draft 반환 시 INVALID_CITATION HTTP 422 safe ErrorResponse 검증."""
    class InvalidCitationP3Provider(ReasoningProvider):
        async def generate_structured(self, *args, **kwargs) -> ProviderResult:
            return ProviderResult(
                provider="test",
                requested_model="mock",
                actual_model="mock",
                structured_data={
                    "version": "1.0.0",
                    "status": "SUCCESS",
                    "drafts": [
                        {
                            "title": "가상 가설 수주 가능성",
                            "reason": "신규 사업장 개설 및 채용 진행",
                            "reasoning_chain": [
                                "E99 FACT: 가상 원문 정보",
                                "INTERPRETATION: 사업 확장 진행 중",
                                "DEMAND: 솔루션 도입 필요",
                            ],
                            "supporting_evidence": ["E99"],
                            "contradicting_evidence": [],
                            "questions": ["해당 솔루션 도입 계획이 있으신가요?"],
                        }
                    ],
                    "reasoning_summary": "E99 근거 추론",
                },
                success=True,
            )

    app_instance = create_app()
    with TestClient(app_instance) as client:
        orchestrator = BriefingOrchestrator(p3_provider=InvalidCitationP3Provider())
        app_instance.state.job_manager.set_orchestrator(orchestrator)

        res = client.post("/v1/briefings", json=_valid_payload_dict("가상기업 인용오류"))
        assert res.status_code == 202
        job_id = res.json()["job_id"]

        for _ in range(20):
            st = client.get(f"/v1/briefing-jobs/{job_id}").json()
            if st["status"] == "FAILED":
                assert st["error_code"] == "INVALID_CITATION"
                assert st["error_http_status"] == 422
                break

        result_res = client.get(f"/v1/briefings/{job_id}")
        assert result_res.status_code == 422
        data = result_res.json()
        assert data["error_code"] == "INVALID_CITATION"
        assert "detail" in data

