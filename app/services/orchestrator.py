"""Briefing Pipeline Orchestrator connecting offline P1 -> P2 -> Search -> WebRawFetcher -> P3 -> Rule Engine -> P4."""

from typing import Callable, Any
from urllib.parse import urlparse
import anyio
from app.core.exceptions import ProviderException
from app.domain.job_models import BriefingCreateRequest
from app.domain.models import BriefingObject, CompanyEntity, ProviderResult
from app.domain.pipeline_models import Evidence, P3Input
from app.domain.search_models import RawSearchItem, SearchQuery, SearchRequest
from app.providers.base import ReasoningProvider
from app.providers.search_base import SearchProvider
from app.providers.mock_search import MockSearchProvider
from app.services.briefing_composer import BriefingComposerService
from app.services.evidence_builder import EvidenceBuilder
from app.services.web_raw_fetcher import WebRawFetcher
from app.services.pipeline_services import (
    ProfileCompilerService,
    RetrievalPlannerService,
    DemandReasonerService,
)
from app.services.rule_engine import HypothesisScorer
from app.services.mock_fixtures import (
    MOCK_VIRTUAL_OFFICIAL_DOMAINS,
    build_mock_company_entity,
    build_mock_p1_data,
    build_mock_p2_data,
    build_mock_search_items,
    build_mock_virtual_html,
    build_mock_p3_data,
    build_mock_p4_payload,
)


class OrchestratorMockProvider(ReasoningProvider):
    """Dynamic Mock reasoning provider that builds responses matching user input and confirmed evidences."""

    def __init__(self, request_data: BriefingCreateRequest):
        self.request_data = request_data
        self._scored_hypotheses: list[dict[str, Any]] = []
        self._confirmed_evidences: list[Evidence] = []

    def set_scored_hypotheses(self, scored_hypotheses: list[dict[str, Any]]) -> None:
        self._scored_hypotheses = scored_hypotheses

    def set_confirmed_evidences(self, confirmed_evidences: list[Evidence]) -> None:
        self._confirmed_evidences = confirmed_evidences

    async def generate_structured(
        self,
        *,
        task: str,
        messages: list[dict[str, Any]],
        response_schema: dict[str, Any],
        model: str = "mock-model",
        timeout_s: int = 30,
    ) -> ProviderResult:
        cp = self.request_data.company_name
        sp = self.request_data.sales_profile

        if task == "p1_profile_compilation":
            resp_data = build_mock_p1_data(self.request_data)
        elif task == "p2_retrieval_planning":
            resp_data = build_mock_p2_data(cp)
        elif task == "p3_demand_reasoning":
            resp_data = build_mock_p3_data(cp, sp.product_service, self._confirmed_evidences)
        elif task == "p4_briefing_composition":
            resp_data = build_mock_p4_payload(
                cp, sp.product_service, self._scored_hypotheses, self._confirmed_evidences
            )
        else:
            resp_data = {}

        return ProviderResult(
            provider="mock",
            requested_model=model,
            actual_model="mock-model",
            structured_data=resp_data,
            content=str(resp_data),
            success=True,
        )


class BriefingOrchestrator:
    """Orchestrates the multi-stage briefing pipeline."""

    def __init__(
        self,
        p1_provider: ReasoningProvider | None = None,
        p2_provider: ReasoningProvider | None = None,
        p3_provider: ReasoningProvider | None = None,
        p4_provider: ReasoningProvider | None = None,
        search_provider: SearchProvider | None = None,
        entity_resolver: Callable[[str, str], CompanyEntity] | None = None,
        search_func: Callable[[str, list[SearchQuery]], list[RawSearchItem]] | None = None,
        raw_html_func: Callable[[str, str], tuple[str, str] | None] | None = None,
        step_gate_event: anyio.Event | None = None,
    ):
        self.p1_provider = p1_provider
        self.p2_provider = p2_provider
        self.p3_provider = p3_provider
        self.p4_provider = p4_provider
        self.search_provider = search_provider
        self.entity_resolver = entity_resolver or (
            lambda name, ind: build_mock_company_entity(name, ind)
        )
        self.search_func = search_func
        self.raw_html_func = raw_html_func or (lambda name, identifier: build_mock_virtual_html(name, identifier))
        self.step_gate_event = step_gate_event

    async def execute_pipeline(self, request_data: BriefingCreateRequest) -> BriefingObject:
        cp = request_data.company_name
        sp = request_data.sales_profile
        mc = request_data.meeting_context

        default_provider = OrchestratorMockProvider(request_data)
        p1_prov = self.p1_provider or default_provider
        p2_prov = self.p2_provider or default_provider
        p3_prov = self.p3_provider or default_provider
        p4_prov = self.p4_provider or default_provider

        # Step 0: Entity Resolution
        company = self.entity_resolver(cp, sp.industry)
        if company.entity_confidence in ("LOW", "MEDIUM"):
            # Halt early without calling P1, Search, P3, or P4
            composer = BriefingComposerService(p4_prov)
            briefing = composer._entity_ambiguous_briefing(company)
            mock_warning = "MOCK_VIRTUAL: 오프라인 가상 파이프라인에서 생성된 결과입니다."
            if mock_warning not in briefing.warnings:
                briefing.warnings.append(mock_warning)
            return briefing

        # Step 1: P1 Profile Compiler
        p1_service = ProfileCompilerService(p1_prov)
        compiled_profile = await p1_service.compile_profile(sp, company, mc)

        # Optional test gate pause to observe RUNNING status deterministically
        if self.step_gate_event is not None:
            await self.step_gate_event.wait()

        # Step 2: P2 Retrieval Planner
        p2_service = RetrievalPlannerService(p2_prov)
        retrieval_plan = await p2_service.plan_retrieval(compiled_profile)

        # Step 3: Mock Search using MockSearchProvider (or custom search_func if overridden)
        if self.search_func is not None:
            raw_items = self.search_func(cp, retrieval_plan.search_queries)
        else:
            provider = self.search_provider or MockSearchProvider(
                default_items=build_mock_search_items(cp)
            )
            search_req = SearchRequest(company_name=cp, queries=retrieval_plan.search_queries)
            search_res = await provider.search(search_req)
            if not search_res.success:
                raise ProviderException(
                    "Search provider execution failed",
                    error_code="PROVIDER_SEARCH_ERROR",
                )
            raw_items = search_res.items

        # Step 4: EvidenceBuilder
        evidence_pack = EvidenceBuilder.build_evidences(
            cp, raw_items, confirmed_official_domains=MOCK_VIRTUAL_OFFICIAL_DOMAINS
        )

        # Step 5: WebRawFetcher & Fact Verification Seam
        web_fetcher = WebRawFetcher(allow_live_fetch=False)
        for evidence in evidence_pack.evidences:
            # Find matching HTML fixture by stable URL identity (or raw_url)
            html_tuple = self.raw_html_func(cp, evidence.url) or self.raw_html_func(cp, evidence.raw_url or "")
            if html_tuple:
                html_content, claim_excerpt = html_tuple
                await web_fetcher.fetch_and_verify_evidence(evidence, custom_raw_html=html_content)
                if evidence.claim == claim_excerpt:
                    evidence.confirm_fact(
                        target_claim=claim_excerpt,
                        supporting_excerpt=claim_excerpt,
                        verification_method="EXACT_EXCERPT_MATCH",
                    )

        confirmed_evidences = [e for e in evidence_pack.evidences if e.is_confirmed_fact]
        if isinstance(default_provider, OrchestratorMockProvider):
            default_provider.set_confirmed_evidences(confirmed_evidences)

        # Step 6: P3 Demand Reasoner
        p3_input = P3Input(compiled_profile=compiled_profile, evidence_pack=evidence_pack)
        p3_service = DemandReasonerService(p3_prov)
        p3_output = await p3_service.reason_demand(p3_input)

        # Step 7: Rule Engine (Scorer)
        if p3_output.status == "SUCCESS" and p3_output.drafts:
            scorer = HypothesisScorer()
            scored_hypotheses = [
                scorer.score_hypothesis(draft, evidence_pack)
                for draft in p3_output.drafts
            ]
        else:
            scored_hypotheses = []

        if isinstance(default_provider, OrchestratorMockProvider):
            default_provider.set_scored_hypotheses([h.model_dump() for h in scored_hypotheses])

        # Step 8: P4 Briefing Composer
        p4_service = BriefingComposerService(p4_prov)
        briefing = await p4_service.compose_briefing(
            company=company,
            evidence_pack=evidence_pack,
            scored_hypotheses=scored_hypotheses,
            compiled_profile=compiled_profile,
        )

        # Guarantee Mock disclaimer in warnings
        mock_warning = "MOCK_VIRTUAL: 오프라인 가상 파이프라인에서 생성된 결과입니다."
        if mock_warning not in briefing.warnings:
            briefing.warnings.append(mock_warning)

        return briefing
