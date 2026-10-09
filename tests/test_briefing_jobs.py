import anyio
import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.core.exceptions import AhThereException
from app.domain.job_models import BriefingCreateRequest
from app.domain.models import BriefingObject
from app.main import app, create_app
from app.services.orchestrator import BriefingOrchestrator


def _valid_payload_dict(company_name: str = "가상기업 알파") -> dict:
    return {
        "company_name": company_name,
        "sales_profile": {
            "company": "가상기업 세일즈",
            "industry": "IT 솔루션",
            "product_service": "기업용 B2B 세일즈 솔루션",
            "target_customer": "중견패션기업",
            "sales_goal": "신규 도입 수주",
        },
        "meeting_context": {
            "department": "영업기획팀",
            "role": "팀장",
            "meeting_purpose": "솔루션 데모",
            "past_notes": "이전 미팅 참고 사항",
        },
    }


def test_lifespan_less_submission_rejected_with_503():
    """수명주기(lifespan)가 활성화되지 않은 상태에서의 작업 제출은 503 JOB_MANAGER_UNAVAILABLE 응답으로 거부된다."""
    app_instance = create_app()
    client = TestClient(app_instance)
    res = client.post("/v1/briefings", json=_valid_payload_dict())
    assert res.status_code == 503
    data = res.json()
    assert data["error_code"] == "JOB_MANAGER_UNAVAILABLE"


def test_app_instance_isolation_and_lifecycle_initialization():
    """서로 다른 두 인스턴스는 독립된 저장소와 수명주기를 가지며 격리된다."""
    app1 = create_app()
    app2 = create_app()

    with TestClient(app1) as client1:
        res1 = client1.post("/v1/briefings", json=_valid_payload_dict("가상기업 원"))
        assert res1.status_code == 202
        job_id1 = res1.json()["job_id"]

        with TestClient(app2) as client2:
            st_res2 = client2.get(f"/v1/briefing-jobs/{job_id1}")
            assert st_res2.status_code == 404
            assert st_res2.json()["error_code"] == "JOB_NOT_FOUND"

            res2 = client2.post("/v1/briefings", json=_valid_payload_dict("가상기업 투"))
            assert res2.status_code == 202
            job_id2 = res2.json()["job_id"]
            assert job_id1 != job_id2


def test_unexpected_500_json_redaction_on_private_marker():
    """예상치 못한 예외 발생 시 비공개 마커나 내부 민감 정보를 노출하지 않고 500 JSON으로 정화하여 응답한다."""
    app_instance = create_app()

    class FailingOrchestrator(BriefingOrchestrator):
        async def execute_pipeline(self, request_data: BriefingCreateRequest) -> BriefingObject:
            raise RuntimeError("REPRO_PRIVATE_MARKER")

    with TestClient(app_instance, raise_server_exceptions=False) as client:
        app_instance.state.job_manager.set_orchestrator(FailingOrchestrator())

        res = client.post("/v1/briefings", json=_valid_payload_dict("가상기업 에러"))
        assert res.status_code == 202
        job_id = res.json()["job_id"]

        for _ in range(20):
            st = client.get(f"/v1/briefing-jobs/{job_id}").json()
            if st["status"] == "FAILED":
                break

        result_res = client.get(f"/v1/briefings/{job_id}")
        assert result_res.status_code == 500
        assert result_res.headers["content-type"].startswith("application/json")
        data = result_res.json()
        assert data["error_code"] == "INTERNAL_SERVER_ERROR"
        assert "REPRO_PRIVATE_MARKER" not in result_res.text


@pytest.mark.asyncio
async def test_deterministic_running_status_observation_with_event_gate():
    """명시적 anyio.sleep 없이 AnyIO 이벤트를 활용하여 RUNNING 상태 및 409 Conflict를 결정론적으로 검증한다."""
    app_instance = create_app()
    gate = anyio.Event()

    async with app_instance.router.lifespan_context(app_instance):
        manager = app_instance.state.job_manager
        orchestrator = BriefingOrchestrator(step_gate_event=gate)
        manager.set_orchestrator(orchestrator)

        req = BriefingCreateRequest(**_valid_payload_dict("가상기업 게이트"))
        sub_resp = manager.submit_job(req)
        job_id = sub_resp.job_id

        await anyio.lowlevel.checkpoint()

        st_res = manager.get_job_status(job_id)
        assert st_res.status == "RUNNING"

        with pytest.raises(AhThereException) as exc_info:
            manager.get_briefing_result(job_id)
        assert exc_info.value.error_code == "JOB_NOT_COMPLETED"

        gate.set()

        with anyio.fail_after(2.0):
            while True:
                await anyio.lowlevel.checkpoint()
                st_res_after = manager.get_job_status(job_id)
                if st_res_after.status == "COMPLETED":
                    break
        assert st_res_after.status == "COMPLETED"


@pytest.mark.asyncio
async def test_asgi_202_response_before_gate_release_returns_409():
    """실제 HTTP 202가 게이트 해제 전에 응답하고 완료 전 GET 결과가 409인 경우를 ASGITransport+앱 lifespan+AnyIO events로 추가 검증한다."""
    app_instance = create_app()
    gate = anyio.Event()

    async with app_instance.router.lifespan_context(app_instance):
        orchestrator = BriefingOrchestrator(step_gate_event=gate)
        app_instance.state.job_manager.set_orchestrator(orchestrator)

        async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://test") as ac:
            post_res = await ac.post("/v1/briefings", json=_valid_payload_dict("가상기업 게이트409"))
            assert post_res.status_code == 202
            job_id = post_res.json()["job_id"]

            await anyio.lowlevel.checkpoint()

            get_res = await ac.get(f"/v1/briefings/{job_id}")
            assert get_res.status_code == 409
            assert get_res.json()["error_code"] == "JOB_NOT_COMPLETED"

            gate.set()

            with anyio.fail_after(2.0):
                while True:
                    await anyio.lowlevel.checkpoint()
                    st_res = (await ac.get(f"/v1/briefing-jobs/{job_id}")).json()
                    if st_res["status"] == "COMPLETED":
                        break

            final_res = await ac.get(f"/v1/briefings/{job_id}")
            assert final_res.status_code == 200


@pytest.mark.asyncio
async def test_lifespan_exit_cancels_running_job_as_failed_job_cancelled():
    """종료 event wait 작업을 bounded lifespan exit로 cancel하고 FAILED/JOB_CANCELLED로 기록되는지 및 다음 lifespan store 초기화를 검증한다."""
    app_instance = create_app()
    gate = anyio.Event()

    async with app_instance.router.lifespan_context(app_instance):
        orchestrator = BriefingOrchestrator(step_gate_event=gate)
        app_instance.state.job_manager.set_orchestrator(orchestrator)

        req = BriefingCreateRequest(**_valid_payload_dict("가상기업 취소"))
        sub_resp = app_instance.state.job_manager.submit_job(req)
        job_id = sub_resp.job_id

        await anyio.lowlevel.checkpoint()
        st_res = app_instance.state.job_manager.get_job_status(job_id)
        assert st_res.status == "RUNNING"

    # lifespan exit cancels task group -> set_failed records FAILED / JOB_CANCELLED
    st_cancelled = app_instance.state.job_manager.get_job_status(job_id)
    assert st_cancelled.status == "FAILED"
    assert st_cancelled.error_code == "JOB_CANCELLED"
    assert st_cancelled.error_http_status == 503

    # 검증: 같은 app의 다음 lifespan 시작 시 store 초기화 확인
    async with app_instance.router.lifespan_context(app_instance):
        with pytest.raises(AhThereException) as exc:
            app_instance.state.job_manager.get_job_status(job_id)
        assert exc.value.error_code == "JOB_NOT_FOUND"


def test_unknown_job_and_briefing_id_returns_404():
    with TestClient(app) as client:
        unknown_id = "00000000-0000-0000-0000-000000000000"
        st_res = client.get(f"/v1/briefing-jobs/{unknown_id}")
        assert st_res.status_code == 404
        assert st_res.json()["error_code"] == "JOB_NOT_FOUND"

        res = client.get(f"/v1/briefings/{unknown_id}")
        assert res.status_code == 404
        assert res.json()["error_code"] == "BRIEFING_NOT_FOUND"


def test_status_and_result_snapshot_mutation_prevention():
    """status/result 스냅샷 변경 시 내부 저장소 데이터가 변조되지 않는지 확인한다."""
    with TestClient(app) as client:
        res = client.post("/v1/briefings", json=_valid_payload_dict("가상기업 변조"))
        job_id = res.json()["job_id"]

        for _ in range(20):
            if client.get(f"/v1/briefing-jobs/{job_id}").json()["status"] == "COMPLETED":
                break

        st = app.state.job_manager.get_job_status(job_id)
        st.status = "FAILED"
        st_check = app.state.job_manager.get_job_status(job_id)
        assert st_check.status == "COMPLETED"

        briefing1 = app.state.job_manager.get_briefing_result(job_id)
        briefing1.company.name = "MUTATED_NAME"

        briefing2 = app.state.job_manager.get_briefing_result(job_id)
        assert briefing2.company.name != "MUTATED_NAME"
        assert briefing2.company.name == "가상기업 변조"

        with pytest.raises(AhThereException) as exc:
            app.state.job_manager.store.set_completed(job_id, briefing2)
        assert exc.value.error_code == "JOB_ALREADY_COMPLETED"


def test_bounded_job_store_capacity_limit_503():
    """Job store 용량 제한을 초과하는 요청에 대해 503 JOB_STORE_FULL을 반환한다."""
    app_instance = create_app()

    with TestClient(app_instance) as client:
        manager = app_instance.state.job_manager
        manager.store.max_capacity = 2

        res1 = client.post("/v1/briefings", json=_valid_payload_dict("가상기업 1"))
        assert res1.status_code == 202
        res2 = client.post("/v1/briefings", json=_valid_payload_dict("가상기업 2"))
        assert res2.status_code == 202

        res3 = client.post("/v1/briefings", json=_valid_payload_dict("가상기업 3"))
        assert res3.status_code == 503
        assert res3.json()["error_code"] == "JOB_STORE_FULL"


def test_input_validation_empty_whitespace_overlength_extra():
    """입력값 검증: 빈 문자열, 공백 전용, 길이 초과 및 추가 필드가 전달된 경우 422 오류를 반환한다."""
    with TestClient(app) as client:
        # 1. Empty company_name
        p1 = _valid_payload_dict("")
        res1 = client.post("/v1/briefings", json=p1)
        assert res1.status_code == 422

        # 2. Whitespace-only company_name
        p2 = _valid_payload_dict("   ")
        res2 = client.post("/v1/briefings", json=p2)
        assert res2.status_code == 422

        # 3. Overlength company_name (>100 chars)
        p3 = _valid_payload_dict("가상기업_" + "A" * 100)
        res3 = client.post("/v1/briefings", json=p3)
        assert res3.status_code == 422

        # 4. Extra root field
        p4 = _valid_payload_dict("가상기업 필드")
        p4["forbidden_extra"] = "value"
        res4 = client.post("/v1/briefings", json=p4)
        assert res4.status_code == 422

        # 5. Extra profile field
        p5 = _valid_payload_dict("가상기업 프로필")
        p5["sales_profile"]["injected"] = "bad"
        res5 = client.post("/v1/briefings", json=p5)
        assert res5.status_code == 422


def test_sales_profile_required_empty_overlength_meeting_context_over_500():
    """영업 프로필 필수 항목 빈값/과대길이 및 MeetingContext 500자 초과 검증 실패를 테스트한다."""
    with TestClient(app) as client:
        # 1. Empty product_service
        p1 = _valid_payload_dict("가상기업 프로필1")
        p1["sales_profile"]["product_service"] = ""
        res1 = client.post("/v1/briefings", json=p1)
        assert res1.status_code == 422

        # 2. Overlength sales_goal (>200 chars)
        p2 = _valid_payload_dict("가상기업 프로필2")
        p2["sales_profile"]["sales_goal"] = "G" * 201
        res2 = client.post("/v1/briefings", json=p2)
        assert res2.status_code == 422

        # 3. MeetingContext past_notes > 500 chars
        p3 = _valid_payload_dict("가상기업 프로필3")
        p3["meeting_context"]["past_notes"] = "N" * 501
        res3 = client.post("/v1/briefings", json=p3)
        assert res3.status_code == 422


@pytest.mark.parametrize(
    "payload_modifier, marker",
    [
        # 1. meeting_context.past_notes 500자 초과 (비공개 마커 포함)
        (
            lambda p, m: p["meeting_context"].update({"past_notes": f"{m}_" + ("x" * 500)}),
            "PRIVATE_MARKER_PAST_NOTES",
        ),
        # 2. sales_profile.company 200자 초과 (비공개 마커 포함)
        (
            lambda p, m: p["sales_profile"].update({"company": f"{m}_" + ("y" * 200)}),
            "PRIVATE_MARKER_SALES_COMPANY",
        ),
        # 3. company_name 빈 문자열 (다른 필드에 비공개 마커 포함)
        (
            lambda p, m: (p.update({"company_name": ""}), p["meeting_context"].update({"past_notes": m})),
            "PRIVATE_MARKER_EMPTY_COMPANY_NAME",
        ),
        # 4. company_name 100자 초과 (비공개 마커 포함)
        (
            lambda p, m: p.update({"company_name": f"{m}_" + ("z" * 100)}),
            "PRIVATE_MARKER_OVERLENGTH_COMPANY_NAME",
        ),
        # 5. 루트 및 프로필 추가 필드(extra) 전달 시 마커 포함
        (
            lambda p, m: p.update({"forbidden_extra_marker": m}),
            "PRIVATE_MARKER_EXTRA_FIELD",
        ),
    ],
)
def test_input_validation_422_redacts_private_markers_on_post(payload_modifier, marker):
    """POST /v1/briefings 요청 시 meeting_context.past_notes, sales_profile.company, company_name 등의 입력값 검증 실패(422) 상황에서 비공개 마커, PII 및 raw 입력 원문이 노출되지 않고 정화된 422 JSON이 반환되는지 실제 HTTP POST로 검증한다."""
    payload = _valid_payload_dict()
    payload_modifier(payload, marker)

    with TestClient(app) as client:
        res = client.post("/v1/briefings", json=payload)
        assert res.status_code == 422
        assert res.headers["content-type"].startswith("application/json")
        data = res.json()
        assert data["error_code"] == "VALIDATION_ERROR"
        assert data["message"] == "요청 입력값 검증에 실패했습니다."
        assert data["detail"] == {}
        assert marker not in res.text


@pytest.mark.parametrize("field_name", ["department", "role", "meeting_purpose", "past_notes"])
def test_meeting_context_whitespace_only_rejected_422(field_name):
    """meeting_context의 department/role/meeting_purpose/past_notes를 각각 공백 전용으로 POST하면 422 VALIDATION_ERROR, detail={}, 입력 원문 미노출을 단언한다."""
    payload = _valid_payload_dict()
    payload["meeting_context"][field_name] = "   "

    with TestClient(app) as client:
        res = client.post("/v1/briefings", json=payload)
        assert res.status_code == 422
        assert res.headers["content-type"].startswith("application/json")
        data = res.json()
        assert data["error_code"] == "VALIDATION_ERROR"
        assert data["message"] == "요청 입력값 검증에 실패했습니다."
        assert data["detail"] == {}


def test_meeting_context_missing_or_null_allowed_202():
    """meeting_context 누락 또는 null(None)은 202 허용된다."""
    with TestClient(app) as client:
        # 1. meeting_context 누락 (omitted)
        payload1 = _valid_payload_dict()
        del payload1["meeting_context"]
        res1 = client.post("/v1/briefings", json=payload1)
        assert res1.status_code == 202

        # 2. meeting_context = null (None)
        payload2 = _valid_payload_dict()
        payload2["meeting_context"] = None
        res2 = client.post("/v1/briefings", json=payload2)
        assert res2.status_code == 202

        # 3. meeting_context 내부 필드가 모두 null
        payload3 = _valid_payload_dict()
        payload3["meeting_context"] = {
            "department": None,
            "role": None,
            "meeting_purpose": None,
            "past_notes": None,
        }
        res3 = client.post("/v1/briefings", json=payload3)
        assert res3.status_code == 202

