import os
from typing import Literal
from pydantic import SecretStr, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "Ah! There Backend V0"
    APP_ENV: Literal["development", "testing", "production"] = "development"
    DEBUG: bool = False

    # Reasoning Provider Choice: mock | openai_compatible
    REASONING_PROVIDER: str = Field(default="mock", description="Selected reasoning provider")

    # OpenAI Compatible LLM Gateway Settings
    OPENAI_BASE_URL: str = Field(default="http://localhost:20128/v1", description="Base URL for OpenAI compatible API")
    OPENAI_API_KEY: SecretStr = Field(default=SecretStr("mock-api-key"), description="API key for LLM provider")
    REASONING_MODEL: str = Field(default="auto/best-coding", description="Model identifier")
    TIMEOUT_SECONDS: int = Field(default=30, ge=1, le=300, description="Timeout in seconds for provider calls")
    MAX_RETRIES: int = Field(default=1, ge=0, le=5, description="Maximum retry count for transient provider errors")

    # Search Provider Choice: mock | perplexity
    SEARCH_PROVIDER: str = Field(default="mock", description="Selected search provider")

    # Perplexity Search Provider Settings
    PERPLEXITY_BASE_URL: str = Field(default="https://api.perplexity.ai", description="Perplexity API base URL")
    PERPLEXITY_API_KEY: SecretStr = Field(default=SecretStr(""), description="API key for Perplexity")
    PERPLEXITY_SEARCH_MODEL: str = Field(default="sonar", description="Perplexity search model (e.g. sonar)")
    PERPLEXITY_TIMEOUT_SECONDS: int = Field(default=15, ge=1, le=120, description="Timeout in seconds for search calls")
    PERPLEXITY_MAX_RETRIES: int = Field(default=1, ge=0, le=5, description="Maximum retry count for search calls")

    # Report Store (Supabase) & 웹 리포트 링크
    REPORT_STORE: Literal["memory", "supabase"] = Field(default="memory", description="리포트 저장소 선택")
    SUPABASE_URL: str = Field(default="", description="Supabase 프로젝트 URL (https://<ref>.supabase.co)")
    SUPABASE_SERVICE_ROLE_KEY: SecretStr = Field(default=SecretStr(""), description="서버 전용 service_role 키")
    # 도메인 미보유: 로컬 Next.js 기본값. 배포 후 https://<project>.vercel.app/report 로 교체
    REPORT_BASE_URL: str = Field(default="http://localhost:3000/report", description="웹 리포트 뷰어 기본 URL")

    # MCP 서버 사용자 고정 (LLM이 사용자 ID를 넘기지 못하게 서버 설정으로만 지정)
    AH_THERE_MESSENGER_TYPE: Literal["telegram", "web"] = Field(default="telegram", description="MCP 서버 소유자 메신저")
    AH_THERE_OWNER_USER_ID: str = Field(default="", description="MCP 서버 소유자의 메신저 숫자 ID (예: 텔레그램 user id)")

    def get_public_provider_config(self) -> dict:
        """Returns safe provider config WITHOUT API keys or sensitive secrets."""
        return {
            "active_provider": self.REASONING_PROVIDER,
            "active_reasoning_provider": self.REASONING_PROVIDER,
            "active_search_provider": self.SEARCH_PROVIDER,
            "model": self.REASONING_MODEL,
            "base_url": self.OPENAI_BASE_URL,
            "perplexity_model": self.PERPLEXITY_SEARCH_MODEL,
            "perplexity_base_url": self.PERPLEXITY_BASE_URL,
            "timeout_seconds": self.TIMEOUT_SECONDS,
            "max_retries": self.MAX_RETRIES,
            "app_env": self.APP_ENV,
            "report_store": self.REPORT_STORE,
        }


settings = Settings()
