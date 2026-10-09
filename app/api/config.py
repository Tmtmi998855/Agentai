from fastapi import APIRouter
from app.core.config import settings

router = APIRouter(prefix="/v1/config", tags=["Config"])


@router.get("/providers")
async def get_providers_config():
    """
    Returns public provider configuration details.
    API keys and secrets are strictly excluded.
    """
    return settings.get_public_provider_config()
