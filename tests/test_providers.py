import pytest
import httpx
from app.providers.mock import MockReasoningProvider
from app.providers.openai_compatible import OpenAICompatibleReasoningProvider
from app.domain.models import ProviderResult


@pytest.mark.asyncio
async def test_mock_provider_structured_output():
    """PRD Test 5: Mock Provider의 구조화 출력."""
    provider = MockReasoningProvider()

    result = await provider.generate_structured(
        task="briefing_generation",
        messages=[{"role": "user", "content": "Generate briefing"}],
        response_schema={"type": "object"},
        model="mock-model",
        timeout_s=30,
    )

    assert isinstance(result, ProviderResult)
    assert result.success is True
    assert result.provider == "mock"
    assert result.structured_data is not None
    assert "company" in result.structured_data
    assert "demand_hypotheses" in result.structured_data


@pytest.mark.asyncio
async def test_mock_provider_timeout_handling():
    """PRD Test 6: Provider timeout 처리."""
    provider = MockReasoningProvider(simulate_timeout=True)

    result = await provider.generate_structured(
        task="briefing_generation",
        messages=[{"role": "user", "content": "Generate briefing"}],
        response_schema={"type": "object"},
        model="mock-model",
        timeout_s=1,
    )

    assert isinstance(result, ProviderResult)
    assert result.success is False
    assert result.error is not None
    assert "timed out" in result.error
    assert result.error_code == "PROVIDER_TIMEOUT"


@pytest.mark.asyncio
async def test_openai_provider_timeout_handling():
    """Verify timeout handling in OpenAICompatibleReasoningProvider."""

    async def mock_handler(request):
        # Simulate timeout by raising httpx.TimeoutException
        raise httpx.TimeoutException("Connection timeout")

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = OpenAICompatibleReasoningProvider(http_client=client)
        result = await provider.generate_structured(
            task="test",
            messages=[],
            response_schema={},
            timeout_s=1,
        )

    assert result.success is False
    assert "timed out after 1 seconds" in result.error
    assert result.error_code == "PROVIDER_TIMEOUT"


@pytest.mark.asyncio
async def test_openai_provider_no_retry_on_4xx_client_error():
    """Verify that 4xx HTTP client/auth errors do NOT trigger retries."""
    call_count = 0

    async def mock_handler(request):
        nonlocal call_count
        call_count += 1
        return httpx.Response(401, json={"error": "Unauthorized"})

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = OpenAICompatibleReasoningProvider(
            max_retries=3,
            http_client=client,
        )
        result = await provider.generate_structured(
            task="test",
            messages=[],
            response_schema={},
        )

    assert call_count == 1  # Exactly 1 call, zero retries on 401 Unauthorized
    assert result.success is False
    assert "HTTP 401" in result.error
    assert result.error_code == "PROVIDER_AUTH_ERROR"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "error_code", "expected_calls"),
    [
        (401, "PROVIDER_AUTH_ERROR", 1),
        (403, "PROVIDER_AUTH_ERROR", 1),
        (400, "PROVIDER_BAD_REQUEST", 1),
        (422, "PROVIDER_BAD_REQUEST", 1),
        (500, "PROVIDER_SERVER_ERROR", 2),
    ],
)
async def test_openai_provider_http_error_codes(status, error_code, expected_calls):
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(status)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await OpenAICompatibleReasoningProvider(
            http_client=client, max_retries=1,
        ).generate_structured(task="test", messages=[], response_schema={})

    assert result.success is False
    assert result.error_code == error_code
    assert calls == expected_calls


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["not json", "null", "[]"])
async def test_openai_provider_invalid_structured_output(content):
    transport = httpx.MockTransport(lambda request: httpx.Response(
        200, json={"choices": [{"message": {"content": content}}]},
    ))
    async with httpx.AsyncClient(transport=transport) as client:
        result = await OpenAICompatibleReasoningProvider(
            http_client=client, max_retries=0,
        ).generate_structured(task="test", messages=[], response_schema={})

    assert result.success is False
    assert result.error_code == "PROVIDER_INVALID_JSON"


@pytest.mark.asyncio
async def test_openai_provider_missing_response_envelope():
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"choices": []}),
    )) as client:
        result = await OpenAICompatibleReasoningProvider(
            http_client=client, max_retries=0,
        ).generate_structured(task="test", messages=[], response_schema={})

    assert result.success is False
    assert result.error_code == "PROVIDER_INVALID_JSON"


@pytest.mark.asyncio
async def test_openai_provider_network_error_code():
    def fail(request):
        raise httpx.ConnectError("offline", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
        result = await OpenAICompatibleReasoningProvider(
            http_client=client, max_retries=0,
        ).generate_structured(task="test", messages=[], response_schema={})

    assert result.success is False
    assert result.error_code == "PROVIDER_NETWORK_ERROR"


@pytest.mark.asyncio
async def test_openai_provider_actual_model_extraction():
    """Verify actual_model is extracted from API response model field."""
    async def mock_handler(request):
        return httpx.Response(200, json={
            "model": "groq-llama-3.3-70b-real",
            "choices": [{"message": {"content": '{"status": "ok"}'}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20}
        })

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = OpenAICompatibleReasoningProvider(http_client=client)
        result = await provider.generate_structured(
            task="test",
            messages=[],
            response_schema={},
            model="auto/best-coding",
        )

    assert result.success is True
    assert result.requested_model == "auto/best-coding"
    assert result.actual_model == "groq-llama-3.3-70b-real"
