"""P4 서버 조립기와 출력 무결성 검증."""

from typing import Any
from pydantic import ValidationError
from pydantic import Field

from app.core.exceptions import CitationIntegrityException, ProviderException
from app.domain.models import (
    BriefingObject,
    BriefingSource,
    CompanyEntity,
    CompanySnapshot,
    DemandHypothesisDraft,
    Evidence,
    EvidencePack,
    ScoredDemandHypothesis,
    SmallTalk,
    StrictBaseModel,
)
from app.domain.pipeline_models import PROMPT_VERSION_P4
from app.prompts.p4_briefing_composer import SYSTEM_PROMPT_P4
from app.providers.base import ReasoningProvider
from app.services.briefing_service import BriefingService
from app.services.pipeline_services import raise_provider_exception


class P4BriefingPayload(StrictBaseModel):
    """Provider가 반환하는 P4 구조에서 서버 소유 필드를 제외한 계약."""

    version: str = PROMPT_VERSION_P4
    company_snapshot: CompanySnapshot
    small_talk: list[SmallTalk] = Field(default_factory=list)
    demand_hypotheses: list[ScoredDemandHypothesis] = Field(default_factory=list)
    meeting_questions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class BriefingComposerService:
    """P4 출력이 기존 FACT와 Rule Engine 결과를 변경하지 않았는지 검증한다."""

    def __init__(self, reasoning_provider: ReasoningProvider, model: str = "mock-model"):
        self.provider = reasoning_provider
        self.model = model

    async def compose(
        self,
        company: CompanyEntity,
        evidence_pack: EvidencePack,
        scored_hypotheses: list[ScoredDemandHypothesis],
        compiled_profile: Any = None,
    ) -> BriefingObject:
        """compose_briefing의 짧은 공개 별칭."""
        return await self.compose_briefing(company, evidence_pack, scored_hypotheses, compiled_profile)

    async def compose_briefing(
        self,
        company: CompanyEntity,
        evidence_pack: EvidencePack,
        scored_hypotheses: list[ScoredDemandHypothesis],
        compiled_profile: Any = None,
    ) -> BriefingObject:
        """확정 source와 scored hypothesis를 P4 Briefing JSON으로 조립한다."""
        if company.entity_confidence == "LOW":
            return self._entity_ambiguous_briefing(company)

        confirmed_evidences = [e for e in evidence_pack.evidences if e.is_confirmed_fact]
        if not confirmed_evidences:
            return self._insufficient_briefing(company)
        confirmed_source_ids = {source.evidence_id for source in confirmed_evidences}
        sanitized_scored_hypotheses = [
            self._sanitize_hypothesis(hypothesis, confirmed_source_ids)
            for hypothesis in scored_hypotheses
        ]

        briefing_sources = [BriefingSource.from_evidence(e) for e in confirmed_evidences]

        result = await self.provider.generate_structured(
            task="p4_briefing_composition",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_P4},
                {
                    "role": "user",
                    "content": str(
                        {
                            "version": PROMPT_VERSION_P4,
                            "company": company.model_dump(),
                            "confirmed_sources": [s.model_dump() for s in briefing_sources],
                            "scored_hypotheses": [h.model_dump() for h in sanitized_scored_hypotheses],
                        }
                    ),
                },
            ],
            response_schema=P4BriefingPayload.model_json_schema(),
            model=self.model,
        )

        if not result.success:
            raise_provider_exception(result, "P4 briefing composer")

        if not result.structured_data:
            raise ProviderException(
                message="P4 briefing composer provider returned no structured data",
                error_code=result.error_code or "STRUCTURED_OUTPUT_MISSING",
                detail={"error": result.error},
            )

        try:
            payload = P4BriefingPayload(**result.structured_data)
        except ValidationError as exc:
            raise ProviderException(
                message="P4 briefing composer provider returned invalid structured data",
                error_code="PROVIDER_INVALID_JSON",
            ) from exc

        self._validate_limits(payload)
        self._validate_server_owned_fields(payload, company, briefing_sources, scored_hypotheses)
        warnings = list(payload.warnings)
        if not scored_hypotheses and "확정된 FACT가 부족하여 수요 가설을 생성하지 않았습니다." not in warnings:
            warnings.append("확정된 FACT가 부족하여 수요 가설을 생성하지 않았습니다.")
        briefing = BriefingObject(
            status="SUCCESS",
            company=company,
            company_snapshot=payload.company_snapshot,
            small_talk=payload.small_talk,
            demand_hypotheses=payload.demand_hypotheses,
            meeting_questions=payload.meeting_questions,
            sources=briefing_sources,
            warnings=warnings,
        )
        BriefingService.validate_briefing_citations(briefing)
        return briefing

    def _validate_limits(self, payload: P4BriefingPayload) -> None:
        summary_lines = [line for line in payload.company_snapshot.summary.splitlines() if line.strip()]
        if not 3 <= len(summary_lines) <= 5:
            raise CitationIntegrityException(message="P4 company summary must contain 3 to 5 lines")
        if len(payload.small_talk) > 3:
            raise CitationIntegrityException(message="P4 small_talk must contain at most 3 items")
        if len(payload.demand_hypotheses) > 3:
            raise CitationIntegrityException(message="P4 demand_hypotheses must contain at most 3 items")
        if not 3 <= len(payload.meeting_questions) <= 5:
            raise CitationIntegrityException(message="P4 meeting_questions must contain 3 to 5 items")

    def _validate_server_owned_fields(
        self,
        payload: P4BriefingPayload,
        company: CompanyEntity,
        sources: list[BriefingSource],
        hypotheses: list[ScoredDemandHypothesis],
    ) -> list[ScoredDemandHypothesis]:
        source_ids = {source.evidence_id for source in sources}
        for evidence_id in payload.company_snapshot.evidence_ids:
            if evidence_id not in source_ids:
                raise CitationIntegrityException(message="P4 cited a non-confirmed source")
        for item in payload.small_talk:
            if any(evidence_id not in source_ids for evidence_id in item.evidence_ids):
                raise CitationIntegrityException(message="P4 small_talk cited a non-confirmed source")

        allowed = {
            self._sanitize_hypothesis(hypothesis, source_ids).model_dump_json(): hypothesis
            for hypothesis in hypotheses
        }
        for hypothesis in payload.demand_hypotheses:
            sanitized_hypothesis = self._sanitize_hypothesis(hypothesis, source_ids)
            if sanitized_hypothesis.model_dump_json() not in allowed:
                raise CitationIntegrityException(
                    message="P4 created or changed a demand hypothesis or signal level"
                )
        return [
            self._sanitize_hypothesis(hypothesis, source_ids)
            for hypothesis in payload.demand_hypotheses
        ]

    def _entity_ambiguous_briefing(self, company: CompanyEntity) -> BriefingObject:
        candidates = company.candidate_entities or [f"{company.name} A", f"{company.name} B"]
        company_ambiguous = CompanyEntity(
            name=company.name,
            resolved_name=None,  # MUST be null, not status string
            entity_confidence=company.entity_confidence,
            candidate_entities=candidates,
            website=company.website,
            industry=company.industry,
            region=company.region,
        )

        candidates_text = ", ".join(candidates)
        return BriefingObject(
            status="ENTITY_AMBIGUOUS",
            company=company_ambiguous,
            company_snapshot=CompanySnapshot(
                summary=(
                    f"입력된 기업명('{company.name}')의 식별 신뢰도가 낮아({company.entity_confidence}) 브리핑 작성을 유보했습니다.\n"
                    f"식별된 법인 후보: {candidates_text}\n"
                    "정확한 정식 법인을 선택한 후 생성을 다시 시도하세요."
                ),
                evidence_ids=[],
            ),
            small_talk=[],
            demand_hypotheses=[],
            meeting_questions=[
                "정확한 정식 법인명과 사업자 등록번호를 선택/확인해 주시겠습니까?",
                "고객사의 주 사업장 소재지 및 대표자명을 확인해 주시겠습니까?",
                "현재 미팅 예정인 부서 또는 사업부 정보를 선택해 주시겠습니까?",
            ],
            warnings=[
                "기업 식별 신뢰도가 낮습니다. 후보 법인을 선택한 뒤 다시 시도하세요.",
            ],
            sources=[],
        )

    @staticmethod
    def _sanitize_hypothesis(
        hypothesis: ScoredDemandHypothesis,
        source_ids: set[str],
    ) -> ScoredDemandHypothesis:
        """가설 인용에서 고객용 확정 출처 ID만 남긴다."""
        return hypothesis.model_copy(
            update={
                "supporting_evidence": [
                    evidence_id
                    for evidence_id in hypothesis.supporting_evidence
                    if evidence_id in source_ids
                ],
                "contradicting_evidence": [
                    evidence_id
                    for evidence_id in hypothesis.contradicting_evidence
                    if evidence_id in source_ids
                ],
            }
        )

    def _ambiguous_briefing(self, company: CompanyEntity) -> BriefingObject:
        return BriefingObject(
            company=company,
            company_snapshot=CompanySnapshot(
                summary="기업 후보가 확정되지 않았습니다.\n현재 공개 자료를 특정 법인에 연결할 수 없습니다.\n후보 법인을 선택한 뒤 브리핑을 다시 생성하세요.",
                evidence_ids=[],
            ),
            meeting_questions=[
                "미팅 대상 법인의 정확한 법인명은 무엇인가요?",
                "후보 법인을 구분할 수 있는 사업장 또는 서비스 정보가 있나요?",
                "현재 확인이 필요한 사업 과제는 무엇인가요?",
            ],
            warnings=["기업 식별 신뢰도가 낮습니다. 후보 법인을 선택한 뒤 다시 시도하세요."],
            sources=[],
            status="ENTITY_AMBIGUOUS",
        )

    def _insufficient_briefing(self, company: CompanyEntity) -> BriefingObject:
        return BriefingObject(
            status="INSUFFICIENT_EVIDENCE",
            company=company,
            company_snapshot=CompanySnapshot(
                summary=(
                    "확정된 공개 공시 및 뉴스 근거가 부족합니다.\n"
                    "현재 수집된 정보만으로는 기업 현황을 판단할 수 없습니다.\n"
                    "추가 검증된 공시 자료 수집 후 브리핑을 업데이트하세요."
                ),
                evidence_ids=[],
            ),
            meeting_questions=[
                "최근 주요 사업 변화가 있었나요?",
                "현재 가장 우선순위가 높은 운영 과제는 무엇인가요?",
                "관련 계획의 일정과 의사결정 기준은 무엇인가요?",
            ],
            warnings=["확정된 FACT가 부족하여 수요 가설을 생성하지 않았습니다."],
            sources=[],
        )

P4BriefingComposer = BriefingComposerService
