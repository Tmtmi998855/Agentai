import pytest
import httpx
import json
from pydantic import SecretStr
from app.domain.search_models import SearchRequest, SearchQuery, SearchResult
from app.providers.mock_search import MockSearchProvider
from app.providers.perplexity_search import PerplexitySearchProvider


@pytest.mark.asyncio
async def test_mock_search_provider_returns_raw_items():
    """Part G-1: Mock Search Provider 정상 결과."""
    provider = MockSearchProvider()
    req = SearchRequest(
        company_name="테스트기업",
        queries=[SearchQuery(query="테스트기업 뉴스")]
    )

    res = await provider.search(req)
    assert isinstance(res, SearchResult)
    assert res.success is True
    assert res.provider == "mock"
    assert len(res.items) == 3
    assert res.items[0].url.startswith("http")


@pytest.mark.asyncio
async def test_perplexity_provider_official_search_request_format():
    """Part G-2: Perplexity Search API (POST /search) 요청 경로 및 본문 검증."""
    captured_request = None
    captured_payload = None

    async def mock_handler(request):
        nonlocal captured_request, captured_payload
        captured_request = request
        captured_payload = json.loads(request.read().decode())
        return httpx.Response(200, json={
            "results": [
                {
                    "title": "현대렌탈 사옥 이전",
                    "url": "https://dart.fss.or.kr/001",
                    "snippet": "현대렌탈이 강남으로 사옥을 이전했습니다.",
                    "date": "2026-09-01"
                }
            ]
        })

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = PerplexitySearchProvider(
            api_key="pplx-key-123",
            http_client=client,
        )
        res = await provider.search(SearchRequest(company_name="현대렌탈"))

    assert res.success is True
    assert captured_request.url.path == "/search"
    assert captured_payload is not None
    assert "query" in captured_payload
    assert "max_results" in captured_payload
    assert len(res.items) == 1
    assert res.items[0].title == "현대렌탈 사옥 이전"
    assert res.items[0].url == "https://dart.fss.or.kr/001"
    assert res.items[0].snippet == "현대렌탈이 강남으로 사옥을 이전했습니다."
    assert res.items[0].published_at == "2026-09-01"


@pytest.mark.asyncio
async def test_perplexity_provider_missing_date_remains_none():
    """날짜 누락 시 published_at이 None으로 유지되는지 검증."""
    async def mock_handler(request):
        return httpx.Response(200, json={
            "results": [
                {
                    "title": "날짜 없는 기사",
                    "url": "https://example.com/no-date",
                    "snippet": "내용 스니펫"
                }
            ]
        })

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = PerplexitySearchProvider(
            api_key="pplx-key-123",
            http_client=client,
        )
        res = await provider.search(SearchRequest(company_name="테스트"))

    assert res.success is True
    assert len(res.items) == 1
    assert res.items[0].published_at is None


@pytest.mark.asyncio
async def test_perplexity_provider_empty_results_handling():
    """빈 검색 결과 처리 (success=True, items=[])."""
    async def mock_handler(request):
        return httpx.Response(200, json={"results": []})

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = PerplexitySearchProvider(
            api_key="pplx-key-123",
            http_client=client,
        )
        res = await provider.search(SearchRequest(company_name="듣보잡기업"))

    assert res.success is True
    assert len(res.items) == 0
    assert res.error is None


@pytest.mark.asyncio
async def test_perplexity_provider_excludes_missing_and_invalid_urls_without_fallback():
    async def mock_handler(request):
        return httpx.Response(200, json={
            "results": [
                {"title": "URL 누락", "snippet": "누락 스니펫"},
                {"title": "URL 무효", "url": "not-a-url", "snippet": "무효 스니펫"},
                {"title": "정상 결과", "url": "https://example.com/ok", "snippet": "정상 스니펫"},
            ]
        })

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = PerplexitySearchProvider(api_key="pplx-key-123", http_client=client)
        res = await provider.search(SearchRequest(company_name="테스트"))

    assert res.success is True
    assert [item.url for item in res.items] == ["https://example.com/ok"]
    assert [item.reason for item in res.excluded_items] == ["URL_MISSING", "URL_INVALID"]
    assert all(item.url is not None for item in res.items)


@pytest.mark.asyncio
async def test_perplexity_provider_timeout_handling():
    """Part G-3: timeout 변환."""
    async def mock_handler(request):
        raise httpx.TimeoutException("Search timeout")

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = PerplexitySearchProvider(
            api_key="secret-key",
            http_client=client,
            timeout_s=1,
        )
        res = await provider.search(SearchRequest(company_name="테스트"))

    assert res.success is False
    assert "timed out after 1 seconds" in res.error


@pytest.mark.asyncio
async def test_perplexity_provider_no_retry_on_4xx_client_error():
    """Part G-4: 비재시도 4xx."""
    call_count = 0

    async def mock_handler(request):
        nonlocal call_count
        call_count += 1
        return httpx.Response(401, json={"error": "Unauthorized API key"})

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = PerplexitySearchProvider(
            api_key="secret-key-123",
            max_retries=3,
            http_client=client,
        )
        res = await provider.search(SearchRequest(company_name="테스트"))

    assert call_count == 1  # No retry on 401
    assert res.success is False
    assert "HTTP 401" in res.error


@pytest.mark.asyncio
async def test_perplexity_provider_retries_on_429_rate_limit():
    """Part G-5: 429 제한 재시도."""
    call_count = 0

    async def mock_handler(request):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(429, headers={"Retry-After": "0.1"}, json={"error": "Rate limit"})
        return httpx.Response(200, json={
            "results": [
                {
                    "title": "공시 내용",
                    "url": "https://dart.fss.or.kr/example",
                    "snippet": "공시 내용 스니펫"
                }
            ]
        })

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = PerplexitySearchProvider(
            api_key="secret-key",
            max_retries=1,
            http_client=client,
        )
        res = await provider.search(SearchRequest(company_name="테스트"))

    assert call_count == 2
    assert res.success is True
    assert len(res.items) == 1


@pytest.mark.asyncio
async def test_perplexity_provider_retries_on_5xx_server_error():
    """Part G-6: 일시적 5xx 제한 재시도."""
    call_count = 0

    async def mock_handler(request):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(503, json={"error": "Service Unavailable"})
        return httpx.Response(200, json={
            "results": [
                {
                    "title": "복구 성공",
                    "url": "https://dart.fss.or.kr/503_fixed",
                    "snippet": "복구 성공 스니펫"
                }
            ]
        })

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = PerplexitySearchProvider(
            api_key="secret-key",
            max_retries=1,
            http_client=client,
        )
        res = await provider.search(SearchRequest(company_name="테스트"))

    assert call_count == 2
    assert res.success is True


@pytest.mark.asyncio
async def test_perplexity_api_key_not_exposed_in_errors():
    """Part G-7: API Key 비노출."""
    secret_key = "my-secret-perplexity-api-key-999"

    async def mock_handler(request):
        return httpx.Response(403, json={"error": "Forbidden"})

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = PerplexitySearchProvider(
            api_key=secret_key,
            http_client=client,
        )
        res = await provider.search(SearchRequest(company_name="테스트"))

    assert res.success is False
    assert secret_key not in res.error
    assert secret_key not in str(res.model_dump())


@pytest.mark.asyncio
async def test_mock_search_provider_distinguishes_empty_from_error():
    """Part G-8: 빈 검색결과와 API 실패 구분."""
    # Case 1: Empty results (success=True, items=[])
    empty_provider = MockSearchProvider(simulate_empty=True)
    res_empty = await empty_provider.search(SearchRequest(company_name="듣보잡기업"))
    assert res_empty.success is True
    assert len(res_empty.items) == 0
    assert res_empty.error is None

    # Case 2: API Error (success=False, error="...")
    error_provider = MockSearchProvider(simulate_error=True, error_message="API Key Invalid")
    res_err = await error_provider.search(SearchRequest(company_name="테스트기업"))
    assert res_err.success is False
    assert len(res_err.items) == 0
    assert "API Key Invalid" in res_err.error


@pytest.mark.integration
@pytest.mark.asyncio
async def test_perplexity_real_api_integration():
    """Integration test with real API key if available."""
    import os
    api_key = os.getenv("PERPLEXITY_API_KEY", "")
    if not api_key:
        pytest.skip("PERPLEXITY_API_KEY environment variable not set")

    provider = PerplexitySearchProvider(api_key=api_key)
    res = await provider.search(SearchRequest(company_name="삼성전자"))
    assert res.success is True
    assert len(res.items) > 0
