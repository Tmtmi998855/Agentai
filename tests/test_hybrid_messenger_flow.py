"""기획서 v2(메신저 + 웹 하이브리드) 흐름 검증: 템플릿 → 듀얼 리서치 → 질문 3선 → 저장 → 메신저 답장."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from app.core.exceptions import CitationIntegrityException
from app.domain.job_models import BriefingCreateRequest
from app.domain.models import (
    BriefingObject,
    CompanyEntity,
    CompanySnapshot,
    Evidence,
    ProviderResult,
)
from app.domain.sales_templates import SalesTemplateSelection, load_sales_template_catalog
from app.domain.strategic_questions import StrategicQuestionSet
from app.main import app
from app.services import agent_tools
from app.services.dual_research import (
    build_company_queries,
    build_industry_queries,
    evidence_scope,
    scope_tag,
)
from app.services.messenger_formatter import TELEGRAM_MAX_CHARS, format_messenger_briefing
from app.services.orchestrator import BriefingOrchestrator
from app.services.report_store import MemoryReportStore, ReportStoreException, SupabaseReportStore
from app.services.strategic_question_composer import StrategicQuestionComposerService

MOBILITY = SalesTemplateSelection(
    category_id="mobility",
    product_id="long_term_rental",
    value_prop_ids=["mobility_acquisition_tax", "mobility_expense"],
)


class StaticProvider:
    def __init__(self, response: dict):
        self.response = response

    async def generate_structured(self, **kwargs):
        return ProviderResult(provider="test", requested_model=kwargs["model"], actual_model="test",
                              structured_data=self.response)


def _confirmed(eid: str, scope: str) -> Evidence:
    ev = Evidence(evidence_id=eid, claim=f"{eid} 확인된 사실", publisher="공식", url=f"https://example.com/{eid}",
                  source_tier="A", relevance_tags=[scope_tag(scope)])
    ev.verify_raw(f"<p>{eid} 확인된 사실</p>")
    ev.confirm_fact(target_claim=f"{eid} 확인된 사실", supporting_excerpt=f"{eid} 확인된 사실",
                    verification_method="EXACT_EXCERPT_MATCH")
    return ev


def _questions(q1_ids, q2_ids, vp_id="mobility_expense") -> dict:
    return {
        "questions": [
            {"type": "COMPANY_ISSUE", "question": "최근 신규 공장 소식 보았는데요, 어떠세요?", "intent": "인지", "evidence_ids": q1_ids},
            {"type": "INDUSTRY_TREND", "question": "업계 원가 부담은 어떻게 체감하세요?", "intent": "공감", "evidence_ids": q2_ids},
            {"type": "SOLUTION_BRIDGE", "question": "차량 비용 처리 방식 고민은 없으세요?", "intent": "연결",
             "evidence_ids": [], "value_prop_id": vp_id},
        ]
    }


# ---------- 템플릿 ----------

def test_catalog_is_data_driven_and_valid():
    catalog = load_sales_template_catalog()
    assert {c.id for c in catalog.categories} >= {"mobility", "it_infra", "saas", "office_equipment"}
    assert {g.id for g in catalog.value_prop_groups} == {"COST", "TAX", "OPS"}


@pytest.mark.parametrize(
    "kwargs",
    [
        {"category_id": "unknown", "product_id": "long_term_rental", "value_prop_ids": ["mobility_expense"]},
        {"category_id": "mobility", "product_id": "groupware", "value_prop_ids": ["mobility_expense"]},
        {"category_id": "mobility", "product_id": "ev_fleet", "value_prop_ids": ["it_usage_billing"]},
        {"category_id": "mobility", "product_id": "ev_fleet", "value_prop_ids": []},
        {"category_id": "mobility", "product_id": "ev_fleet",
         "value_prop_ids": ["mobility_expense", "mobility_vat_refund", "mobility_off_balance", "mobility_admin_reduction"]},
        {"category_id": "mobility", "product_id": "ev_fleet", "value_prop_ids": ["mobility_expense", "mobility_expense"]},
    ],
)
def test_template_selection_rejects_invalid_combinations(kwargs):
    with pytest.raises(ValidationError):
        SalesTemplateSelection(**kwargs)


def test_from_template_builds_legacy_profile_for_existing_pipeline():
    req = BriefingCreateRequest.from_template("삼양패키징", MOBILITY, target_industry="포장재")
    assert req.sales_profile.product_service == "신차 장기렌터카"
    assert "손비 처리" in req.sales_profile.sales_goal
    assert req.target_industry == "포장재"


# ---------- 듀얼 리서치 ----------

def test_dual_research_queries_are_public_only():
    company_q = [q.query for q in build_company_queries("삼양패키징")]
    industry_q = [q.query for q in build_industry_queries("포장재/PET")]
    assert len(company_q) == 3 and all("삼양패키징" in q for q in company_q)
    assert len(industry_q) == 3 and all(q.startswith("포장재PET 산업") for q in industry_q)


# ---------- 질문 3선 계약 ----------

def test_question_set_requires_fixed_order():
    data = _questions([], [])
    data["questions"].reverse()
    with pytest.raises(ValidationError):
        StrategicQuestionSet.model_validate(data)


def test_solution_bridge_requires_value_prop():
    data = _questions([], [])
    data["questions"][2]["value_prop_id"] = None
    with pytest.raises(ValidationError):
        StrategicQuestionSet.model_validate(data)


@pytest.mark.parametrize(
    "q1_ids,q2_ids,vp_id",
    [
        (["E02"], [], "mobility_expense"),            # Q1이 산업 근거 인용
        ([], ["E01"], "mobility_expense"),            # Q2가 기업 근거 인용
        (["E99"], [], "mobility_expense"),            # 존재하지 않는 근거
        ([], [], "mobility_vat_refund"),              # 선택하지 않은 소구점
    ],
)
async def test_p5_integrity_fails_closed(q1_ids, q2_ids, vp_id):
    service = StrategicQuestionComposerService(StaticProvider(_questions(q1_ids, q2_ids, vp_id)))
    with pytest.raises(CitationIntegrityException):
        await service.compose_questions(
            company_name="테스트기업", industry="포장재", template=MOBILITY.resolve(),
            confirmed_evidences=[_confirmed("E01", "COMPANY"), _confirmed("E02", "INDUSTRY")],
        )


async def test_p5_server_recomputes_grounded():
    data = _questions(["E01"], [])
    data["questions"][1]["grounded"] = True  # LLM이 근거 없이 grounded라고 주장해도
    service = StrategicQuestionComposerService(StaticProvider(data))
    result = await service.compose_questions(
        company_name="테스트기업", industry="포장재", template=MOBILITY.resolve(),
        confirmed_evidences=[_confirmed("E01", "COMPANY")],
    )
    assert [q.grounded for q in result.questions] == [True, False, False]


# ---------- 오케스트레이터 E2E (Mock) ----------

async def test_orchestrator_template_flow_produces_scoped_questions():
    req = BriefingCreateRequest.from_template("삼양패키징", MOBILITY, target_industry="포장재")
    briefing = await BriefingOrchestrator().execute_pipeline(req)

    assert briefing.status == "SUCCESS"
    scopes = {s.evidence_id: s.scope for s in briefing.sources}
    assert "INDUSTRY" in scopes.values() and "COMPANY" in scopes.values()

    q1, q2, q3 = briefing.strategic_questions.questions
    assert q1.evidence_ids and all(scopes[e] == "COMPANY" for e in q1.evidence_ids)
    assert q2.evidence_ids and all(scopes[e] == "INDUSTRY" for e in q2.evidence_ids)
    assert q3.value_prop_id in MOBILITY.value_prop_ids
    assert briefing.validate_citations() == []


async def test_orchestrator_legacy_request_has_no_strategic_questions():
    req = BriefingCreateRequest.from_template("삼양패키징", MOBILITY)
    legacy = BriefingCreateRequest(company_name=req.company_name, sales_profile=req.sales_profile)
    briefing = await BriefingOrchestrator().execute_pipeline(legacy)
    assert briefing.strategic_questions is None
    assert all(s.scope is None for s in briefing.sources)


# ---------- 메신저 포맷 ----------

async def test_messenger_text_has_three_questions_and_link():
    req = BriefingCreateRequest.from_template("삼양패키징", MOBILITY, target_industry="포장재")
    briefing = await BriefingOrchestrator().execute_pipeline(req)
    text = format_messenger_briefing(briefing, "http://localhost:3000/report/abc")
    for label in ("Q1. [기업 이슈 인지]", "Q2. [산업 트렌드 공감]", "Q3. [솔루션 브리지]"):
        assert label in text
    assert text.endswith("http://localhost:3000/report/abc")
    assert "MOCK_VIRTUAL" in text


def test_messenger_text_truncation_keeps_link():
    briefing = BriefingObject(
        company=CompanyEntity(name="A", entity_confidence="HIGH"),
        company_snapshot=CompanySnapshot(summary="\n".join(["가" * 3000] * 3)),
        meeting_questions=["q1", "q2", "q3"],
    )
    text = format_messenger_briefing(briefing, "http://localhost:3000/report/x")
    assert len(text) <= TELEGRAM_MAX_CHARS
    assert text.endswith("http://localhost:3000/report/x")


# ---------- 에이전트 도구 + 저장소 ----------

async def test_agent_tools_require_profile_then_save_report():
    store = MemoryReportStore()
    with pytest.raises(agent_tools.AgentToolError) as exc:
        await agent_tools.create_meeting_briefing(store, "telegram", "1001", "삼양패키징")
    assert exc.value.error_code == "PROFILE_NOT_FOUND"

    saved = await agent_tools.save_sales_profile(store, "telegram", "1001", **MOBILITY.model_dump())
    assert saved["profile"]["product"] == "신차 장기렌터카"

    result = await agent_tools.create_meeting_briefing(
        store, "telegram", "1001", "삼양패키징", target_industry="포장재",
        report_base_url="http://localhost:3000/report/",
    )
    assert result["report_url"] == f"http://localhost:3000/report/{result['report_id']}"
    report = await store.get_report(result["report_id"])
    assert len(report.questions) == 3
    assert "포장재" in report.industry_summary
    assert result["messenger_text"].endswith(result["report_url"])


async def test_agent_tools_reject_invalid_template():
    with pytest.raises(agent_tools.AgentToolError) as exc:
        await agent_tools.save_sales_profile(MemoryReportStore(), "telegram", "1", "mobility", "groupware", ["x"])
    assert exc.value.error_code == "INVALID_TEMPLATE_SELECTION"


async def test_supabase_store_uses_upsert_and_hides_secret_on_error():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "POST" and request.url.path.endswith("/users"):
            body = json.loads(request.content)
            return httpx.Response(201, json=[{"id": "u-1", **body}])
        return httpx.Response(500, json={"message": "boom"})

    store = SupabaseReportStore("https://proj.supabase.co", SecretStr("service-secret"),
                                transport=httpx.MockTransport(handler))
    user = await store.upsert_user_profile("telegram", "1001", MOBILITY)
    assert user.template == MOBILITY
    req = calls[0]
    assert req.url.params["on_conflict"] == "messenger_type,messenger_user_id"
    assert "merge-duplicates" in req.headers["prefer"]
    assert req.headers["authorization"] == "Bearer service-secret"

    with pytest.raises(ReportStoreException) as exc:
        await store.get_report("r-1")
    assert "service-secret" not in exc.value.message


def test_supabase_store_requires_configuration():
    with pytest.raises(ReportStoreException):
        SupabaseReportStore("", SecretStr(""))


# ---------- HTTP API ----------

def test_sales_templates_endpoint_and_template_validation():
    client = TestClient(app)
    res = client.get("/v1/sales-templates")
    assert res.status_code == 200
    assert res.json()["categories"][0]["id"] == "mobility"

    req = BriefingCreateRequest.from_template("삼양패키징", MOBILITY).model_dump()
    req["sales_template"]["value_prop_ids"] = ["it_usage_billing"]
    bad = client.post("/v1/briefings", json=req)
    assert bad.status_code == 422
    assert bad.json()["error_code"] == "VALIDATION_ERROR"
