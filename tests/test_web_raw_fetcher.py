import pytest
import httpx
from app.domain.models import Evidence
from app.services.web_raw_fetcher import (
    WebRawFetcher,
    SSRFFilter,
    SSRFViolationException,
)


@pytest.mark.asyncio
async def test_web_raw_fetcher_html_success():
    """Case 1: Normal HTML page fetch success -> status becomes RAW_VERIFIED (NOT FACT_CONFIRMED!)."""
    evidence = Evidence(
        evidence_id="E01",
        claim="테스트기업 강남 사옥 이전 공시",
        publisher="금융감독원",
        url="https://dart.fss.or.kr/001",
        source_tier="A",
        status="CLASSIFIED"
    )

    fetcher = WebRawFetcher()
    html_fixture = "<html><body><h1>테스트기업 공시</h1><p>서울 강남 사옥 이전 완료 내용</p></body></html>"

    result = await fetcher.fetch_and_verify_evidence(evidence, custom_raw_html=html_fixture)

    assert result.success is True
    assert result.status_code == 200
    assert "서울 강남 사옥 이전 완료 내용" in evidence.verified_raw_content
    # CRITICAL SECURITY BOUNDARY: Raw fetch success MUST set status to RAW_VERIFIED, NOT FACT_CONFIRMED!
    assert evidence.status == "RAW_VERIFIED"
    assert evidence.is_confirmed_fact is False


def test_web_raw_fetcher_ssrf_blocked_localhost_and_private_ips():
    """Case 2: SSRF defense blocks localhost, 127.0.0.1, 169.254.169.254, private IPs, and IPv4-mapped IPv6 bypasses."""
    # 1. Loopback hostname
    with pytest.raises(SSRFViolationException, match="Forbidden"):
        SSRFFilter.resolve_and_validate_ip("localhost")

    # 2. Loopback IPv4
    with pytest.raises(SSRFViolationException, match="Forbidden IP"):
        SSRFFilter.resolve_and_validate_ip("127.0.0.1")

    # 3. Link-Local / AWS IMDS
    with pytest.raises(SSRFViolationException, match="Forbidden IP"):
        SSRFFilter.resolve_and_validate_ip("169.254.169.254")

    # 4. Private Class A
    with pytest.raises(SSRFViolationException, match="Forbidden IP"):
        SSRFFilter.resolve_and_validate_ip("10.0.0.1")

    # 5. Unsupported Scheme (file://)
    with pytest.raises(SSRFViolationException, match="Unsupported scheme"):
        SSRFFilter.validate_url_scheme("file:///etc/passwd")

    # 6. IPv4-mapped IPv6 CGNAT bypass
    with pytest.raises(SSRFViolationException, match="Forbidden IP|restricted network"):
        SSRFFilter.resolve_and_validate_ip("::ffff:100.64.0.1")

    # 7. IPv4-mapped IPv6 Loopback bypass
    with pytest.raises(SSRFViolationException, match="Forbidden IP"):
        SSRFFilter.resolve_and_validate_ip("::ffff:127.0.0.1")

    # 8. IPv4-mapped IPv6 Link-Local bypass
    with pytest.raises(SSRFViolationException, match="Forbidden IP"):
        SSRFFilter.resolve_and_validate_ip("::ffff:169.254.169.254")


@pytest.mark.asyncio
async def test_web_raw_fetcher_ssrf_redirect_to_private_ip_blocked():
    """Case 3: Redirect to private IP (127.0.0.1) is blocked during hop validation."""
    async def mock_handler(request):
        # Redirects to local AWS Metadata IP
        return httpx.Response(302, headers={"Location": "http://169.254.169.254/latest/meta-data/"})

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        fetcher = WebRawFetcher(http_client=client, allow_live_fetch=True)
        # Mock public domain initial resolution
        # Will pass initial scheme check, but fail on redirect hop to 169.254.169.254
        result = await fetcher._safe_http_fetch("https://example.com/redirect-to-metadata")

    assert result.success is False
    assert result.status_code in (400, 500)
    assert "SSRF Violation" in result.error_message or "Forbidden IP" in result.error_message


@pytest.mark.asyncio
async def test_web_raw_fetcher_404_not_found():
    """Case 4: 404 HTTP Error -> returns failure and does NOT transition status to RAW_VERIFIED."""
    evidence = Evidence(
        evidence_id="E02",
        claim="존재하지 않는 공시",
        publisher="출처",
        url="https://example.com/404-page",
        source_tier="B",
        status="CLASSIFIED"
    )

    async def mock_handler(request):
        return httpx.Response(404)

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        fetcher = WebRawFetcher(http_client=client, allow_live_fetch=True)

        # Mock public IP DNS resolution
        import unittest.mock as mock
        with mock.patch.object(SSRFFilter, "resolve_and_validate_ip", return_value="93.184.216.34"):
            result = await fetcher.fetch_and_verify_evidence(evidence)

    assert result.success is False
    assert result.status_code == 404
    assert evidence.status == "CLASSIFIED"  # Remains unverified!
    assert evidence.verified_raw_content is None


@pytest.mark.asyncio
async def test_web_raw_fetcher_timeout_handling():
    """Case 5: Timeout handling -> returns failure gracefully."""
    async def mock_handler(request):
        raise httpx.TimeoutException("Connection timed out")

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        fetcher = WebRawFetcher(http_client=client, allow_live_fetch=True)
        import unittest.mock as mock
        with mock.patch.object(SSRFFilter, "resolve_and_validate_ip", return_value="93.184.216.34"):
            result = await fetcher._safe_http_fetch("https://example.com/timeout")

    assert result.success is False
    assert "Fetch failed" in result.error_message or "timed out" in result.error_message


@pytest.mark.asyncio
async def test_web_raw_fetcher_oversized_response_blocked():
    """Case 6: Response body exceeding 5MB max bytes limit is blocked (413)."""
    large_content = "A" * (6 * 1024 * 1024)  # 6MB

    async def mock_handler(request):
        return httpx.Response(200, text=large_content)

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        fetcher = WebRawFetcher(http_client=client, allow_live_fetch=True)
        import unittest.mock as mock
        with mock.patch.object(SSRFFilter, "resolve_and_validate_ip", return_value="93.184.216.34"):
            result = await fetcher._safe_http_fetch("https://example.com/large")

    assert result.success is False
    assert result.status_code == 413
    assert "exceeds limit" in result.error_message


@pytest.mark.asyncio
async def test_web_raw_fetcher_unsupported_pdf_content_type():
    """Case 7: Unsupported Content Type (application/pdf) returns 415 unsupported."""
    async def mock_handler(request):
        return httpx.Response(200, headers={"Content-Type": "application/pdf"}, content=b"%PDF-1.4...")

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        fetcher = WebRawFetcher(http_client=client, allow_live_fetch=True)
        import unittest.mock as mock
        with mock.patch.object(SSRFFilter, "resolve_and_validate_ip", return_value="93.184.216.34"):
            result = await fetcher._safe_http_fetch("https://example.com/doc.pdf")

    assert result.success is False
    assert result.status_code == 415
    assert "PDF requires PyMuPDF converter" in result.error_message


@pytest.mark.asyncio
async def test_pinned_network_backend_dns_rebinding_defense():
    """Verify PinnedNetworkBackend forces socket connection ONLY to validated IP, preventing DNS Rebinding TOCTOU."""
    import httpcore
    from app.services.web_raw_fetcher import PinnedNetworkBackend

    captured_connect_hosts = []

    class MockBaseBackend(httpcore.AsyncNetworkBackend):
        async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
            captured_connect_hosts.append(host)
            raise httpcore.ConnectError(f"Mock connect to {host}:{port}")

    mock_base = MockBaseBackend()
    # Pin transport to pre-validated public IP "93.184.216.34"
    pinned = PinnedNetworkBackend(pinned_ip="93.184.216.34", base_backend=mock_base)

    # Simulate secondary DNS resolution attempt during connect_tcp for attacker domain
    try:
        await pinned.connect_tcp(host="attacker-rebound-to-private-ip.com", port=80)
    except httpcore.ConnectError:
        pass

    # CRITICAL: PinnedNetworkBackend MUST force connection to "93.184.216.34", ignoring attacker domain secondary DNS lookup!
    assert len(captured_connect_hosts) == 1
    assert captured_connect_hosts[0] == "93.184.216.34"


@pytest.mark.asyncio
async def test_injected_real_client_creates_isolated_hop_without_mutating_shared_client():
    """Verify injected real AsyncClient creates isolated per-hop client without mutating shared client state."""
    import unittest.mock as mock

    transport = httpx.AsyncHTTPTransport()
    async with httpx.AsyncClient(transport=transport, follow_redirects=False) as client:
        original_backend = getattr(client._transport._pool, "_network_backend", None)
        fetcher = WebRawFetcher(http_client=client, allow_live_fetch=True)

        with mock.patch.object(SSRFFilter, "resolve_and_validate_ip", return_value="93.184.216.34"):
            with mock.patch.object(httpx.AsyncClient, "get", side_effect=httpx.ConnectError("Mock block")) as mock_get:
                result = await fetcher._safe_http_fetch("https://example.com/isolated-test")

        # Shared client's backend MUST NOT be mutated!
        current_backend = getattr(client._transport._pool, "_network_backend", None)
        assert current_backend == original_backend
        assert result.success is False


def test_injected_client_with_follow_redirects_true_rejected():
    """Verify that an injected client with follow_redirects=True is rejected."""
    client = httpx.AsyncClient(follow_redirects=True)
    with pytest.raises(SSRFViolationException, match="follow_redirects=False"):
        WebRawFetcher(http_client=client)


def test_injected_client_with_mounts_rejected():
    """Verify that an injected client with custom mounts/proxies is rejected."""
    client = httpx.AsyncClient(mounts={"https://": httpx.AsyncHTTPTransport()})
    with pytest.raises(SSRFViolationException, match="mounts or proxies"):
        WebRawFetcher(http_client=client)


@pytest.mark.asyncio
async def test_mock_transport_redirect_hop_observation_and_private_blocking():
    """Observes redirect hops without external network calls and blocks private redirect targets."""
    observed_hops = []

    async def mock_handler(request):
        observed_hops.append(str(request.url))
        if str(request.url) == "https://public-site.com/start":
            return httpx.Response(302, headers={"Location": "https://forbidden-internal.com/target"})
        return httpx.Response(200, text="Internal Secret Page")

    def mock_dns_resolver(hostname):
        if hostname == "public-site.com":
            return "93.184.216.34"  # Valid public IP
        if hostname == "forbidden-internal.com":
            raise SSRFViolationException("Forbidden IP address: 10.0.0.1")
        raise SSRFViolationException(f"Unknown host: {hostname}")

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport, follow_redirects=False) as client:
        fetcher = WebRawFetcher(http_client=client, allow_live_fetch=True)
        import unittest.mock as mock
        with mock.patch.object(SSRFFilter, "resolve_and_validate_ip", side_effect=mock_dns_resolver):
            result = await fetcher._safe_http_fetch("https://public-site.com/start")

    # Hop 1 (public-site.com) was fetched. Hop 2 (forbidden-internal.com) was blocked at DNS/SSRF resolution BEFORE HTTP fetch!
    assert len(observed_hops) == 1
    assert observed_hops[0] == "https://public-site.com/start"
    assert result.success is False
    assert "SSRF Violation" in result.error_message


@pytest.mark.asyncio
async def test_concurrent_fetches_with_shared_client_no_race_condition():
    """Verify multiple concurrent fetches sharing the same client complete safely without pool corruption."""
    import asyncio

    async def mock_handler(request):
        return httpx.Response(200, text=f"<html><body>Response for {request.url}</body></html>")

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport, follow_redirects=False) as client:
        fetcher = WebRawFetcher(http_client=client, allow_live_fetch=True)
        import unittest.mock as mock
        with mock.patch.object(SSRFFilter, "resolve_and_validate_ip", return_value="93.184.216.34"):
            tasks = [
                fetcher._safe_http_fetch(f"https://example.com/page-{i}")
                for i in range(5)
            ]
            results = await asyncio.gather(*tasks)

    assert len(results) == 5
    assert all(r.success is True for r in results)


def test_injected_client_unsupported_transport_rejected():
    """Verify that custom arbitrary transport classes are explicitly rejected."""
    class CustomArbitraryTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            return httpx.Response(200)

    client = httpx.AsyncClient(transport=CustomArbitraryTransport(), follow_redirects=False)
    with pytest.raises(SSRFViolationException, match="Unsupported transport type"):
        WebRawFetcher(http_client=client)


@pytest.mark.asyncio
async def test_sensitive_and_custom_auth_headers_stripped_from_mock_request():
    """Verify X-Auth-Token, X-Internal-Api-Key, Authorization, Cookie, and custom Host headers are stripped from public web requests."""
    captured_request_headers = {}

    async def mock_handler(request):
        captured_request_headers.update(dict(request.headers))
        return httpx.Response(200, text="Public Content")

    transport = httpx.MockTransport(mock_handler)
    injected_headers = {
        "Authorization": "Bearer SECRET_JWT_TOKEN",
        "X-Auth-Token": "SECRET_AUTH_TOKEN_VALUE",
        "X-Internal-Api-Key": "SECRET_INTERNAL_KEY_VALUE",
        "Cookie": "session=SECRET_COOKIE_ID",
        "Proxy-Authorization": "Basic SECRET_PROXY",
        "X-Api-Key": "SECRET_KEY",
        "Host": "spoofed-internal-host.local",
        "Custom-Unsafe-Header": "ShouldBeDisallowed",
        "Accept-Language": "ko-KR",
        "Accept": "text/html",
    }
    async with httpx.AsyncClient(transport=transport, headers=injected_headers, follow_redirects=False) as client:
        fetcher = WebRawFetcher(http_client=client, allow_live_fetch=True)
        import unittest.mock as mock
        with mock.patch.object(SSRFFilter, "resolve_and_validate_ip", return_value="93.184.216.34"):
            result = await fetcher._safe_http_fetch("https://public-web-site.com/data")

    assert result.success is True

    # 1. Sensitive and custom authentication headers MUST NOT be present in MockTransport request!
    assert "authorization" not in captured_request_headers
    assert "x-auth-token" not in captured_request_headers
    assert "x-internal-api-key" not in captured_request_headers
    assert "cookie" not in captured_request_headers
    assert "proxy-authorization" not in captured_request_headers
    assert "x-api-key" not in captured_request_headers
    assert "custom-unsafe-header" not in captured_request_headers

    # 2. User-specified custom Host header MUST NOT be passed (HTTPX sets real target host "public-web-site.com")
    assert captured_request_headers.get("host") == "public-web-site.com"

    # 3. ONLY safe, whitelisted standard headers are preserved
    assert captured_request_headers.get("accept-language") == "ko-KR"
    assert captured_request_headers.get("accept") == "text/html"
    assert "user-agent" in captured_request_headers


@pytest.mark.asyncio
async def test_concurrent_fetches_different_hosts_fake_network_backend_connects_to_verified_ips():
    """
    Verify concurrent requests to different hosts each connect strictly to their verified target IP via fake network backend.
    Observed bindings:
      - host-a.com -> 93.184.216.34:443 (Public IPv4 address - example.com RIPE block)
      - host-b.com -> 1.1.1.1:443 (Public IPv4 address - Cloudflare public DNS global IP)
    This test asserts the exact 1-to-1 mapping (original_host -> pinned_ip:port) and would fail if mappings were swapped.
    """
    import asyncio
    import httpcore
    import unittest.mock as mock
    from app.services.web_raw_fetcher import PinnedNetworkBackend

    captured_bindings = []

    class FakeNetworkBackend(httpcore.AsyncNetworkBackend):
        async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
            raise httpcore.ConnectError(f"Fake network connection blocked to {host}:{port}")

    orig_connect_tcp = PinnedNetworkBackend.connect_tcp

    async def spy_pinned_connect_tcp(self, host, port, **kwargs):
        captured_bindings.append((host, self.pinned_ip, port))
        return await orig_connect_tcp(self, host, port, **kwargs)

    def mock_dns_resolver(hostname):
        if hostname == "host-a.com":
            return "93.184.216.34"  # Public IPv4 (RIPE example.com)
        if hostname == "host-b.com":
            return "1.1.1.1"  # Public IPv4 (Cloudflare DNS global IP)
        raise SSRFViolationException(f"Unknown host: {hostname}")

    base_backend = FakeNetworkBackend()
    transport = httpx.AsyncHTTPTransport()
    # Inject fake network backend into AsyncHTTPTransport pool
    transport._pool._network_backend = base_backend

    async with httpx.AsyncClient(transport=transport, follow_redirects=False) as client:
        fetcher = WebRawFetcher(http_client=client, allow_live_fetch=True)
        with mock.patch.object(SSRFFilter, "resolve_and_validate_ip", side_effect=mock_dns_resolver):
            with mock.patch.object(PinnedNetworkBackend, "connect_tcp", spy_pinned_connect_tcp):
                tasks = [
                    fetcher._safe_http_fetch("https://host-a.com/page1"),
                    fetcher._safe_http_fetch("https://host-b.com/page2"),
                ]
                results = await asyncio.gather(*tasks)

    # Both requests fail with ConnectError as expected from FakeNetworkBackend
    assert len(results) == 2
    assert all(r.success is False for r in results)

    # CRITICAL: Verify exact 1-to-1 mapping (original_host -> pinned_ip:port)!
    bindings_set = set(captured_bindings)
    assert ("host-a.com", "93.184.216.34", 443) in bindings_set
    assert ("host-b.com", "1.1.1.1", 443) in bindings_set

    # Assert that swapped mappings DO NOT exist!
    assert ("host-a.com", "1.1.1.1", 443) not in bindings_set
    assert ("host-b.com", "93.184.216.34", 443) not in bindings_set
