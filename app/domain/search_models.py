from datetime import datetime, timezone
from typing import Any
import uuid
from pydantic import Field
from app.domain.models import EvidenceExclusion, StrictBaseModel, current_iso_time


class SearchQuery(StrictBaseModel):
    """Specific query specification for searching."""
    query: str = Field(..., description="검색 쿼리 문자열")
    time_range: str | None = Field(default=None, description="검색 대상 기간 (예: 1m, 1y)")
    domain_filter: list[str] = Field(default_factory=list, description="우선 검색 대상 도메인")
    max_results: int = Field(default=5, ge=1, le=20, description="최대 수집 건수")


class SearchRequest(StrictBaseModel):
    """Search request bundle for a company."""
    company_name: str = Field(..., description="대상 고객사명")
    queries: list[SearchQuery] = Field(default_factory=list, description="실행할 검색 쿼리 목록")
    max_results_per_query: int = Field(default=5, ge=1, le=10)


class RawSearchItem(StrictBaseModel):
    """Single raw search result item directly captured from search provider."""
    item_id: str = Field(default_factory=lambda: f"raw_{uuid.uuid4().hex[:8]}")
    query: str = Field(..., description="사용한 검색 쿼리")
    title: str = Field(..., description="검색 결과 제목")
    snippet: str = Field(..., description="검색 본문 발췌(스니펫)")
    url: str | None = Field(default=None, description="원본 문서 URL")
    publisher: str | None = Field(default=None, description="언론사/출처명")
    published_at: str | None = Field(default=None, description="발행일자 (YYYY-MM-DD)")
    retrieved_at: str = Field(default_factory=current_iso_time)
    raw_payload: dict[str, Any] = Field(default_factory=dict, description="제공자 원본 응답 메타데이터")


class SearchResult(StrictBaseModel):
    """Result bundle from SearchProvider."""
    provider: str = Field(..., description="검색 공급자명 (perplexity, mock 등)")
    query: str = Field(..., description="실행된 대표 쿼리 또는 요약")
    items: list[RawSearchItem] = Field(default_factory=list, description="수집된 RawSearchItem 목록")
    excluded_items: list[EvidenceExclusion] = Field(default_factory=list, description="URL 누락/무효로 제외된 검색결과")
    total_count: int = 0
    retrieved_at: str = Field(default_factory=current_iso_time)
    success: bool = True
    error: str | None = None


class SearchRun(StrictBaseModel):
    """Observability and audit log for search operations."""
    run_id: str = Field(default_factory=lambda: f"srun_{uuid.uuid4().hex[:8]}")
    provider: str
    query: str
    requested_at: str = Field(default_factory=current_iso_time)
    completed_at: str = Field(default_factory=current_iso_time)
    latency_ms: float = 0.0
    success: bool = True
    status_code: int | None = None
    result_count: int = 0
    retry_count: int = 0
    error_code: str | None = None
