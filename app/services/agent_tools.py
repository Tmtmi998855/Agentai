"""Hermes Agent(메신저 허브)가 MCP로 호출하는 도구의 실제 구현.

MCP 서버(app/mcp_server.py)는 이 함수들을 감싸기만 한다. 테스트는 MCP 없이 이 모듈을 직접 호출한다.
"""

from typing import Any

from pydantic import ValidationError

from app.core.config import settings
from app.core.exceptions import AhThereException
from app.domain.job_models import BriefingCreateRequest
from app.domain.sales_templates import SalesTemplateSelection, load_sales_template_catalog
from app.services.messenger_formatter import format_messenger_briefing
from app.services.orchestrator import BriefingOrchestrator, create_orchestrator
from app.services.report_store import MessengerType, ReportStore, build_report_row


class AgentToolError(AhThereException):
    def __init__(self, message: str, error_code: str):
        super().__init__(message, error_code=error_code, detail={})


def list_sales_templates() -> dict[str, Any]:
    """온보딩 3단계(카테고리 → 품목 → 소구점) 선택지를 반환한다."""
    return load_sales_template_catalog().model_dump()


async def save_sales_profile(
    store: ReportStore,
    messenger_type: MessengerType,
    messenger_user_id: str,
    category_id: str,
    product_id: str,
    value_prop_ids: list[str],
) -> dict[str, Any]:
    try:
        selection = SalesTemplateSelection(
            category_id=category_id, product_id=product_id, value_prop_ids=value_prop_ids
        )
    except ValidationError as exc:
        # 어떤 값이 틀렸는지는 카탈로그 기준이므로 안내 가능하지만, 원문 입력은 되돌려주지 않는다.
        raise AgentToolError("템플릿 선택값이 올바르지 않습니다. list_sales_templates 결과의 ID를 사용하세요.",
                             "INVALID_TEMPLATE_SELECTION") from exc
    record = await store.upsert_user_profile(messenger_type, messenger_user_id, selection)
    resolved = selection.resolve()
    return {
        "user_id": record.id,
        "profile": {
            "category": resolved.category_label,
            "product": resolved.product_label,
            "value_props": [v.label for v in resolved.value_props],
        },
    }


async def create_meeting_briefing(
    store: ReportStore,
    messenger_type: MessengerType,
    messenger_user_id: str,
    company_name: str,
    target_industry: str | None = None,
    orchestrator: BriefingOrchestrator | None = None,
    report_base_url: str | None = None,
    company_website: str | None = None,
) -> dict[str, Any]:
    """기업명 하나로 듀얼 리서치 → 질문 3선 → 리포트 저장 → 메신저 답장 텍스트까지 만든다."""
    user = await store.get_user_profile(messenger_type, messenger_user_id)
    if user is None:
        raise AgentToolError("영업 프로필이 없습니다. 먼저 온보딩(save_sales_profile)을 진행하세요.",
                             "PROFILE_NOT_FOUND")
    try:
        request = BriefingCreateRequest.from_template(
            company_name, user.template, target_industry, company_website=company_website
        )
    except ValidationError as exc:
        raise AgentToolError("기업명·산업명·홈페이지 입력값을 확인하세요.", "VALIDATION_ERROR") from exc

    briefing = await (orchestrator or create_orchestrator()).execute_pipeline(request)

    report_url = None
    report_id = None
    if briefing.status != "ENTITY_AMBIGUOUS":
        saved = await store.save_report(build_report_row(user.id, briefing))
        report_id = saved.id
        report_url = f"{(report_base_url or settings.REPORT_BASE_URL).rstrip('/')}/{saved.id}"

    return {
        "status": briefing.status,
        "report_id": report_id,
        "report_url": report_url,
        "messenger_text": format_messenger_briefing(briefing, report_url),
    }
