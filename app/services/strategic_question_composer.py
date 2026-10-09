"""P5 질문 3선 생성 및 서버 측 무결성 검증.

LLM은 문장만 만든다. 다음은 서버가 강제한다.
- 인용 evidence_id는 FACT_CONFIRMED 근거만 허용 (위반 시 INVALID_CITATION으로 fail-closed)
- Q1은 기업 범위, Q2는 산업 범위 근거만 인용
- Q3의 value_prop_id는 영업사원이 선택한 소구점이어야 함
- grounded 값은 LLM 응답을 무시하고 서버가 다시 계산
"""

from typing import Any

from pydantic import ValidationError

from app.core.exceptions import CitationIntegrityException, ProviderException
from app.domain.models import Evidence
from app.domain.pipeline_models import PROMPT_VERSION_P5
from app.domain.sales_templates import ResolvedSalesTemplate
from app.domain.strategic_questions import EvidenceScope, StrategicQuestionSet
from app.prompts.p5_strategic_questions import SYSTEM_PROMPT_P5
from app.prompts.pipeline_prompts import format_external_fact_excerpt
from app.providers.base import ReasoningProvider
from app.services.dual_research import evidence_scope
from app.services.pipeline_services import raise_provider_exception

REQUIRED_SCOPE: dict[str, EvidenceScope] = {
    "COMPANY_ISSUE": "COMPANY",
    "INDUSTRY_TREND": "INDUSTRY",
}


class StrategicQuestionComposerService:
    def __init__(self, reasoning_provider: ReasoningProvider, model: str = "mock-model"):
        self.provider = reasoning_provider
        self.model = model

    async def compose_questions(
        self,
        *,
        company_name: str,
        industry: str | None,
        template: ResolvedSalesTemplate,
        confirmed_evidences: list[Evidence],
    ) -> StrategicQuestionSet:
        user_payload = {
            "company_name": company_name,
            "industry": industry,
            "sales_template": {
                "category": template.category_label,
                "product": template.product_label,
                "value_props": [v.model_dump() for v in template.value_props],
            },
            "confirmed_facts": [
                {
                    "evidence_id": e.evidence_id,
                    "scope": evidence_scope(e) or "COMPANY",
                    "claim": format_external_fact_excerpt(e.evidence_id, self._claim_text(e)),
                    "publisher": e.publisher,
                    "published_at": e.published_at,
                }
                for e in confirmed_evidences
            ],
        }

        result = await self.provider.generate_structured(
            task="p5_strategic_questions",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_P5},
                {"role": "user", "content": str(user_payload)},
            ],
            response_schema=StrategicQuestionSet.model_json_schema(),
            model=self.model,
        )

        if not result.success:
            raise_provider_exception(result, "P5 strategic question composer")
        if not result.structured_data:
            raise ProviderException(
                message="P5 strategic question composer returned no structured data",
                error_code=result.error_code or "STRUCTURED_OUTPUT_MISSING",
            )

        data = dict(result.structured_data)
        data.pop("version", None)
        try:
            question_set = StrategicQuestionSet.model_validate(data)
        except ValidationError as exc:
            raise ProviderException(
                message="P5 strategic question composer returned invalid structured data",
                error_code="PROVIDER_INVALID_JSON",
            ) from exc

        return self._enforce_integrity(question_set, template, confirmed_evidences)

    @staticmethod
    def _claim_text(evidence: Evidence) -> str:
        if evidence.verification_record:
            return evidence.verification_record.target_claim
        return evidence.claim

    @staticmethod
    def _enforce_integrity(
        question_set: StrategicQuestionSet,
        template: ResolvedSalesTemplate,
        confirmed_evidences: list[Evidence],
    ) -> StrategicQuestionSet:
        scope_by_id = {e.evidence_id: (evidence_scope(e) or "COMPANY") for e in confirmed_evidences if e.is_confirmed_fact}

        unknown = sorted(question_set.cited_evidence_ids() - scope_by_id.keys())
        if unknown:
            raise CitationIntegrityException(
                message=f"P5 question referenced unconfirmed or invalid evidence_id: {unknown}",
                detail={"unconfirmed_citations": unknown},
            )

        for q in question_set.questions:
            required = REQUIRED_SCOPE.get(q.type)
            if required:
                wrong = sorted(eid for eid in q.evidence_ids if scope_by_id[eid] != required)
                if wrong:
                    raise CitationIntegrityException(
                        message=f"P5 {q.type} question cited out-of-scope evidence: {wrong}",
                        detail={"out_of_scope_citations": wrong, "required_scope": required},
                    )
            if q.type == "SOLUTION_BRIDGE" and q.value_prop_id not in template.value_prop_ids():
                raise CitationIntegrityException(
                    message="P5 SOLUTION_BRIDGE referenced a value proposition the salesperson did not select",
                    detail={"value_prop_id": q.value_prop_id},
                )
            q.grounded = bool(q.evidence_ids)

        return question_set


def build_mock_p5_payload(
    company_name: str,
    industry: str | None,
    template: ResolvedSalesTemplate,
    confirmed_evidences: list[Evidence],
) -> dict[str, Any]:
    """오프라인 Mock: 확정 근거와 선택 소구점만으로 결정적인 질문 3선을 만든다."""
    company_ev = [e for e in confirmed_evidences if evidence_scope(e) != "INDUSTRY"]
    industry_ev = [e for e in confirmed_evidences if evidence_scope(e) == "INDUSTRY"]
    industry_name = industry or "해당 산업"
    vp = template.value_props[0]

    if company_ev:
        q1 = f"최근 {company_name}의 사업 확장 소식을 봤는데, 현장에서는 어떤 변화가 가장 크게 느껴지시나요?"
    else:
        q1 = f"요즘 {company_name}에서 가장 공들이고 계신 사업 변화는 어떤 건가요?"
    if industry_ev:
        q2 = f"{industry_name} 업계 전반에 원가 부담 이야기가 많은데, 실제로 체감하시는 정도는 어떠세요?"
    else:
        q2 = f"요즘 {industry_name} 업계에서 공통적으로 고민하시는 과제는 어떤 게 있을까요?"
    q3 = f"이런 변화 속에서 {template.product_label} 운영과 관련해 '{vp.label}' 측면의 고민은 없으신가요?"

    return {
        "version": PROMPT_VERSION_P5,
        "questions": [
            {
                "type": "COMPANY_ISSUE",
                "question": q1,
                "intent": "최근 행보 인지 + 변화에 따른 운영 부담 파악",
                "evidence_ids": [e.evidence_id for e in company_ev[:2]],
            },
            {
                "type": "INDUSTRY_TREND",
                "question": q2,
                "intent": "산업 공통 Pain Point에 대한 현장 체감 확인",
                "evidence_ids": [e.evidence_id for e in industry_ev[:2]],
            },
            {
                "type": "SOLUTION_BRIDGE",
                "question": q3,
                "intent": f"[{vp.group_label}] 소구점으로 이어질 기회 탐색",
                "evidence_ids": [],
                "value_prop_id": vp.id,
            },
        ],
    }
