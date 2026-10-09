from fastapi import APIRouter
from app.api.health import router as health_router
from app.api.config import router as config_router
from app.api.briefings import router as briefings_router
from app.api.ui_review import router as ui_review_router
from app.api.sales_templates import router as sales_templates_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(config_router)
api_router.include_router(briefings_router)
api_router.include_router(ui_review_router)
api_router.include_router(sales_templates_router)
