import asyncio
import time
from typing import Any
from app.domain.search_models import SearchRequest, SearchResult, RawSearchItem
from app.providers.search_base import SearchProvider


class MockSearchProvider(SearchProvider):
    """Mock implementation of SearchProvider for offline testing without API keys."""

    def __init__(
        self,
        default_items: list[RawSearchItem] | None = None,
        simulate_empty: bool = False,
        simulate_timeout: bool = False,
        simulate_error: bool = False,
        error_message: str = "Mock search provider error",
    ):
        self.simulate_empty = simulate_empty
        self.simulate_timeout = simulate_timeout
        self.simulate_error = simulate_error
        self.error_message = error_message
        self.default_items = default_items

    async def search(self, request: SearchRequest) -> SearchResult:
        start_time = time.perf_counter()
        primary_query = request.queries[0].query if request.queries else f"{request.company_name} 뉴스"

        if self.simulate_timeout:
            await asyncio.sleep(0.5)
            return SearchResult(
                provider="mock",
                query=primary_query,
                items=[],
                total_count=0,
                success=False,
                error="Search call timed out after timeout period",
            )

        if self.simulate_error:
            return SearchResult(
                provider="mock",
                query=primary_query,
                items=[],
                total_count=0,
                success=False,
                error=self.error_message,
            )

        if self.simulate_empty:
            return SearchResult(
                provider="mock",
                query=primary_query,
                items=[],
                total_count=0,
                success=True,
                error=None,
            )

        if self.default_items is not None:
            items = self.default_items
        else:
            items = [
                RawSearchItem(
                    item_id="raw_mock_01",
                    query=primary_query,
                    title=f"{request.company_name}, 서울 신사옥 이전 및 공장 확장 공시",
                    snippet=f"{request.company_name}는 2026년 하반기 사업 확장을 위해 신사옥 이전 및 생산 시설 증설을 완료했다고 공시했습니다.",
                    url="https://dart.fss.or.kr/example/001",
                    publisher="금융감독원 전자공시",
                    published_at="2026-09-01",
                    raw_payload={"source": "dart_mock"}
                ),
                RawSearchItem(
                    item_id="raw_mock_02",
                    query=primary_query,
                    title=f"{request.company_name}, 하반기 물류 및 영업 인력 대규모 채용",
                    snippet=f"{request.company_name}가 신규 사업 확장에 발맞추어 영업, 기획, 물류 부문 채용을 진행 중입니다.",
                    url="https://www.mk.co.kr/news/example/002",
                    publisher="매일경제",
                    published_at="2026-09-10",
                    raw_payload={"source": "news_mock"}
                ),
                RawSearchItem(
                    item_id="raw_mock_03",
                    query=primary_query,
                    title=f"[블로그] {request.company_name} 신사옥 방문 후기 및 사업 현황",
                    snippet=f"최근 {request.company_name} 강남 사옥을 방문해 관계자를 만났습니다.",
                    url="https://blog.naver.com/example/003",
                    publisher="네이버 블로그",
                    published_at="2026-09-15",
                    raw_payload={"source": "blog_mock"}
                ),
            ]

        return SearchResult(
            provider="mock",
            query=primary_query,
            items=items,
            total_count=len(items),
            success=True,
            error=None,
        )
