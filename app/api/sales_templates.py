from fastapi import APIRouter

from app.services.agent_tools import list_sales_templates

router = APIRouter(prefix="/v1", tags=["sales-templates"])


@router.get("/sales-templates")
async def get_sales_templates() -> dict:
    """온보딩 3단계 템플릿 (카테고리 → 품목 → 소구점)."""
    return list_sales_templates()
