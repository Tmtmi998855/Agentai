from typing import Protocol, runtime_checkable
from app.domain.search_models import SearchRequest, SearchResult


@runtime_checkable
class SearchProvider(Protocol):
    """Protocol abstraction for Web Search Providers (Perplexity, Mock, etc.)."""

    async def search(self, request: SearchRequest) -> SearchResult:
        """Executes search for given company and queries, returning SearchResult."""
        ...
