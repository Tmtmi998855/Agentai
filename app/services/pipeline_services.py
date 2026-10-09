from typing import Any
from pydantic import ValidationError
from app.domain.models import (
    SalesProfile,
    CompanyEntity,
    MeetingContext,
    EvidencePack,
    ProviderResult,
)
from app.domain.pipeline_models import (
    CompiledProfile,
    RetrievalPlan,
    P3Input,
    DemandReasonerOutput,
    PROMPT_VERSION_P1,
    PROMPT_VERSION_P2,
    PROMPT_VERSION_P3,
)
from app.providers.base import ReasoningProvider
from app.core.exceptions import (
    CitationIntegrityException,
    ProviderException,
    ProviderAuthException,
    ProviderTimeoutException,
)
from app.prompts.pipeline_prompts import (
    SYSTEM_PROMPT_P1,
    SYSTEM_PROMPT_P2,
    SYSTEM_PROMPT_P3,
    format_external_fact_excerpt,
)
from app.services.search_privacy_filter import SearchPrivacyFilter


def raise_provider_exception(result: ProviderResult, stage_name: str) -> None:
    """Passes provider execution failures cleanly using structured error_code without string searching."""
    error_code = result.error_code or "PROVIDER_ERROR"
    err_msg = result.error or "Unknown provider failure"
    detail = {"error_code": error_code, "error": err_msg}

    if error_code == "PROVIDER_AUTH_ERROR":
        raise ProviderAuthException(
            message=f"{stage_name} provider authentication failed: {err_msg}",
            detail=detail,
        )
    elif error_code == "PROVIDER_TIMEOUT":
        raise ProviderTimeoutException(
            message=f"{stage_name} provider call timed out: {err_msg}",
            detail=detail,
        )
    else:
        raise ProviderException(
            message=f"{stage_name} provider failed: {err_msg}",
            error_code=error_code,
            detail=detail,
        )


class ProfileCompilerService:
    """P1 Profile Compiler Service."""

    def __init__(self, reasoning_provider: ReasoningProvider, model: str = "mock-model"):
        self.provider = reasoning_provider
        self.model = model

    async def compile_profile(
        self,
        sales_profile: SalesProfile,
        company: CompanyEntity,
        meeting_context: MeetingContext | None = None
    ) -> CompiledProfile:
        # Construct message payload
        user_message = {
            "sales_profile": sales_profile.model_dump(),
            "company": company.model_dump(),
            "meeting_context": meeting_context.model_dump() if meeting_context else None
        }

        result = await self.provider.generate_structured(
            task="p1_profile_compilation",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_P1},
                {"role": "user", "content": str(user_message)}
            ],
            response_schema=CompiledProfile.model_json_schema(),
            model=self.model,
        )

        if result.success and result.structured_data:
            data = result.structured_data
            data["version"] = PROMPT_VERSION_P1
            try:
                return CompiledProfile(**data)
            except ValidationError as exc:
                raise ProviderException(
                    message="P1 profile compiler provider returned invalid structured data",
                    error_code="PROVIDER_INVALID_JSON",
                ) from exc

        if not result.success:
            raise_provider_exception(result, "P1 profile compiler")

        raise ProviderException(
            message="P1 profile compiler provider returned no structured data",
            error_code=result.error_code or "STRUCTURED_OUTPUT_MISSING",
            detail={"error": result.error},
        )


class RetrievalPlannerService:
    """P2 Retrieval Planner Service."""

    def __init__(self, reasoning_provider: ReasoningProvider, model: str = "mock-model"):
        self.provider = reasoning_provider
        self.model = model

    async def plan_retrieval(self, profile: CompiledProfile) -> RetrievalPlan:
        result = await self.provider.generate_structured(
            task="p2_retrieval_planning",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_P2},
                {"role": "user", "content": profile.model_dump_json()}
            ],
            response_schema=RetrievalPlan.model_json_schema(),
            model=self.model,
        )

        if result.success and result.structured_data:
            data = result.structured_data
            data["version"] = PROMPT_VERSION_P2
            # Ensure queries pass privacy filter
            safe_queries = []
            for q in data.get("search_queries", []):
                query_str = q.get("query", "")
                try:
                    SearchPrivacyFilter.validate_query(query_str)
                    safe_queries.append(q)
                except Exception:
                    continue
            data["search_queries"] = safe_queries
            try:
                return RetrievalPlan(**data)
            except ValidationError as exc:
                raise ProviderException(
                    message="P2 retrieval planner provider returned invalid structured data",
                    error_code="PROVIDER_INVALID_JSON",
                ) from exc

        if not result.success:
            raise_provider_exception(result, "P2 retrieval planner")

        raise ProviderException(
            message="P2 retrieval planner provider returned no structured data",
            error_code=result.error_code or "STRUCTURED_OUTPUT_MISSING",
            detail={"error": result.error},
        )


class DemandReasonerService:
    """P3 Demand Reasoner Service with strict FACT verification boundary."""

    def __init__(self, reasoning_provider: ReasoningProvider, model: str = "mock-model"):
        self.provider = reasoning_provider
        self.model = model

    async def reason_demand(self, p3_input: P3Input) -> DemandReasonerOutput:
        # P3 Validation Boundary: Only CONFIRMED FACTS (status == 'FACT_CONFIRMED') can be used as FACTs
        fact_payloads = [
            fact
            for fact in p3_input.get_confirmed_fact_payloads()
            if fact.evidence_id in {
                evidence.evidence_id
                for evidence in p3_input.get_confirmed_evidences()
            }
        ]

        if not fact_payloads:
            # Fallback path: Insufficient confirmed evidence available
            return DemandReasonerOutput(
                version=PROMPT_VERSION_P3,
                status="INSUFFICIENT_EVIDENCE",
                drafts=[],
                reasoning_summary="Confirmed FACT evidence is missing or unverified. Cannot generate demand hypotheses.",
            )

        confirmed_ids = {f.evidence_id for f in fact_payloads}

        user_payload = {
            "compiled_profile": p3_input.compiled_profile.model_dump(),
            "confirmed_fact_payloads": [
                {
                    **fact.model_dump(),
                    "supporting_excerpt": format_external_fact_excerpt(
                        fact.evidence_id,
                        fact.supporting_excerpt,
                    ),
                }
                for fact in fact_payloads
            ],
        }

        result = await self.provider.generate_structured(
            task="p3_demand_reasoning",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_P3},
                {"role": "user", "content": str(user_payload)}
            ],
            response_schema=DemandReasonerOutput.model_json_schema(),
            model=self.model,
        )

        if result.success and result.structured_data:
            data = result.structured_data
            data["version"] = PROMPT_VERSION_P3
            try:
                output = DemandReasonerOutput(**data)
            except ValidationError as exc:
                raise ProviderException(
                    message="P3 demand reasoner provider returned invalid structured data",
                    error_code="PROVIDER_INVALID_JSON",
                ) from exc

            # P3 출력 내 인용 검증 경계: supporting 및 contradicting evidence ID가 확정 FACT에 존재하는지 검증한다.
            # PRD 11절 원문 정책(존재하지 않는 evidence_id: 해당 문장·가설 폐기 후 재평가) 대비,
            # 현재 파이프라인은 LLM 자동 재평가 미구현 상태이므로 INSUFFICIENT_EVIDENCE로 오분류하지 않고
            # fail-closed 처리로 CitationIntegrityException(INVALID_CITATION)을 발생시켜 즉시 차단한다.
            for draft in output.drafts:
                cited_ids = set(draft.supporting_evidence) | set(draft.contradicting_evidence)
                unconfirmed_citations = cited_ids - confirmed_ids
                if unconfirmed_citations:
                    sorted_unconfirmed = sorted(unconfirmed_citations)
                    raise CitationIntegrityException(
                        message=f"P3 draft referenced unconfirmed or invalid evidence_id: {sorted_unconfirmed}",
                        detail={"unconfirmed_citations": sorted_unconfirmed},
                    )
            return output

        if not result.success:
            raise_provider_exception(result, "P3 demand reasoner")

        raise ProviderException(
            message="P3 demand reasoner provider returned no structured hypotheses",
            error_code=result.error_code or "STRUCTURED_OUTPUT_MISSING",
            detail={"error": result.error},
        )
