from app.core.config import settings
from app.providers.base import ReasoningProvider
from app.providers.mock import MockReasoningProvider
from app.providers.openai_compatible import OpenAICompatibleReasoningProvider

from app.providers.search_base import SearchProvider
from app.providers.mock_search import MockSearchProvider
from app.providers.perplexity_search import PerplexitySearchProvider


def get_reasoning_provider(provider_type: str | None = None) -> ReasoningProvider:
    """Factory function to instantiate the configured ReasoningProvider."""
    target_provider = provider_type or settings.REASONING_PROVIDER

    if target_provider == "mock":
        return MockReasoningProvider()
    elif target_provider == "openai_compatible":
        return OpenAICompatibleReasoningProvider(
            base_url=settings.OPENAI_BASE_URL,
            api_key=settings.OPENAI_API_KEY,
            default_model=settings.REASONING_MODEL,
            default_timeout_s=settings.TIMEOUT_SECONDS,
            max_retries=settings.MAX_RETRIES,
        )
    else:
        raise ValueError(f"Unsupported REASONING_PROVIDER: {target_provider}")


def get_search_provider(provider_type: str | None = None) -> SearchProvider:
    """Factory function to instantiate the configured SearchProvider."""
    target_provider = provider_type or settings.SEARCH_PROVIDER

    if target_provider == "mock":
        return MockSearchProvider()
    elif target_provider == "perplexity":
        return PerplexitySearchProvider(
            base_url=settings.PERPLEXITY_BASE_URL,
            api_key=settings.PERPLEXITY_API_KEY,
            timeout_s=settings.PERPLEXITY_TIMEOUT_SECONDS,
            max_retries=settings.PERPLEXITY_MAX_RETRIES,
        )
    else:
        raise ValueError(f"Unsupported SEARCH_PROVIDER: {target_provider}")
