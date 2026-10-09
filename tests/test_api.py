import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request
from app.core.exceptions import ProviderAuthException, ProviderException, ProviderTimeoutException
from app.main import app, ah_there_exception_handler

client = TestClient(app)


def test_health_and_ready_endpoints():
    """PRD Test 8: '/health' 및 '/ready' 응답."""
    health_res = client.get("/health")
    assert health_res.status_code == 200
    health_json = health_res.json()
    assert health_json["status"] == "ok"
    assert "app_env" in health_json

    ready_res = client.get("/ready")
    assert ready_res.status_code == 200
    ready_json = ready_res.json()
    assert ready_json["status"] == "ready"
    assert "provider" in ready_json


def test_providers_config_api_key_hidden():
    """PRD Test 7: API Key 비노출."""
    config_res = client.get("/v1/config/providers")
    assert config_res.status_code == 200
    config_json = config_res.json()

    # Public config fields must be present
    assert "active_provider" in config_json
    assert "model" in config_json
    assert "base_url" in config_json
    assert "timeout_seconds" in config_json
    assert "max_retries" in config_json

    # API keys or secret fields MUST NOT be present
    assert "api_key" not in config_json
    assert "OPENAI_API_KEY" not in config_json
    assert "PERPLEXITY_API_KEY" not in config_json
    assert "secret" not in config_json

    # Verify no secret value appears in raw response string
    raw_text = config_res.text
    assert "mock-api-key" not in raw_text
    assert "your-api-key-here" not in raw_text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "status", "error_code"),
    [
        (ProviderAuthException("upstream SECRET_VALUE", detail={"token": "SECRET_VALUE"}), 502, "PROVIDER_AUTH_ERROR"),
        (ProviderException("upstream SECRET_VALUE", error_code="PROVIDER_BAD_REQUEST"), 502, "PROVIDER_BAD_REQUEST"),
        (ProviderException("upstream SECRET_VALUE", error_code="PROVIDER_SERVER_ERROR"), 502, "PROVIDER_SERVER_ERROR"),
        (ProviderException("upstream SECRET_VALUE", error_code="PROVIDER_INVALID_JSON"), 502, "PROVIDER_INVALID_JSON"),
        (ProviderException("upstream SECRET_VALUE", error_code="STRUCTURED_OUTPUT_MISSING"), 502, "STRUCTURED_OUTPUT_MISSING"),
        (ProviderTimeoutException("upstream SECRET_VALUE"), 504, "PROVIDER_TIMEOUT"),
    ],
)
async def test_provider_errors_have_safe_api_response(error, status, error_code):
    request = Request({"type": "http", "method": "GET", "path": "/"})
    response = await ah_there_exception_handler(request, error)

    assert response.status_code == status
    assert response.body.decode("utf-8").find("SECRET_VALUE") == -1
    assert error_code in response.body.decode("utf-8")


def test_unhandled_exception_500_response_redacts_private_marker_even_in_debug_mode():
    """unhandled Exception 발생 시 settings.DEBUG=True 상태에서도 SECRET_UNHANDLED_MARKER나 트레이스백을 노출하지 않고 500 ErrorResponse(INTERNAL_SERVER_ERROR)를 반환한다."""
    from app.core.config import settings
    from app.main import create_app

    old_debug = settings.DEBUG
    try:
        settings.DEBUG = True
        app_instance = create_app()

        @app_instance.get("/test-unhandled-secret-error")
        async def secret_error_route():
            raise RuntimeError("SECRET_UNHANDLED_MARKER")

        with TestClient(app_instance, raise_server_exceptions=False) as client:
            res = client.get("/test-unhandled-secret-error")
            assert res.status_code == 500
            assert res.headers["content-type"].startswith("application/json")
            data = res.json()
            assert data["error_code"] == "INTERNAL_SERVER_ERROR"
            assert data["message"] == "내부 처리 중 오류가 발생했습니다."
            assert data["detail"] == {}
            assert "SECRET_UNHANDLED_MARKER" not in res.text
            assert "Traceback" not in res.text
    finally:
        settings.DEBUG = old_debug


def test_ui_review_endpoint_returns_html_form_and_csp():
    """GET /ui-review가 200 text/html을 반환하고 폼·실제 API 경로가 포함되며 CSP connect-src는 동일 출처만 허용함을 검증한다."""
    res = client.get("/ui-review")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/html")
    text = res.text
    assert "company_name" in text
    assert "/v1/briefings" in text
    assert "/v1/briefing-jobs" in text
    assert "connect-src 'self'" in text
    assert "connect-src *" not in text
    assert "connect-src https:" not in text
