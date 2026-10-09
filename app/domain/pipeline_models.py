from datetime import datetime, timezone
from typing import Literal, Any
from pydantic import Field
from app.domain.models import (
    StrictBaseModel,
    SalesProfile,
    CompanyEntity,
    MeetingContext,
    Evidence,
    EvidencePack,
    DemandHypothesisDraft,
    current_iso_time,
)
from app.domain.search_models import SearchQuery


# Prompt Versions
PROMPT_VERSION_P1 = "1.0.0"
PROMPT_VERSION_P2 = "1.0.0"
PROMPT_VERSION_P3 = "1.0.0"
PROMPT_VERSION_P4 = "1.0.0"


# P1 Profile Compiler Schemas
class CompiledProfile(StrictBaseModel):
    """Output schema for P1 Profile Compiler (Versioned)."""
    version: str = Field(default=PROMPT_VERSION_P1, description="P1 프롬프트/스키마 버전")
    company_name: str = Field(..., description="고객사 정식 명칭")
    resolved_name: str = Field(..., description="식별된 정식 법인명")
    industry: str = Field(..., description="산업군")
    product_service: str = Field(..., description="영업 담당자 상품/서비스")
    target_customer: str = Field(..., description="타깃 고객 유형")
    sales_goal: str = Field(..., description="영업 목표")
    focus_topics: list[str] = Field(default_factory=list, description="추출된 주요 관심 주제")
    compiled_at: str = Field(default_factory=current_iso_time)


# P2 Retrieval Planner Schemas
class RetrievalPlan(StrictBaseModel):
    """Output schema for P2 Retrieval Planner (Versioned)."""
    version: str = Field(default=PROMPT_VERSION_P2, description="P2 프롬프트/스키마 버전")
    company_name: str = Field(..., description="대상 기업명")
    approved_topics: list[str] = Field(..., description="검색 안전 승인 공개 주제 목록")
    search_queries: list[SearchQuery] = Field(default_factory=list, description="생성된 공개 검색 쿼리")
    planned_at: str = Field(default_factory=current_iso_time)


# P3 Demand Reasoner Schemas & Input Contract
class ConfirmedFactPayload(StrictBaseModel):
    """Clean, bounded payload of confirmed FACTs passed into P3 LLM reasoning stage."""
    evidence_id: str = Field(..., description="고유 증거 ID")
    confirmed_claim: str = Field(..., description="검증된 단일 사실 문장")
    supporting_excerpt: str = Field(..., description="이를 뒷받침하는 짧은 원문 구절")
    publisher: str = Field(..., description="출처명")
    url: str = Field(..., description="원문 URL")
    published_at: str | None = Field(default=None, description="발행일자")
    source_tier: str = Field(..., description="출처 등급")


class P3Input(StrictBaseModel):
    """Input contract for P3 Demand Reasoner."""
    compiled_profile: CompiledProfile
    evidence_pack: EvidencePack
    confirmed_facts_only: bool = Field(default=True, description="True인 경우 FACT_CONFIRMED 상태의 증거만 허용")

    def get_confirmed_evidences(self) -> list[Evidence]:
        """
        Returns ONLY confirmed FACT evidence (is_confirmed_fact == True).
        Unconfirmed search snippets (status != 'FACT_CONFIRMED') are strictly excluded.
        """
        return [e for e in self.evidence_pack.evidences if e.is_confirmed_fact]

    def get_confirmed_fact_payloads(self) -> list[ConfirmedFactPayload]:
        """
        Constructs clean ConfirmedFactPayload objects ONLY from FACT_CONFIRMED evidence.
        Excludes full raw document text and unconfirmed search snippets.
        """
        payloads = []
        for e in self.evidence_pack.evidences:
            if e.is_confirmed_fact and e.verification_record:
                payloads.append(ConfirmedFactPayload(
                    evidence_id=e.evidence_id,
                    confirmed_claim=e.verification_record.target_claim,
                    supporting_excerpt=e.verification_record.supporting_excerpt,
                    publisher=e.publisher,
                    url=e.url,
                    published_at=e.published_at,
                    source_tier=e.source_tier,
                ))
        return payloads


class DemandReasonerOutput(StrictBaseModel):
    """Output schema for P3 Demand Reasoner (Versioned)."""
    version: str = Field(default=PROMPT_VERSION_P3, description="P3 프롬프트/스키마 버전")
    status: Literal["SUCCESS", "INSUFFICIENT_EVIDENCE"] = Field(
        default="SUCCESS", description="가설 생성 상태"
    )
    drafts: list[DemandHypothesisDraft] = Field(default_factory=list, description="생성된 수요 가설 초안")
    reasoning_summary: str = Field(default="", description="추론 요약 및 근거 평가")
    evaluated_at: str = Field(default_factory=current_iso_time)
