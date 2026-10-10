import ssl
import asyncio
import hashlib
import html
import ipaddress
import re
import socket
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import urlparse, urljoin
import httpx
import httpcore
from pydantic import Field

from app.domain.models import Evidence, StrictBaseModel, current_iso_time
from app.core.exceptions import AhThereException


class SSRFViolationException(AhThereException):
    """Raised when a URL attempts to target local, private, or restricted IP addresses."""
    def __init__(self, message: str = "URL targets forbidden private or internal IP address", detail: dict | None = None):
        super().__init__(message, error_code="SSRF_VIOLATION", detail=detail)


class RawFetchResult(StrictBaseModel):
    """Result payload of WebRawFetcher operations."""
    url: str = Field(..., description="수집 대상 원본 URL")
    resolved_ip: str | None = Field(default=None, description="접속한 검증된 IP 주소")
    status_code: int = Field(..., description="HTTP 응답 코드 (200, 404, 415 등)")
    content_type: str | None = Field(default=None, description="수집된 Content-Type")
    raw_content_hash: str | None = Field(default=None, description="원문 HTML 텍스트 SHA256 해시")
    extracted_text: str | None = Field(default=None, description="추출된 본문 텍스트 (성공 시)")
    fetched_at: str = Field(default_factory=current_iso_time)
    success: bool = Field(default=True)
    error_message: str | None = Field(default=None)


class SSRFFilter:
    """Security validator preventing SSRF, DNS Rebinding, and Proxy Bypass."""

    ALLOWED_PUBLIC_HEADERS = {
        "user-agent",
        "accept",
        "accept-language",
        "accept-encoding",
    }

    # Forbidden IPv4 networks: Private, Loopback, Link-Local, CGNAT, Multicast, Reserved
    FORBIDDEN_IPV4_NETWORKS = [
        ipaddress.ip_network("0.0.0.0/8"),
        ipaddress.ip_network("127.0.0.0/8"),      # Loopback
        ipaddress.ip_network("10.0.0.0/8"),       # Private Class A
        ipaddress.ip_network("172.16.0.0/12"),    # Private Class B
        ipaddress.ip_network("192.168.0.0/16"),   # Private Class C
        ipaddress.ip_network("169.254.0.0/16"),   # Link-Local / AWS IMDS
        ipaddress.ip_network("100.64.0.0/10"),    # CGNAT
        ipaddress.ip_network("224.0.0.0/4"),      # Multicast
        ipaddress.ip_network("240.0.0.0/4"),      # Reserved
    ]

    # Forbidden IPv6 networks: Discard-only, Documentation, ULA, Link-Local, Multicast
    FORBIDDEN_IPV6_NETWORKS = [
        ipaddress.ip_network("100::/64"),         # Discard-only
        ipaddress.ip_network("2001:db8::/32"),     # Documentation
        ipaddress.ip_network("fc00::/7"),         # Unique Local (ULA)
        ipaddress.ip_network("fe80::/10"),        # Link-Local
        ipaddress.ip_network("ff00::/8"),         # Multicast
    ]

    @staticmethod
    def validate_url_scheme(url: str) -> str:
        """Enforces protocol restriction: ONLY http:// and https:// allowed."""
        if not url or not isinstance(url, str):
            raise SSRFViolationException("URL must be a non-empty string")

        parsed = urlparse(url.strip())
        if parsed.scheme.lower() not in ("http", "https"):
            raise SSRFViolationException(f"Unsupported scheme '{parsed.scheme}'. Only http and https allowed.")

        if not parsed.hostname:
            raise SSRFViolationException("Missing hostname in URL")

        return url.strip()

    @staticmethod
    def resolve_and_validate_ip(hostname: str) -> str:
        """
        Resolves hostname to IP and validates against private/local networks.
        Returns validated IP address string.
        """
        clean_host = hostname.strip().lower()

        if clean_host in ("localhost", "localhost.localdomain", "broadcasthost"):
            raise SSRFViolationException(f"Forbidden hostname: {clean_host}")

        # Check if already IP address literal
        try:
            ip_obj = ipaddress.ip_address(clean_host)
            SSRFFilter.validate_ip_object(ip_obj)
            return str(ip_obj)
        except ValueError:
            pass

        # Perform DNS resolution
        try:
            addr_info = socket.getaddrinfo(clean_host, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        except socket.gaierror as e:
            raise SSRFViolationException(f"DNS resolution failed for hostname '{clean_host}': {str(e)}")

        resolved_ips = []
        for family, _, _, _, sockaddr in addr_info:
            ip_str = sockaddr[0]
            try:
                ip_obj = ipaddress.ip_address(ip_str)
                SSRFFilter.validate_ip_object(ip_obj)
                resolved_ips.append(str(ip_obj))
            except SSRFViolationException:
                raise

        if not resolved_ips:
            raise SSRFViolationException(f"No valid public IP resolved for '{clean_host}'")

        return resolved_ips[0]

    @staticmethod
    def validate_ip_object(ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
        # Unwrap IPv4-mapped IPv6 addresses (e.g. ::ffff:127.0.0.1, ::ffff:100.64.0.1)
        if isinstance(ip_obj, ipaddress.IPv6Address) and ip_obj.ipv4_mapped:
            ip_obj = ip_obj.ipv4_mapped

        if ip_obj.is_loopback or ip_obj.is_private or ip_obj.is_link_local or ip_obj.is_multicast or ip_obj.is_reserved:
            raise SSRFViolationException(f"Forbidden IP address: {ip_obj}")

        if isinstance(ip_obj, ipaddress.IPv4Address):
            for net in SSRFFilter.FORBIDDEN_IPV4_NETWORKS:
                if ip_obj in net:
                    raise SSRFViolationException(f"IP address {ip_obj} falls into restricted network {net}")
        elif isinstance(ip_obj, ipaddress.IPv6Address):
            for net in SSRFFilter.FORBIDDEN_IPV6_NETWORKS:
                if ip_obj in net:
                    raise SSRFViolationException(f"IP address {ip_obj} falls into restricted network {net}")

    @staticmethod
    def is_public_ip_str(ip_str: str | None) -> bool:
        if not ip_str:
            return False
        try:
            raw_ip = ip_str.split(" ")[0].strip()
            ip_obj = ipaddress.ip_address(raw_ip)
            SSRFFilter.validate_ip_object(ip_obj)
            return True
        except Exception:
            return False


class PinnedNetworkBackend(httpcore.AsyncNetworkBackend):
    """
    Custom httpcore network backend enforcing IP Pinning.
    Intercepts TCP connect requests and forces socket connection ONLY to pre-validated IP address,
    preventing DNS Rebinding (TOCTOU) attacks while preserving domain TLS SNI.
    """
    def __init__(self, pinned_ip: str, base_backend: httpcore.AsyncNetworkBackend):
        self.pinned_ip = pinned_ip
        self.base_backend = base_backend

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None
    ) -> httpcore.AsyncNetworkStream:
        # Override connection host to connect ONLY to pinned_ip, ignoring any secondary DNS lookup!
        return await self.base_backend.connect_tcp(
            host=self.pinned_ip,
            port=port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options
        )

    async def connect_unix_socket(self, *args, **kwargs):
        return await self.base_backend.connect_unix_socket(*args, **kwargs)

    async def sleep(self, seconds: float):
        return await self.base_backend.sleep(seconds)


class WebRawFetcher:
    """
    Service for fetching HTML raw content over HTTP with SSRF defense,
    IP Pinning (Anti-DNS-Rebinding), and strict RAW_VERIFIED status transitions.
    """

    def __init__(
        self,
        max_bytes: int = 5 * 1024 * 1024,  # 5MB upper limit
        timeout_s: float = 10.0,
        max_redirects: int = 3,
        http_client: httpx.AsyncClient | None = None,
        allow_live_fetch: bool = False,  # Safety flag: Keep False for offline mock verification
        ca_bundle: str | None = None,  # 사내/클라우드 프록시처럼 TLS를 중계하는 환경의 추가 CA (검증은 항상 유지)
    ):
        self.max_bytes = max_bytes
        self.timeout_s = timeout_s
        self.max_redirects = max_redirects
        self._http_client = http_client
        self.allow_live_fetch = allow_live_fetch
        self._verify: ssl.SSLContext | bool = ssl.create_default_context(cafile=ca_bundle) if ca_bundle else True
        if self._http_client is not None:
            self._validate_injected_client(self._http_client)

    @staticmethod
    def _validate_injected_client(client: httpx.AsyncClient) -> None:
        """Enforces security invariants on injected httpx.AsyncClient."""
        if getattr(client, "follow_redirects", False) is True:
            raise SSRFViolationException(
                "Injected http_client must have follow_redirects=False to enforce per-hop SSRF validation"
            )

        mounts = getattr(client, "_mounts", {})
        if mounts:
            raise SSRFViolationException(
                "Injected http_client with custom mounts or proxies is unsupported as it bypasses per-hop IP pinning"
            )

        raw_transport = getattr(client, "_transport", None)
        if not isinstance(raw_transport, (httpx.AsyncHTTPTransport, httpx.MockTransport)):
            raise SSRFViolationException(
                f"Unsupported transport type '{type(raw_transport).__name__}'. "
                "Only AsyncHTTPTransport and MockTransport are permitted for security."
            )

    ALLOWED_PUBLIC_HEADERS = {
        "user-agent",
        "accept",
        "accept-language",
        "accept-encoding",
    }

    @staticmethod
    def _sanitize_headers(headers: httpx.Headers | dict[str, str] | None) -> dict[str, str]:
        """
        Strips custom/sensitive headers and user-specified Host headers before fetching public web content.
        ONLY copies safe, standard public request headers from the whitelisted set.
        """
        clean_headers = {}
        if headers:
            for key, value in headers.items():
                if key.lower() in SSRFFilter.ALLOWED_PUBLIC_HEADERS:
                    clean_headers[key] = value

        if "user-agent" not in {k.lower() for k in clean_headers}:
            clean_headers["User-Agent"] = "AhThere-RawFetcher/0.1"

        return clean_headers

    async def fetch_and_verify_evidence(
        self,
        evidence: Evidence,
        custom_raw_html: str | None = None
    ) -> RawFetchResult:
        """
        Fetches raw content and updates Evidence status to RAW_VERIFIED.
        CRITICAL: Raw fetch success ONLY sets status='RAW_VERIFIED'.
        It NEVER grants status='FACT_CONFIRMED'!
        """
        # If offline fixture raw HTML is provided directly
        if custom_raw_html is not None:
            clean_text = self._extract_clean_text(custom_raw_html)
            evidence.verify_raw(clean_text)
            content_hash = hashlib.sha256(clean_text.encode()).hexdigest()
            return RawFetchResult(
                url=evidence.url,
                resolved_ip="127.0.0.1 (offline-fixture)",
                status_code=200,
                content_type="text/html",
                raw_content_hash=content_hash,
                extracted_text=clean_text,
                success=True,
            )

        if not self.allow_live_fetch:
            # Live site fetching disabled for safety
            return RawFetchResult(
                url=evidence.url,
                status_code=403,
                success=False,
                error_message="Live site fetching is disabled in offline V0 stage.",
            )

        # Validate URL and SSRF bounds
        try:
            url = SSRFFilter.validate_url_scheme(evidence.url)
            result = await self._safe_http_fetch(url)

            if result.success and result.extracted_text:
                # Transition status to RAW_VERIFIED (NOT FACT_CONFIRMED!)
                evidence.verify_raw(result.extracted_text)

            return result
        except SSRFViolationException as se:
            return RawFetchResult(
                url=evidence.url,
                status_code=400,
                success=False,
                error_message=f"SSRF Violation: {str(se)}"
            )
        except Exception as e:
            return RawFetchResult(
                url=evidence.url,
                status_code=500,
                success=False,
                error_message=f"Fetch failed: {str(e)}"
            )

    async def _safe_http_fetch(self, initial_url: str) -> RawFetchResult:
        if self._http_client is not None:
            self._validate_injected_client(self._http_client)

        current_url = initial_url
        redirect_count = 0
        last_ip = None

        while redirect_count <= self.max_redirects:
            try:
                parsed = urlparse(current_url)
                # Step 1: Validate SSRF for current hop
                last_ip = SSRFFilter.resolve_and_validate_ip(parsed.hostname)

                # Step 2: Configure Client per-hop with PinnedNetworkBackend to guarantee IP Pinning (Anti-DNS-Rebinding)
                # without mutating any shared transport or connection pool
                should_close_client = False

                if self._http_client is None:
                    base_backend = httpcore.AnyIOBackend()
                    pinned_backend = PinnedNetworkBackend(pinned_ip=last_ip, base_backend=base_backend)
                    transport = httpx.AsyncHTTPTransport(trust_env=False, verify=self._verify)
                    transport._pool._network_backend = pinned_backend
                    client = httpx.AsyncClient(
                        timeout=httpx.Timeout(self.timeout_s),
                        headers={"User-Agent": "AhThere-RawFetcher/0.1"},
                        transport=transport,
                        trust_env=False,
                        follow_redirects=False,
                    )
                    should_close_client = True
                else:
                    raw_transport = getattr(self._http_client, "_transport", None)
                    clean_headers = self._sanitize_headers(self._http_client.headers)

                    if isinstance(raw_transport, httpx.AsyncHTTPTransport):
                        existing_backend = getattr(raw_transport._pool, "_network_backend", None)
                        if isinstance(existing_backend, PinnedNetworkBackend):
                            base_backend = existing_backend.base_backend
                        elif existing_backend is not None:
                            base_backend = existing_backend
                        else:
                            base_backend = httpcore.AnyIOBackend()

                        pinned_backend = PinnedNetworkBackend(pinned_ip=last_ip, base_backend=base_backend)
                        transport = httpx.AsyncHTTPTransport(trust_env=False, verify=self._verify)
                        transport._pool._network_backend = pinned_backend
                        client = httpx.AsyncClient(
                            timeout=self._http_client.timeout,
                            headers=clean_headers,
                            transport=transport,
                            trust_env=False,
                            follow_redirects=False,
                        )
                        should_close_client = True
                    else:
                        # Test MockTransport
                        client = httpx.AsyncClient(
                            timeout=self._http_client.timeout,
                            headers=clean_headers,
                            transport=raw_transport,
                            trust_env=False,
                            follow_redirects=False,
                        )
                        should_close_client = True

                try:
                    # Make request to verified URL (follow_redirects=False) with sanitized headers
                    response = await client.get(current_url)

                    # Step 3: Check PDF / Unsupported Content Type
                    content_type = response.headers.get("Content-Type", "").lower()
                    if "application/pdf" in content_type:
                        return RawFetchResult(
                            url=initial_url,
                            resolved_ip=last_ip,
                            status_code=415,
                            content_type=content_type,
                            success=False,
                            error_message="Unsupported Content Type: PDF requires PyMuPDF converter (V0 unsupported)"
                        )

                    # Handle Redirects manually with SSRF re-validation
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get("Location")
                        if not location:
                            return RawFetchResult(
                                url=initial_url,
                                resolved_ip=last_ip,
                                status_code=response.status_code,
                                success=False,
                                error_message="Redirect missing Location header"
                            )
                        redirect_url = urljoin(current_url, location)
                        current_url = SSRFFilter.validate_url_scheme(redirect_url)
                        redirect_count += 1
                        continue

                    if response.status_code != 200:
                        return RawFetchResult(
                            url=initial_url,
                            resolved_ip=last_ip,
                            status_code=response.status_code,
                            content_type=content_type,
                            success=False,
                            error_message=f"HTTP Error {response.status_code}"
                        )

                    # Step 4: Size bound check
                    body_bytes = response.content
                    if len(body_bytes) > self.max_bytes:
                        return RawFetchResult(
                            url=initial_url,
                            resolved_ip=last_ip,
                            status_code=413,
                            content_type=content_type,
                            success=False,
                            error_message=f"Response body size ({len(body_bytes)} bytes) exceeds limit ({self.max_bytes} bytes)"
                        )

                    html_text = response.text
                    clean_text = self._extract_clean_text(html_text)
                    if not clean_text:
                        return RawFetchResult(
                            url=initial_url,
                            resolved_ip=last_ip,
                            status_code=200,
                            content_type=content_type,
                            raw_content_hash=hashlib.sha256(b"").hexdigest(),
                            extracted_text="",
                            success=True,
                            error_message="Empty HTML body"
                        )

                    content_hash = hashlib.sha256(clean_text.encode()).hexdigest()
                    return RawFetchResult(
                        url=initial_url,
                        resolved_ip=last_ip,
                        status_code=200,
                        content_type=content_type,
                        raw_content_hash=content_hash,
                        extracted_text=clean_text,
                        success=True
                    )

                finally:
                    if should_close_client:
                        await client.aclose()

            except SSRFViolationException as se:
                return RawFetchResult(
                    url=initial_url,
                    resolved_ip=last_ip,
                    status_code=400,
                    success=False,
                    error_message=f"SSRF Violation: {str(se)}"
                )
            except (httpx.TimeoutException, TimeoutError) as te:
                return RawFetchResult(
                    url=initial_url,
                    resolved_ip=last_ip,
                    status_code=504,
                    success=False,
                    error_message=f"Fetch failed: {str(te)}"
                )
            except httpx.RequestError as re:
                return RawFetchResult(
                    url=initial_url,
                    resolved_ip=last_ip,
                    status_code=502,
                    success=False,
                    error_message=f"Fetch failed: {str(re)}"
                )

        return RawFetchResult(
            url=initial_url,
            resolved_ip=last_ip,
            status_code=310,
            success=False,
            error_message=f"Exceeded maximum redirects limit ({self.max_redirects})"
        )

    @staticmethod
    def _extract_clean_text(html_str: str) -> str:
        """HTML 태그와 스크립트를 제거하고 html.unescape를 적용한 뒤 공백을 정규화한다."""
        if not html_str:
            return ""
        # 1. script, style, svg, noscript 태그 제거
        clean = re.sub(r"<(script|style|svg|noscript)[^>]*>.*?</\1>", " ", html_str, flags=re.DOTALL | re.IGNORECASE)
        # 2. HTML 태그 제거
        clean = re.sub(r"<[^>]+>", " ", clean)
        # 3. 태그 제거 후 공백 정규화 전에 html.unescape 적용 (사람이 보는 원문 보존)
        clean = html.unescape(clean)
        # 4. 공백 정규화
        clean = re.sub(r"\s+", " ", clean).strip()
        return clean
