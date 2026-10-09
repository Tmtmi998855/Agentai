"""MCP 서버 보안 경계: 사용자 ID는 서버 설정으로만 정해진다."""

import pytest

pytest.importorskip("mcp")

import app.mcp_server as mcp_server  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.services.report_store import MemoryReportStore  # noqa: E402


@pytest.fixture
def fresh_store(monkeypatch):
    store = MemoryReportStore()
    monkeypatch.setattr(mcp_server, "_store", store)
    return store


async def test_tools_do_not_accept_user_identity():
    tools = {t.name: t for t in await mcp_server.server.list_tools()}
    assert set(tools) == {"list_sales_templates", "save_sales_profile", "create_meeting_briefing"}
    for tool in tools.values():
        props = set(tool.input_schema.get("properties", {}))
        assert not props & {"messenger_user_id", "messenger_type", "user_id"}


async def test_missing_owner_fails_closed(monkeypatch, fresh_store):
    monkeypatch.setattr(settings, "AH_THERE_OWNER_USER_ID", "")
    result = await mcp_server.server.call_tool("create_meeting_briefing", {"company_name": "삼양패키징"})
    assert result.structured_content["error_code"] == "OWNER_NOT_CONFIGURED"


async def test_owner_bound_flow(monkeypatch, fresh_store):
    monkeypatch.setattr(settings, "AH_THERE_OWNER_USER_ID", "123456789")
    saved = await mcp_server.server.call_tool(
        "save_sales_profile",
        {"category_id": "mobility", "product_id": "long_term_rental", "value_prop_ids": ["mobility_expense"]},
    )
    assert saved.structured_content["profile"]["product"] == "신차 장기렌터카"
    assert await fresh_store.get_user_profile("telegram", "123456789") is not None

    result = await mcp_server.server.call_tool(
        "create_meeting_briefing", {"company_name": "삼양패키징", "target_industry": "포장재"}
    )
    body = result.structured_content
    assert body["status"] == "SUCCESS"
    assert body["report_url"].startswith(settings.REPORT_BASE_URL.rstrip("/") + "/")
