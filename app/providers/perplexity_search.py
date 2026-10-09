import asyncio
import json
import time
from typing import Any
from urllib.parse import urlparse
import httpx
from pydantic import SecretStr
from app.domain.models import EvidenceExclusion
from app.domain.search_models import SearchRequest, SearchResult, RawSearchItem
from app.providers.search_base import SearchProvider


class PerplexitySearchProvider(SearchProvider):
    """
    SearchProvider implementation calling official Perplexity Search API.
    Perplexity Search API Endpoint: POST /search
    Request Schema: {"query": str, "max_results": int}
    Response Schema: {"results": [{"title": str, "url": str, "snippet": str, "date": str}]}
    """

    def __init__(
        self,
        base_url: str = "https://api.perplexity.ai",
        api_key: SecretStr | str = "",
        timeout_s: int = 15,
        max_retries: int = 1,
        http_client: httpx.AsyncClient | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key if isinstance(api_key, SecretStr) else SecretStr(api_key)
        self.timeout_s = timeout_s
        self.max_retries = max(0, min(max_retries, 5))
        self._http_client = http_client

    async def search(self, request: SearchRequest) -> SearchResult:
        if not self.api_key.get_secret_value():
            return SearchResult(
                provider="perplexity",
                query=request.company_name,
                items=[],
                total_count=0,
                success=False,
                error="Perplexity API Key is not configured",
            )

        queries = request.queries or [
            {"query": f"{request.company_name} 최신 대표이사 사업장 시설 투자 채용 공시", "max_results": 5}
        ]

        all_items: list[RawSearchItem] = []
        excluded_items: list[EvidenceExclusion] = []
        endpoint = f"{self.base_url}/search"
        headers = {
            "Authorization": f"Bearer {self.api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }

        primary_query = queries[0].query if hasattr(queries[0], "query") else str(queries[0])
        last_error = None

        for q in queries:
            query_str = q.query if hasattr(q, "query") else str(q)
            max_results = getattr(q, "max_results", 5)

            # Official Perplexity Search API payload
            payload = {
                "query": query_str,
                "max_results": max_results
            }

            for attempt in range(self.max_retries + 1):
                try:
                    client = self._http_client or httpx.AsyncClient(timeout=float(self.timeout_s))
                    try:
                        response = await client.post(endpoint, json=payload, headers=headers)
                    finally:
                        if self._http_client is None:
                            await client.aclose()

                    # 4xx client errors (400, 401, 403, 422) - NO retry!
                    if 400 <= response.status_code < 500 and response.status_code != 429:
                        last_error = f"HTTP {response.status_code}: Client Error"
                        return SearchResult(
                            provider="perplexity",
                            query=primary_query,
                            items=[],
                            total_count=0,
                            success=False,
                            error=last_error,
                        )

                    # 429 Rate limit handling with Retry-After header
                    if response.status_code == 429:
                        last_error = "HTTP 429: Rate Limit Exceeded"
                        retry_after = response.headers.get("Retry-After")
                        if retry_after and attempt < self.max_retries:
                            try:
                                wait_seconds = min(float(retry_after), 10.0)
                                await asyncio.sleep(wait_seconds)
                            except ValueError:
                                await asyncio.sleep(0.1)
                        continue

                    # 5xx Transient server error - retry bounded
                    if 500 <= response.status_code < 600:
                        last_error = f"HTTP {response.status_code}: Server Error"
                        if attempt < self.max_retries:
                            await asyncio.sleep(0.1)
                            continue
                        else:
                            return SearchResult(
                                provider="perplexity",
                                query=primary_query,
                                items=[],
                                total_count=0,
                                success=False,
                                error=last_error,
                            )

                    if response.status_code != 200:
                        last_error = f"HTTP {response.status_code}: Unexpected Status"
                        continue

                    res_json = response.json()
                    results = res_json.get("results", [])

                    # Parse official Search API results[]
                    if isinstance(results, list):
                        for idx, r in enumerate(results):
                            item_id = f"pplx_srch_{idx}_{uuid_short()}"
                            r_url = r.get("url")
                            exclusion_reason = url_exclusion_reason(r_url)
                            if exclusion_reason is not None:
                                excluded_items.append(EvidenceExclusion(item_id=item_id, reason=exclusion_reason))
                                continue
                            r_url = r_url.strip()

                            item = RawSearchItem(
                                item_id=item_id,
                                query=query_str,
                                title=r.get("title") or f"{request.company_name} 검색결과 {idx+1}",
                                snippet=r.get("snippet") or "",
                                url=r_url,
                                publisher=r.get("publisher") or extract_domain(r_url),
                                published_at=r.get("date") or r.get("published_date"),
                                raw_payload={"search_index": idx, "endpoint": "/search", "url_valid": bool(r_url)}
                            )
                            all_items.append(item)

                    break

                except (httpx.TimeoutException, TimeoutError):
                    last_error = f"Search provider call timed out after {self.timeout_s} seconds"
                    break
                except httpx.RequestError as re:
                    last_error = f"Network request error: {str(re)}"
                    continue
                except Exception as e:
                    last_error = f"Unexpected error during search execution: {str(e)}"
                    break

        if all_items:
            return SearchResult(
                provider="perplexity",
                query=primary_query,
                items=all_items,
                excluded_items=excluded_items,
                total_count=len(all_items),
                success=True,
                error=None,
            )

        return SearchResult(
            provider="perplexity",
            query=primary_query,
            items=[],
            excluded_items=excluded_items,
            total_count=0,
            success=last_error is None,
            error=last_error,
        )


class PerplexitySonarAdapter:
    """
    Isolated Legacy/Experimental Adapter for Perplexity Sonar Chat Completions API.
    NOT used in standard SearchProvider pipeline.
    """
    def __init__(
        self,
        base_url: str = "https://api.perplexity.ai",
        api_key: SecretStr | str = "",
        model: str = "sonar",
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key if isinstance(api_key, SecretStr) else SecretStr(api_key)
        self.model = model


def uuid_short() -> str:
    import uuid
    return uuid.uuid4().hex[:6]


def extract_domain(url: str) -> str:
    from urllib.parse import urlparse
    try:
        parsed = urlparse(url)
        return parsed.hostname or url
    except Exception:
        return url


def url_exclusion_reason(url: str | None) -> str | None:
    """Returns the audit reason for a missing or invalid HTTP(S) URL."""
    if not isinstance(url, str) or not url.strip():
        return "URL_MISSING"
    parsed = urlparse(url.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return "URL_INVALID"
    return None
