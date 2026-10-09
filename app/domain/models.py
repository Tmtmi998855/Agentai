from datetime import datetime, timezone
from typing import Literal, Any
import uuid
from pydantic import BaseModel, Field, ConfigDict, model_validator


def current_iso_time() -> str:
    return datetime.now(timezone.utc).isoformat()


class StrictBaseModel(BaseModel):
    """Base model with extra fields forbidden for strict validation."""
    model_config = ConfigDict(extra="forbid")


class SalesProfile(StrictBaseModel):
    """B2B Sales context profile."""
    company: str = Field(..., description="영업 담당자 소속 회사명")
    industry: str = Field(..., description="산업군")
    product_service: str = Field(..., description="취급 상품 및 서비스")
    target_customer: str = Field(..., description="타깃 고객 유형")
    sales_goal: str = Field(..., description="영업 목표")


class CompanyEntity(StrictBaseModel):
    """Entity information for target company."""
    name: str = Field(..., description="입력된 기업명")
    resolved_name: str | None = Field(default=None, description="식별된 정식 법인명 (LOW 신뢰도 시 null)")
    entity_confidence: Literal["HIGH", "MEDIUM", "LOW"] = Field(..., description="식별 신뢰도")
    candidate_entities: list[str] = Field(default_factory=list, description="식별 신뢰도 LOW 시 후보 법인 명칭 목록")
    website: str | None = Field(default=None, description="홈페이지 URL")
    industry: str | None = Field(default=None, description="주요 업종")
    region: str | None = Field(default=None, description="사업장 소재지")


class MeetingContext(StrictBaseModel):
    """Optional meeting context details."""
    department: str | None = Field(default=None, description="고객사 미팅 부서")
    role: str | None = Field(default=None, description="담당자 직책/역할")
    meeting_purpose: str | None = Field(default=None, description="미팅 목적")
    past_notes: str | None = Field(default=None, description="과거 메모 및 맥락 (검색 쿼리에 유입 금지)")


EvidenceStatus = Literal["RAW_SNIPPET", "CLASSIFIED", "RAW_VERIFIED", "FACT_CONFIRMED", "REVIEW_REQUIRED"]
EvidenceExclusionReason = Literal["URL_MISSING", "URL_INVALID"]


class EvidenceExclusion(StrictBaseModel):
    """Search item excluded before Evidence creation, with an auditable reason."""
    item_id: str
    reason: EvidenceExclusionReason


class FactVerificationRecord(StrictBaseModel):
    """Audit record proving that raw text content or manual review verifies a specific claim."""
    target_claim: str = Field(..., description="확인 대상 claim 문장")
    supporting_excerpt: str = Field(..., description="이를 뒷받침하는 짧은 원문 구절")
    url: str = Field(..., description="원문 URL")
    verification_method: Literal["EXACT_EXCERPT_MATCH", "MANUAL_REVIEW"] = Field(..., description="확인 방식")
    excerpt_found: bool = Field(default=True, description="원문 내 뒷받침 구절 존재 여부")
    claim_confirmed: bool = Field(default=True, description="주장의 의미적 사실 확인 여부")
    review_decision: Literal["APPROVED", "REJECTED", "PENDING"] = Field(default="APPROVED", description="검토 승인 결과")
    verified_at: str = Field(default_factory=current_iso_time, description="확인 시각")
    verified_by: str | None = Field(default=None, description="수동 확인 시 확인자 ID")
    verification_notes: str | None = Field(default=None, description="검토 메모 및 사유")

    @model_validator(mode="after")
    def validate_verification_identity(self) -> "FactVerificationRecord":
        if self.verification_method == "EXACT_EXCERPT_MATCH" and self.verified_by not in (
            None,
            "SYSTEM_EXACT_MATCH",
        ):
            raise ValueError("EXACT_EXCERPT_MATCH verified_by must be None or SYSTEM_EXACT_MATCH")
        if self.verification_method == "MANUAL_REVIEW" and (
            not self.verified_by or not self.verified_by.strip()
        ):
            raise ValueError("verified_by is required for MANUAL_REVIEW verification method")
        if self.verification_method == "MANUAL_REVIEW" and (
            not self.verification_notes or not self.verification_notes.strip()
        ):
            raise ValueError("verification_notes is required for MANUAL_REVIEW verification method")
        return self


class Evidence(StrictBaseModel):
    """Verified factual intelligence piece (FACT)."""
    evidence_id: str = Field(..., description="고유 증거 식별자 (예: E01, E02)")
    claim: str = Field(..., description="검증된 단일 사실 문장")
    published_at: str | None = Field(default=None, description="발행일자 (YYYY-MM-DD), 미확인 시 None")
    publisher: str = Field(..., description="출처/언론사/발행기관")
    url: str = Field(..., description="정규화된 출처 URL")
    raw_url: str | None = Field(default=None, description="감사 목적 원본 URL")
    source_tier: Literal["A", "B", "C", "REVIEW_REQUIRED"] = Field(..., description="출처 신뢰도 등급")
    status: EvidenceStatus = Field(default="CLASSIFIED", description="증거 처리 및 검증 상태 (RAW_SNIPPET -> CLASSIFIED -> RAW_VERIFIED -> FACT_CONFIRMED)")
    retrieved_at: str = Field(default_factory=current_iso_time, description="수집 일시")
    relevance_tags: list[str] = Field(default_factory=list, description="관련 태그 목록")
    duplicate_group_id: str | None = Field(default=None, description="동일 이슈 중복 출처 그룹 식별자")
    verified_raw_content: str | None = Field(default=None, description="수집된 원문 전체 텍스트")
    verification_record: FactVerificationRecord | None = Field(default=None, description="사실 확인 검증 기록")
    verified_by: str | None = Field(default=None, description="수동 검토자 식별자")
    verification_notes: str | None = Field(default=None, description="수동 검토 기록")
    verified_at: str | None = Field(default=None, description="검증 완료 시각")

    @property
    def is_confirmed_fact(self) -> bool:
        """
        Returns True ONLY if fact verification is explicitly completed (status == 'FACT_CONFIRMED').
        Source tier A or B alone DOES NOT grant confirmed fact status.
        Snippet collection, tier classification, raw verification, and fact verification are distinct states.
        """
        return (
            self.status == "FACT_CONFIRMED"
            and self.source_tier in ("A", "B", "C")
            and "REVIEW_REQUIRED" not in self.relevance_tags
            and self.verification_record is not None
            and (
                self.verification_record.verification_method == "MANUAL_REVIEW"
                or self.verification_record.excerpt_found
            )
            and self.verification_record.claim_confirmed
            and self.verification_record.review_decision == "APPROVED"
        )

    @property
    def can_support_strong_signal(self) -> bool:
        """Unconfirmed or REVIEW_REQUIRED evidence cannot be used as primary support for strong demand signals."""
        return self.is_confirmed_fact and self.source_tier in ("A", "B")

    def verify_raw(self, raw_content: str) -> "Evidence":
        """Stage 1: Fetches and stores raw content, transitioning status to RAW_VERIFIED."""
        if not raw_content or not raw_content.strip():
            raise ValueError("Raw content cannot be empty for raw verification")
        self.verified_raw_content = raw_content.strip()
        if self.status in ("RAW_SNIPPET", "CLASSIFIED"):
            self.status = "RAW_VERIFIED"
        return self

    def confirm_fact(
        self,
        target_claim: str,
        supporting_excerpt: str,
        verification_method: Literal["EXACT_EXCERPT_MATCH", "MANUAL_REVIEW"],
        verified_by: str | None = None,
        verification_notes: str | None = None,
        review_decision: Literal["APPROVED", "REJECTED", "PENDING"] = "APPROVED",
    ) -> "Evidence":
        """
        Stage 2: Verifies supporting excerpt or manual review decision.
        If review_decision == 'REJECTED', raises ValueError and stays unconfirmed.
        """
        if self.status != "RAW_VERIFIED" and not (
            self.status == "CLASSIFIED" and verification_method == "MANUAL_REVIEW"
        ):
            raise ValueError(
                "Fact confirmation requires RAW_VERIFIED status or CLASSIFIED status with MANUAL_REVIEW"
            )

        if not target_claim.strip():
            raise ValueError("target_claim is required for fact confirmation")

        if not supporting_excerpt.strip():
            raise ValueError("supporting_excerpt is required for fact confirmation")

        excerpt_clean = supporting_excerpt.strip()

        if verification_method == "EXACT_EXCERPT_MATCH":
            if not self.verified_raw_content:
                raise ValueError("Cannot perform EXACT_EXCERPT_MATCH without prior raw content verification (verify_raw)")

            if excerpt_clean not in self.verified_raw_content:
                raise ValueError(f"supporting_excerpt '{excerpt_clean[:50]}...' was not found in verified raw content")

            if review_decision == "REJECTED":
                raise ValueError("EXACT_EXCERPT_MATCH cannot use review_decision REJECTED")

        elif verification_method == "MANUAL_REVIEW":
            if not verified_by or not verified_by.strip():
                raise ValueError("verified_by is required for MANUAL_REVIEW verification method")
            if not verification_notes or not verification_notes.strip():
                raise ValueError("verification_notes is required for MANUAL_REVIEW verification method")
            if review_decision == "REJECTED":
                raise ValueError("Manual review rejected the target claim")

        else:
            raise ValueError(f"Unsupported verification_method: {verification_method}")

        rec = FactVerificationRecord(
            target_claim=target_claim.strip(),
            supporting_excerpt=excerpt_clean,
            url=self.url,
            verification_method=verification_method,
            excerpt_found=bool(self.verified_raw_content and excerpt_clean in self.verified_raw_content),
            claim_confirmed=verification_method == "EXACT_EXCERPT_MATCH" or review_decision == "APPROVED",
            review_decision="APPROVED" if verification_method == "EXACT_EXCERPT_MATCH" else review_decision,
            verified_at=current_iso_time(),
            verified_by=("SYSTEM_EXACT_MATCH" if verification_method == "EXACT_EXCERPT_MATCH" else verified_by.strip()),
            verification_notes=verification_notes.strip() if verification_notes else None,
        )

        self.verification_record = rec
        self.verified_by = rec.verified_by
        self.verification_notes = rec.verification_notes
        self.verified_at = rec.verified_at
        self.status = "FACT_CONFIRMED" if rec.claim_confirmed and rec.review_decision == "APPROVED" else "REVIEW_REQUIRED"
        return self


class EvidencePack(StrictBaseModel):
    """Collection of gathered evidences for a target company."""
    company_name: str
    evidences: list[Evidence] = Field(default_factory=list)
    excluded_items: list[EvidenceExclusion] = Field(default_factory=list)
    retrieved_at: str = Field(default_factory=current_iso_time)

    def get_evidence_ids(self) -> set[str]:
        return {e.evidence_id for e in self.evidences}

    def find_evidence(self, evidence_id: str) -> Evidence | None:
        for e in self.evidences:
            if e.evidence_id == evidence_id:
                return e
        return None

    def validate_fact_promotion(self, hypothesis: "DemandHypothesisDraft") -> list[str]:
        """
        Ensures REVIEW_REQUIRED items are not promoted as confirmed FACTs for strong demand hypothesis support.
        """
        violations = []
        for eid in hypothesis.supporting_evidence:
            ev = self.find_evidence(eid)
            if ev and not ev.is_confirmed_fact:
                violations.append(
                    f"Evidence {eid} (tier: {ev.source_tier}) is marked REVIEW_REQUIRED and cannot be promoted to confirmed FACT"
                )
        return violations


HypothesisStatus = Literal["ACTIVE", "INSUFFICIENT_EVIDENCE", "REJECTED"]
SignalLevel = Literal["NONE", "WEAK", "MODERATE", "STRONG", "VERY_STRONG"]


class DemandHypothesisDraft(StrictBaseModel):
    """Unscored demand hypothesis generated by LLM reasoning stage (NO signal_level)."""
    title: str = Field(..., description="가설 제목 (예: 업무용 차량 증차 수요)")
    reason: str = Field(..., description="가설 도출 근거 요약")
    reasoning_chain: list[str] = Field(..., description="논리 전개 단계 (FACT -> INTERPRETATION -> DEMAND)")
    supporting_evidence: list[str] = Field(..., description="찬성 근거 evidence_id 목록")
    contradicting_evidence: list[str] = Field(default_factory=list, description="반대/약화 근거 evidence_id 목록")
    questions: list[str] = Field(default_factory=list, description="미팅에서 가설을 확인할 질문 목록")
    status: HypothesisStatus = Field(default="ACTIVE")

    @model_validator(mode="after")
    def validate_evidence_uniqueness_and_conflict(self) -> "DemandHypothesisDraft":
        if len(self.supporting_evidence) != len(set(self.supporting_evidence)):
            raise ValueError("Duplicate evidence_id found in supporting_evidence")

        if len(self.contradicting_evidence) != len(set(self.contradicting_evidence)):
            raise ValueError("Duplicate evidence_id found in contradicting_evidence")

        overlap = set(self.supporting_evidence) & set(self.contradicting_evidence)
        if overlap:
            raise ValueError(f"Conflict: evidence_id(s) {overlap} cannot be both supporting and contradicting")

        return self


class ScoredDemandHypothesis(DemandHypothesisDraft):
    """Hypothesis scored by Server Rule Engine containing mandatory signal_level."""
    signal_level: SignalLevel = Field(..., description="Rule Engine이 계산한 최종 신호 강도")


def score_hypothesis(draft: DemandHypothesisDraft, signal_level: SignalLevel) -> ScoredDemandHypothesis:
    """Explicit server-side transformation from Draft to Scored hypothesis."""
    data = draft.model_dump()
    data["signal_level"] = signal_level
    return ScoredDemandHypothesis(**data)


class CompanySnapshot(StrictBaseModel):
    """Brief summary of target company facts."""
    summary: str = Field(..., description="기업 현황 요약 (3~5줄)")
    evidence_ids: list[str] = Field(default_factory=list, description="연결된 evidence_id 목록")


class SmallTalk(StrictBaseModel):
    """Conversation starter topic backed by factual evidence."""
    topic: str = Field(..., description="아이스브레이킹 주제")
    talking_point: str = Field(..., description="구체적 대화 소재")
    evidence_ids: list[str] = Field(default_factory=list, description="연결된 evidence_id 목록")


class BriefingSource(StrictBaseModel):
    """Customer-facing public source model excluding internal audit & raw content fields."""
    evidence_id: str = Field(..., description="증거 식별자 (예: E01)")
    claim: str = Field(..., description="확인된 사실 문장")
    publisher: str = Field(..., description="발행처/출처")
    url: str = Field(..., description="원문 URL")
    published_at: str | None = Field(default=None, description="발행일자 (YYYY-MM-DD)")
    source_tier: Literal["A", "B", "C"] = Field(..., description="출처 신뢰도 등급")

    @classmethod
    def from_evidence(cls, evidence: Evidence) -> "BriefingSource":
        if not evidence.is_confirmed_fact:
            raise ValueError(f"Only FACT_CONFIRMED evidence can become a BriefingSource (got unconfirmed evidence {evidence.evidence_id})")
        claim_text = (
            evidence.verification_record.target_claim
            if evidence.verification_record
            else evidence.claim
        )
        tier = evidence.source_tier if evidence.source_tier in ("A", "B", "C") else "C"
        return cls(
            evidence_id=evidence.evidence_id,
            claim=claim_text,
            publisher=evidence.publisher,
            url=evidence.url,
            published_at=evidence.published_at,
            source_tier=tier,
        )


BriefingObjectStatus = Literal["SUCCESS", "INSUFFICIENT_EVIDENCE", "ENTITY_AMBIGUOUS"]


class BriefingObject(StrictBaseModel):
    """Final briefing presentation object combining FACTS and HYPOTHESES."""
    status: BriefingObjectStatus = Field(default="SUCCESS", description="브리핑 생성 상태")
    company: CompanyEntity
    company_snapshot: CompanySnapshot
    small_talk: list[SmallTalk] = Field(default_factory=list)
    demand_hypotheses: list[ScoredDemandHypothesis] = Field(default_factory=list)
    meeting_questions: list[str] = Field(default_factory=list, description="미팅 확인 질문 3~5개")
    sources: list[BriefingSource] = Field(default_factory=list, description="고객용 확정 출처 목록")
    warnings: list[str] = Field(default_factory=list)
    status: Literal["SUCCESS", "INSUFFICIENT_EVIDENCE", "ENTITY_AMBIGUOUS"] = "SUCCESS"
    created_at: str = Field(default_factory=current_iso_time)
    sources: list[BriefingSource] = Field(default_factory=list)

    def validate_citations(self) -> list[str]:
        valid_ids = {s.evidence_id for s in self.sources}
        invalid_references = []

        for eid in self.company_snapshot.evidence_ids:
            if eid not in valid_ids:
                invalid_references.append(f"company_snapshot referenced unknown evidence_id: {eid}")

        for item in self.small_talk:
            for eid in item.evidence_ids:
                if eid not in valid_ids:
                    invalid_references.append(f"small_talk[{item.topic}] referenced unknown evidence_id: {eid}")

        for hyp in self.demand_hypotheses:
            for eid in hyp.supporting_evidence:
                if eid not in valid_ids:
                    invalid_references.append(f"hypothesis[{hyp.title}] supporting_evidence unknown: {eid}")
            for eid in hyp.contradicting_evidence:
                if eid not in valid_ids:
                    invalid_references.append(f"hypothesis[{hyp.title}] contradicting_evidence unknown: {eid}")

        return invalid_references


class ProviderRequest(StrictBaseModel):
    """Request payload sent to ReasoningProvider."""
    task: str
    messages: list[dict[str, Any]]
    response_schema: dict[str, Any]
    model: str
    timeout_s: int = Field(default=30, ge=1)


class ProviderResult(StrictBaseModel):
    """Execution result from ReasoningProvider."""
    provider: str
    requested_model: str
    actual_model: str
    content: str | None = None
    structured_data: dict[str, Any] | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    raw_response: dict[str, Any] | None = None
    success: bool = True
    error: str | None = None
    error_code: str | None = None


class ProviderRun(StrictBaseModel):
    """Observability run log for auditing and billing analysis."""
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = Field(default_factory=current_iso_time)
    provider: str
    requested_model: str
    actual_model: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_latency_ms: float = 0.0
    cost_usd: float = 0.0
    status: Literal["SUCCESS", "FAILED", "FALLBACK"] = "SUCCESS"
    error_code: str | None = None


class ErrorResponse(StrictBaseModel):
    """Standardized API and domain error response."""
    error_code: str
    message: str
    detail: dict[str, Any] | None = None
    timestamp: str = Field(default_factory=current_iso_time)
