import asyncio
import time
from typing import Any
from app.domain.models import ProviderResult
from app.providers.base import ReasoningProvider


class MockReasoningProvider(ReasoningProvider):
    """Mock implementation of ReasoningProvider for testing without external API calls."""

    def __init__(
        self,
        default_response: dict[str, Any] | None = None,
        simulate_timeout: bool = False,
        simulate_error: bool = False,
        error_message: str = "Mock provider failure",
        error_code: str = "PROVIDER_ERROR",
    ):
        self._custom_response = default_response is not None
        self.default_response = default_response or {
            "company": {
                "name": "테스트기업",
                "resolved_name": "테스트기업 주식회사",
                "entity_confidence": "HIGH",
                "website": "https://testcompany.example.com",
                "industry": "IT 솔루션",
                "region": "서울"
            },
            "company_snapshot": {
                "summary": "테스트기업은 IT 솔루션 전문 기업으로 신규 사업장을 확장 중입니다.",
                "evidence_ids": ["E01"]
            },
            "small_talk": [
                {
                    "topic": "신규 사업장 개설 축하",
                    "talking_point": "최근 강남 신규 사옥 이전을 축하드립니다.",
                    "evidence_ids": ["E01"]
                }
            ],
            "demand_hypotheses": [
                {
                    "title": "업무용 차량 및 설비 증설 수요",
                    "reason": "신규 사업장 이전에 따른 이동 업무용 차량 도입 검토 가능성",
                    "reasoning_chain": [
                        "신규 사옥 확전 발표 (E01)",
                        "운영 인력 및 영업인력 증원 (E02)",
                        "업무용 신규 차량 도입 가설"
                    ],
                    "supporting_evidence": ["E01", "E02"],
                    "contradicting_evidence": [],
                    "questions": [
                        "신규 사옥 이전 이후 직원분들의 외근이나 업무 이동 수단 배정은 어떻게 진행하고 계신가요?"
                    ],
                    "status": "ACTIVE"
                }
            ],
            "sources": [
                {
                    "evidence_id": "E01",
                    "claim": "테스트기업, 서울 강남 신사옥 이전 및 사업장 확장 공시",
                    "published_at": "2026-09-01",
                    "publisher": "금융감독원 전자공시",
                    "url": "https://dart.fss.or.kr/example/001",
                    "source_tier": "A",
                    "retrieved_at": "2026-09-22T00:00:00Z",
                    "relevance_tags": ["사옥 이전", "사업장 확장"]
                },
                {
                    "evidence_id": "E02",
                    "claim": "테스트기업, 하반기 영업/기획 채용 공고 진행 중",
                    "published_at": "2026-09-10",
                    "publisher": "사람인",
                    "url": "https://saramin.co.kr/example/002",
                    "source_tier": "B",
                    "retrieved_at": "2026-09-22T00:00:00Z",
                    "relevance_tags": ["채용", "조직 확대"]
                }
            ],
            "warnings": []
        }
        self.simulate_timeout = simulate_timeout
        self.simulate_error = simulate_error
        self.error_message = error_message
        self.error_code = error_code

    async def generate_structured(
        self,
        *,
        task: str,
        messages: list[dict[str, Any]],
        response_schema: dict[str, Any],
        model: str = "mock-model",
        timeout_s: int = 30,
    ) -> ProviderResult:
        start_time = time.perf_counter()

        if self.simulate_timeout:
            await asyncio.sleep(timeout_s + 0.1)
            elapsed = (time.perf_counter() - start_time) * 1000
            return ProviderResult(
                provider="mock",
                requested_model=model,
                actual_model="mock-model",
                success=False,
                error=f"Provider call timed out after {timeout_s} seconds",
                error_code="PROVIDER_TIMEOUT",
                latency_ms=elapsed,
            )

        if self.simulate_error:
            elapsed = (time.perf_counter() - start_time) * 1000
            return ProviderResult(
                provider="mock",
                requested_model=model,
                actual_model="mock-model",
                success=False,
                error=self.error_message,
                error_code=self.error_code,
                latency_ms=elapsed,
            )

        elapsed = (time.perf_counter() - start_time) * 1000

        # Task-specific structured mock responses matching contract schemas
        resp_data = self.default_response
        if task == "p1_profile_compilation":
            resp_data = {
                "version": "1.0.0",
                "company_name": "테스트기업",
                "resolved_name": "테스트기업 주식회사",
                "industry": "IT 솔루션",
                "product_service": "기업용 차량 관리 SaaS",
                "target_customer": "중견/대기업",
                "sales_goal": "차량 관리 솔루션 수주",
                "focus_topics": ["사옥 이전", "시설 투자", "채용"],
                "compiled_at": "2026-09-22T00:00:00Z"
            }
        elif task == "p2_retrieval_planning":
            resp_data = {
                "version": "1.0.0",
                "company_name": "테스트기업",
                "approved_topics": ["사옥 이전", "시설 투자"],
                "search_queries": [
                    {"query": "테스트기업 사옥 이전 공시", "max_results": 5},
                    {"query": "테스트기업 시설 투자 공시", "max_results": 5}
                ],
                "planned_at": "2026-09-22T00:00:00Z"
            }
        elif task == "p3_demand_reasoning" and self.default_response == self._get_initial_default_briefing():
            resp_data = {
                "version": "1.0.0",
                "status": "SUCCESS",
                "drafts": [
                    {
                        "title": "업무용 차량 및 설비 증설 수요",
                        "reason": "신규 사업장 이전에 따른 이동 업무용 차량 도입 검토 가능성",
                        "reasoning_chain": [
                            "신규 사옥 확장 발표 (E01)",
                            "영업인력 증원 (E02)",
                            "업무용 신규 차량 도입 가설"
                        ],
                        "supporting_evidence": ["E01", "E02"],
                        "contradicting_evidence": [],
                        "questions": [
                            "신규 사옥 이전 이후 직원분들의 외근이나 업무 이동 수단 배정은 어떻게 진행하고 계신가요?"
                        ],
                        "status": "ACTIVE"
                    }
                ],
                "reasoning_summary": "확정 FACT 증거 2건에 기초하여 수요 가설 도출",
                "evaluated_at": "2026-09-22T00:00:00Z"
            }

        if task == "p3_demand_reasoning" and not self._custom_response:
            resp_data = {
                "version": "1.0.0",
                "status": "INSUFFICIENT_EVIDENCE",
                "drafts": [],
                "reasoning_summary": "확정된 FACT가 없어 오프라인 Mock에서 추론을 중단했습니다.",
                "evaluated_at": "2026-09-22T00:00:00Z",
            }

        return ProviderResult(
            provider="mock",
            requested_model=model,
            actual_model="mock-model",
            structured_data=resp_data,
            content=str(resp_data),
            input_tokens=150,
            output_tokens=350,
            latency_ms=elapsed,
            cost_usd=0.0,
            raw_response={"mock": True},
            success=True,
            error=None,
        )

    def _get_initial_default_briefing(self) -> dict[str, Any]:
        return {
            "company": {
                "name": "테스트기업",
                "resolved_name": "테스트기업 주식회사",
                "entity_confidence": "HIGH",
                "website": "https://testcompany.example.com",
                "industry": "IT 솔루션",
                "region": "서울"
            },
            "company_snapshot": {
                "summary": "테스트기업은 IT 솔루션 전문 기업으로 신규 사업장을 확장 중입니다.",
                "evidence_ids": ["E01"]
            },
            "small_talk": [
                {
                    "topic": "신규 사업장 개설 축하",
                    "talking_point": "최근 강남 신규 사옥 이전을 축하드립니다.",
                    "evidence_ids": ["E01"]
                }
            ],
            "demand_hypotheses": [
                {
                    "title": "업무용 차량 및 설비 증설 수요",
                    "reason": "신규 사업장 이전에 따른 이동 업무용 차량 도입 검토 가능성",
                    "reasoning_chain": [
                        "신규 사옥 확장 발표 (E01)",
                        "영업인력 증원 (E02)",
                        "업무용 신규 차량 도입 가설"
                    ],
                    "supporting_evidence": ["E01", "E02"],
                    "contradicting_evidence": [],
                    "questions": [
                        "신규 사옥 이전 이후 직원분들의 외근이나 업무 이동 수단 배정은 어떻게 진행하고 계신가요?"
                    ],
                    "status": "ACTIVE"
                }
            ],
            "sources": [
                {
                    "evidence_id": "E01",
                    "claim": "테스트기업, 서울 강남 신사옥 이전 및 사업장 확장 공시",
                    "published_at": "2026-09-01",
                    "publisher": "금융감독원 전자공시",
                    "url": "https://dart.fss.or.kr/example/001",
                    "source_tier": "A",
                    "retrieved_at": "2026-09-22T00:00:00Z",
                    "relevance_tags": ["사옥 이전", "사업장 확장"]
                },
                {
                    "evidence_id": "E02",
                    "claim": "테스트기업, 하반기 영업/기획 채용 공고 진행 중",
                    "published_at": "2026-09-10",
                    "publisher": "사람인",
                    "url": "https://saramin.co.kr/example/002",
                    "source_tier": "B",
                    "retrieved_at": "2026-09-22T00:00:00Z",
                    "relevance_tags": ["채용", "조직 확대"]
                }
            ],
            "warnings": []
        }
