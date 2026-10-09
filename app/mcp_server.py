"""Ah!There MCP 서버 — Hermes Agent가 stdio로 붙어서 쓰는 도구 모음.

실행:  python -m app.mcp_server
필요 패키지:  pip install -e ".[agent]"   (MCP Python SDK 2.x)
"""

from typing import Any

from mcp.server.mcpserver import MCPServer

from app.core.exceptions import AhThereException
from app.services import agent_tools
from app.services.report_store import get_report_store

server = MCPServer(
    name="ah-there",
    instructions=(
        "B2B 영업사원용 미팅 브리핑 도구. 사용자가 기업명을 보내면 create_meeting_briefing을 호출하고 "
        "결과의 messenger_text를 수정 없이 그대로 답장한다. 프로필이 없다는 오류가 오면 "
        "list_sales_templates로 선택지를 보여주고 save_sales_profile로 저장한다."
    ),
)
_store = get_report_store()


def _error(exc: AhThereException) -> dict[str, Any]:
    return {"error_code": exc.error_code, "message": exc.message}


@server.tool()
def list_sales_templates() -> dict[str, Any]:
    """온보딩용 영업 템플릿(카테고리 → 품목 → 소구점) 목록을 반환한다."""
    return agent_tools.list_sales_templates()


@server.tool()
async def save_sales_profile(
    messenger_type: str,
    messenger_user_id: str,
    category_id: str,
    product_id: str,
    value_prop_ids: list[str],
) -> dict[str, Any]:
    """영업사원의 템플릿 선택(카테고리 1개, 품목 1개, 소구점 1~3개)을 저장한다."""
    try:
        return await agent_tools.save_sales_profile(
            _store, messenger_type, messenger_user_id, category_id, product_id, value_prop_ids
        )
    except AhThereException as exc:
        return _error(exc)


@server.tool()
async def create_meeting_briefing(
    messenger_type: str,
    messenger_user_id: str,
    company_name: str,
    target_industry: str | None = None,
) -> dict[str, Any]:
    """기업명으로 현장 브리핑과 미팅 질문 3선을 만들고 웹 리포트 링크를 반환한다."""
    try:
        return await agent_tools.create_meeting_briefing(
            _store, messenger_type, messenger_user_id, company_name, target_industry
        )
    except AhThereException as exc:
        return _error(exc)


if __name__ == "__main__":
    server.run("stdio")
