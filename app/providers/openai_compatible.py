import json
import time
from typing import Any
import httpx
from pydantic import SecretStr
from app.domain.models import ProviderResult
from app.providers.base import ReasoningProvider


class OpenAICompatibleReasoningProvider(ReasoningProvider):
    """ReasoningProvider implementation for OpenAI-compatible endpoints (OmniRoute, Groq, Cerebras, OpenRouter, etc.)."""

    def __init__(
        self,
        base_url: str = "http://localhost:20128/v1",
        api_key: SecretStr | str = "mock-key",
        default_model: str = "auto/best-coding",
        default_timeout_s: int = 30,
        max_retries: int = 1,
        http_client: httpx.AsyncClient | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key if isinstance(api_key, SecretStr) else SecretStr(api_key)
        self.default_model = default_model
        self.default_timeout_s = default_timeout_s
        self.max_retries = max(0, min(max_retries, 5))
        self._http_client = http_client

    async def generate_structured(
        self,
        *,
        task: str,
        messages: list[dict[str, Any]],
        response_schema: dict[str, Any],
        model: str | None = None,
        timeout_s: int | None = None,
    ) -> ProviderResult:
        target_model = model or self.default_model
        timeout = timeout_s or self.default_timeout_s
        endpoint = f"{self.base_url}/chat/completions"

        system_instruction = (
            f"You must output valid JSON conforming to the following JSON schema:\n"
            f"{json.dumps(response_schema, ensure_ascii=False)}"
        )
        formatted_messages = [{"role": "system", "content": system_instruction}] + messages

        payload = {
            "model": target_model,
            "messages": formatted_messages,
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
        }

        headers = {
            "Authorization": f"Bearer {self.api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }

        start_time = time.perf_counter()
        last_error = None
        last_error_code = None

        for attempt in range(self.max_retries + 1):
            try:
                client = self._http_client or httpx.AsyncClient(timeout=float(timeout))
                try:
                    response = await client.post(endpoint, json=payload, headers=headers)
                finally:
                    if self._http_client is None:
                        await client.aclose()

                elapsed_ms = (time.perf_counter() - start_time) * 1000

                # 4xx errors are client/auth errors — do not retry!
                if 400 <= response.status_code < 500:
                    if response.status_code in (401, 403):
                        err_code = "PROVIDER_AUTH_ERROR"
                        err_msg = f"HTTP {response.status_code}: Provider Authentication Error"
                    elif response.status_code in (400, 422):
                        err_code = "PROVIDER_BAD_REQUEST"
                        err_msg = f"HTTP {response.status_code}: Client Error"
                    else:
                        err_code = "PROVIDER_CLIENT_ERROR"
                        err_msg = f"HTTP {response.status_code}: Client Error"

                    return ProviderResult(
                        provider="openai_compatible",
                        requested_model=target_model,
                        actual_model=target_model,
                        success=False,
                        error=err_msg,
                        error_code=err_code,
                        latency_ms=elapsed_ms,
                    )

                if response.status_code != 200:
                    last_error_code = "PROVIDER_SERVER_ERROR"
                    last_error = f"HTTP {response.status_code}: Server Error"
                    continue

                try:
                    res_json = response.json()
                    content = res_json["choices"][0]["message"]["content"]
                except (ValueError, TypeError, KeyError, IndexError):
                    last_error_code = "PROVIDER_INVALID_JSON"
                    last_error = "Provider response is missing structured content"
                    continue

                try:
                    structured_data = json.loads(content)
                except (json.JSONDecodeError, TypeError) as jde:
                    last_error_code = "PROVIDER_INVALID_JSON"
                    last_error = f"Invalid JSON in model output: {jde}"
                    continue
                if not isinstance(structured_data, dict):
                    last_error_code = "PROVIDER_INVALID_JSON"
                    last_error = "Model output must be a JSON object"
                    continue

                usage = res_json.get("usage", {})
                input_tokens = usage.get("prompt_tokens", 0)
                output_tokens = usage.get("completion_tokens", 0)
                # actual_model extracted directly from API response
                actual_model = res_json.get("model") or target_model

                return ProviderResult(
                    provider="openai_compatible",
                    requested_model=target_model,
                    actual_model=actual_model,
                    content=content,
                    structured_data=structured_data,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=elapsed_ms,
                    cost_usd=0.0,
                    raw_response=res_json,
                    success=True,
                    error=None,
                    error_code=None,
                )

            except (httpx.TimeoutException, TimeoutError) as te:
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                return ProviderResult(
                    provider="openai_compatible",
                    requested_model=target_model,
                    actual_model=target_model,
                    success=False,
                    error=f"Provider call timed out after {timeout} seconds",
                    error_code="PROVIDER_TIMEOUT",
                    latency_ms=elapsed_ms,
                )
            except httpx.RequestError as re:
                last_error_code = "PROVIDER_NETWORK_ERROR"
                last_error = f"Network request error: {str(re)}"
                continue
            except Exception as e:
                last_error_code = "PROVIDER_ERROR"
                last_error = f"Unexpected error during provider execution: {str(e)}"
                break

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        return ProviderResult(
            provider="openai_compatible",
            requested_model=target_model,
            actual_model=target_model,
            success=False,
            error=last_error or "Unknown provider failure",
            error_code=last_error_code or "PROVIDER_ERROR",
            latency_ms=elapsed_ms,
        )
