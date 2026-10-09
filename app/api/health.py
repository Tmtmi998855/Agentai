from fastapi import APIRouter
from app.core.config import settings

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health_check():
    """Liveness probe returning application status."""
    return {
        "status": "ok",
        "app_env": settings.APP_ENV,
        "app_name": settings.APP_NAME,
    }


@router.get("/ready")
async def readiness_check():
    """Readiness probe indicating if the service is initialized."""
    return {
        "status": "ready",
        "provider": settings.REASONING_PROVIDER,
        "app_env": settings.APP_ENV,
    }
