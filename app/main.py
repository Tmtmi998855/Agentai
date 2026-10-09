from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.exceptions import AhThereException, ProviderException
from app.domain.models import ErrorResponse
from app.api.router import api_router
from app.services.briefing_jobs import BriefingJobManager


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """App-scoped lifespan creating an isolated BriefingJobManager in app.state."""
    manager = BriefingJobManager(max_capacity=100)
    app.state.job_manager = manager
    async with manager.lifespan(app):
        yield


async def ah_there_exception_handler(request: Request, exc: Exception):
    if not isinstance(exc, AhThereException):
        return await unhandled_exception_handler(request, exc)
    is_provider_error = isinstance(exc, ProviderException)
    if is_provider_error:
        message = (
            "분석 서비스 응답 시간이 초과되었습니다."
            if exc.error_code == "PROVIDER_TIMEOUT"
            else "분석 서비스를 일시적으로 이용할 수 없습니다."
        )
    else:
        message = exc.message
    error_res = ErrorResponse(
        error_code=exc.error_code,
        message=message,
        detail={} if is_provider_error else exc.detail,
    )
    status_code = 400
    if exc.error_code == "PROVIDER_TIMEOUT":
        status_code = 504
    elif is_provider_error:
        status_code = 502
    elif exc.error_code == "INVALID_CITATION":
        status_code = 422
    elif exc.error_code in ("JOB_NOT_FOUND", "BRIEFING_NOT_FOUND"):
        status_code = 404
    elif exc.error_code == "JOB_NOT_COMPLETED":
        status_code = 409
    elif exc.error_code in ("JOB_STORE_FULL", "JOB_CANCELLED", "JOB_MANAGER_UNAVAILABLE"):
        status_code = 503
    elif exc.error_code == "INTERNAL_SERVER_ERROR":
        status_code = 500
    return JSONResponse(status_code=status_code, content=error_res.model_dump())


async def validation_exception_handler(request: Request, exc: Exception):
    """요청 입력값 검증 실패 시 PII/원문입력/상세구조를 노출하지 않고 정화된 ErrorResponse(422)를 반환한다."""
    error_res = ErrorResponse(
        error_code="VALIDATION_ERROR",
        message="요청 입력값 검증에 실패했습니다.",
        detail={},
    )
    return JSONResponse(status_code=422, content=error_res.model_dump())


async def unhandled_exception_handler(request: Request, exc: Exception):
    """Fallback handler catching all unexpected internal server errors cleanly without exposing tracebacks."""
    error_res = ErrorResponse(
        error_code="INTERNAL_SERVER_ERROR",
        message="내부 처리 중 오류가 발생했습니다.",
        detail={},
    )
    return JSONResponse(status_code=500, content=error_res.model_dump())


def create_app() -> FastAPI:
    """App factory function enabling application instance isolation testing."""
    app_instance = FastAPI(
        title=settings.APP_NAME,
        description="Ah! There (아!거기) B2B Sales Briefing Service V0 Backend",
        version="0.1.0",
        debug=False,
        lifespan=lifespan,
    )
    app_instance.include_router(api_router)
    app_instance.add_exception_handler(AhThereException, ah_there_exception_handler)
    app_instance.add_exception_handler(RequestValidationError, validation_exception_handler)
    app_instance.add_exception_handler(Exception, unhandled_exception_handler)
    return app_instance


app = create_app()
