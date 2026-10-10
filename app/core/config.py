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

    # 파이프라인 모드: mock(오프라인 가상 데이터) | live(실제 검색·원문 확인·LLM)
    PIPELINE_MODE: Literal["mock", "live"] = Field(default="mock", description="브리핑 파이프라인 실행 모드")

    # Reasoning Provider Choice: mock | openai_compatible | codex_cli
    REASONING_PROVIDER: str = Field(default="mock", description="Selected reasoning provider")

    # 원문 페이지 수집 시 추가로 신뢰할 CA 파일 (TLS 중계 프록시 환경 전용, 보통 비워 둠)
    RAW_FETCH_CA_BUNDLE: str = Field(default="", description="원문 수집용 추가 CA 번들 경로")

    # Codex CLI (로컬 PC에 로그인된 Codex로 GPT-6 Luna 호출)
    CODEX_COMMAND: str = Field(default="codex", description="Codex CLI 실행 명령")
    CODEX_MODEL: str = Field(default="gpt-6-luna", description="Codex에 넘길 모델 ID (비우면 Codex 기본 모델)")
    CODEX_TIMEOUT_SECONDS: int = Field(default=180, ge=10, le=900, description="Codex 1회 호출 제한 시간")

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
            "pipeline_mode": self.PIPELINE_MODE,
            "report_store": self.REPORT_STORE,
        }


settings = Settings()
