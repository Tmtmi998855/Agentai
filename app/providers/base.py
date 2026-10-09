from typing import Protocol, runtime_checkable, Any
from app.domain.models import ProviderResult


@runtime_checkable
class ReasoningProvider(Protocol):
    """Abstraction protocol for LLM Reasoning Providers."""

    async def generate_structured(
        self,
        *,
        task: str,
        messages: list[dict[str, Any]],
        response_schema: dict[str, Any],
        model: str,
        timeout_s: int = 30,
    ) -> ProviderResult:
        """Generates structured output conforming to response_schema."""
        ...
