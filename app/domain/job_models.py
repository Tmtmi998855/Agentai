import re
from datetime import datetime, timezone
from typing import Literal, Any
import uuid
from pydantic import Field, field_validator, ConfigDict

from app.domain.models import (
    StrictBaseModel,
    SalesProfile,
    MeetingContext,
    BriefingObject,
    current_iso_time,
)
from app.domain.sales_templates import SalesTemplateSelection

JobStatus = Literal["PENDING", "RUNNING", "COMPLETED", "FAILED"]
JobProvenance = Literal["MOCK_VIRTUAL"]


def _validate_bounded_string(val: str, field_name: str, max_len: int = 200) -> str:
    s = val.strip()
    if not s:
        raise ValueError(f"{field_name} cannot be empty or whitespace only")
    if len(s) > max_len:
        raise ValueError(f"{field_name} length exceeds maximum limit of {max_len} characters")
    return s


class BoundedSalesProfile(SalesProfile):
    """SalesProfile with strict bounded string non-empty validation."""

    @field_validator("company", "industry", "product_service", "target_customer", "sales_goal", mode="after")
    @classmethod
    def validate_profile_fields(cls, v: str, info) -> str:
        return _validate_bounded_string(v, info.field_name, max_len=200)


class BoundedMeetingContext(MeetingContext):
    """MeetingContext with strict bounded string length validation."""

    @field_validator("department", "role", "meeting_purpose", "past_notes", mode="after")
    @classmethod
    def validate_context_fields(cls, v: str | None, info) -> str | None:
        if v is not None:
            s = v.strip()
            if not s:
                raise ValueError(f"{info.field_name} cannot be empty or whitespace only")
            if len(s) > 500:
                raise ValueError(f"{info.field_name} length exceeds maximum limit of 500 characters")
            return s
        return v


class BriefingCreateRequest(StrictBaseModel):
    """Payload to create an asynchronous briefing generation job."""

    company_name: str = Field(..., description="대상 기업명 (공백 불가, 1~100자)")
    sales_profile: BoundedSalesProfile = Field(..., description="영업 담당자 프로필")
    meeting_context: BoundedMeetingContext | None = Field(default=None, description="선택적 미팅 맥락")
    sales_template: SalesTemplateSelection | None = Field(
        default=None, description="3단계 영업 템플릿 선택값. 지정 시 산업 리서치와 질문 3선(P5)을 추가 실행"
    )
    target_industry: str | None = Field(
        default=None, description="고객사 산업군 힌트 (예: 포장재). 미지정 시 기업 식별 결과의 업종 사용"
    )
    company_website: str | None = Field(
        default=None, description="고객사 공식 홈페이지 (live 모드에서 동명 기업 구분 및 공식 출처 등급에 사용)"
    )

    @field_validator("company_name", mode="after")
    @classmethod
    def validate_company_name(cls, v: str) -> str:
        return _validate_bounded_string(v, "company_name", max_len=100)

    @field_validator("target_industry", mode="after")
    @classmethod
    def validate_target_industry(cls, v: str | None) -> str | None:
        return None if v is None else _validate_bounded_string(v, "target_industry", max_len=50)

    @field_validator("company_website", mode="after")
    @classmethod
    def validate_company_website(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = _validate_bounded_string(v, "company_website", max_len=200)
        if not re.match(r"^https?://[^\s/]+\.[^\s]+$", s):
            raise ValueError("company_website must be an http(s) URL")
        return s

    @classmethod
    def from_template(
        cls,
        company_name: str,
        sales_template: SalesTemplateSelection,
        target_industry: str | None = None,
        seller_company: str = "미입력",
        company_website: str | None = None,
    ) -> "BriefingCreateRequest":
        """메신저/MCP 경로: 기업명 + 저장된 템플릿만으로 요청을 만든다."""
        profile = sales_template.resolve().to_sales_profile(seller_company)
        return cls(
            company_name=company_name,
            sales_profile=BoundedSalesProfile(**profile.model_dump()),
            sales_template=sales_template,
            target_industry=target_industry,
            company_website=company_website,
        )


class BriefingJobSubmitResponse(StrictBaseModel):
    """Response returned upon POST /v1/briefings (HTTP 202 Accepted)."""

    job_id: str = Field(..., description="작업 식별자 UUID")
    status: JobStatus = Field(default="PENDING", description="작업 접수 상태")
    status_url: str = Field(..., description="작업 상태 조회 URL")
    result_url: str = Field(..., description="브리핑 결과 조회 URL")
    provenance: JobProvenance = Field(default="MOCK_VIRTUAL", description="실행 프로비넌스 (오프라인 가상)")


class BriefingJobStatusResponse(StrictBaseModel):
    """Typed immutable snapshot returned upon GET /v1/briefing-jobs/{job_id} (HTTP 200)."""

    job_id: str = Field(..., description="작업 식별자 UUID")
    status: JobStatus = Field(..., description="현재 작업 상태")
    provenance: JobProvenance = Field(default="MOCK_VIRTUAL", description="실행 프로비넌스")
    created_at: str = Field(..., description="작업 생성이시")
    completed_at: str | None = Field(default=None, description="작업 완료/실패 시시")
    error_code: str | None = Field(default=None, description="작업 실패 시 정화된 에러 코드")
    error_http_status: int | None = Field(default=None, description="작업 실패 시 매핑될 HTTP 상태 코드")


class JobRecord(StrictBaseModel):
    """Internal typed in-memory storage record for a briefing job."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    job_id: str
    briefing_id: str
    status: JobStatus = "PENDING"
    provenance: JobProvenance = "MOCK_VIRTUAL"
    created_at: str = Field(default_factory=current_iso_time)
    completed_at: str | None = None
    request_data: BriefingCreateRequest
    result: BriefingObject | None = None
    error_code: str | None = None
    error_http_status: int | None = None
    error_message: str | None = None
