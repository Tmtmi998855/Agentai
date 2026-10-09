"""FastAPI API router for asynchronous Briefing generation and job status queries."""

from fastapi import APIRouter, Depends, Request, status
from app.core.exceptions import AhThereException
from app.domain.job_models import (
    BriefingCreateRequest,
    BriefingJobSubmitResponse,
    BriefingJobStatusResponse,
)
from app.domain.models import BriefingObject, ErrorResponse
from app.services.briefing_jobs import BriefingJobManager

router = APIRouter(prefix="/v1", tags=["Briefings"])


def get_job_manager(request: Request) -> BriefingJobManager:
    """Dependency retrieving the app-scoped BriefingJobManager from request.app.state."""
    manager: BriefingJobManager | None = getattr(request.app.state, "job_manager", None)
    if manager is None:
        raise AhThereException(
            "Job manager is unavailable",
            error_code="JOB_MANAGER_UNAVAILABLE",
        )
    return manager


@router.post(
    "/briefings",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=BriefingJobSubmitResponse,
    responses={
        202: {"description": "비동기 브리핑 생성 작업 접수 성공"},
        422: {"model": ErrorResponse, "description": "입력값 검증 실패 (VALIDATION_ERROR)"},
        503: {"model": ErrorResponse, "description": "작업 관리자 이용 불가 또는 저장소 초과 (JOB_MANAGER_UNAVAILABLE, JOB_STORE_FULL)"},
    },
)
async def create_briefing_job(
    payload: BriefingCreateRequest,
    manager: BriefingJobManager = Depends(get_job_manager),
) -> BriefingJobSubmitResponse:
    """
    POST /v1/briefings: 비동기 브리핑 생성 작업을 접수한다.
    - 입력값: company_name, sales_profile, 선택적 meeting_context
    - 반환: 202 Accepted + job_id + status(PENDING) + status_url + result_url + provenance(MOCK_VIRTUAL)
    """
    return manager.submit_job(payload)


@router.get(
    "/briefing-jobs/{job_id}",
    status_code=status.HTTP_200_OK,
    response_model=BriefingJobStatusResponse,
    responses={
        200: {"description": "작업 상태 엔벨롭 조회 성공 (PENDING / RUNNING / COMPLETED / FAILED)"},
        404: {"model": ErrorResponse, "description": "존재하지 않는 job_id"},
        503: {"model": ErrorResponse, "description": "작업 관리자 이용 불가"},
    },
)
async def get_briefing_job_status(
    job_id: str,
    manager: BriefingJobManager = Depends(get_job_manager),
) -> BriefingJobStatusResponse:
    """
    GET /v1/briefing-jobs/{job_id}: 비동기 작업의 진행 상태를 조회한다.
    - 미등록 job_id: HTTP 404
    - 실패한 작업인 경우 HTTP 200 status 엔벨롭 내에 FAILED, error_code, error_http_status 반환.
    """
    return manager.get_job_status(job_id)


@router.get(
    "/briefings/{briefing_id}",
    status_code=status.HTTP_200_OK,
    response_model=BriefingObject,
    responses={
        200: {"description": "완료된 BriefingObject 반환 (SUCCESS / INSUFFICIENT_EVIDENCE / ENTITY_AMBIGUOUS)"},
        404: {"model": ErrorResponse, "description": "존재하지 않는 briefing_id"},
        409: {"model": ErrorResponse, "description": "작업 미완료 (PENDING / RUNNING)"},
        422: {"model": ErrorResponse, "description": "인용 무결성 실패 (INVALID_CITATION)"},
        500: {"model": ErrorResponse, "description": "내부 서버 오류 (INTERNAL_SERVER_ERROR)"},
        502: {"model": ErrorResponse, "description": "공급자 오류 (PROVIDER_AUTH_ERROR / PROVIDER_ERROR)"},
        503: {"model": ErrorResponse, "description": "작업 취소 또는 관리자 이용 불가 (JOB_CANCELLED / JOB_MANAGER_UNAVAILABLE)"},
        504: {"model": ErrorResponse, "description": "공급자 타임아웃 (PROVIDER_TIMEOUT)"},
    },
)
async def get_briefing_result(
    briefing_id: str,
    manager: BriefingJobManager = Depends(get_job_manager),
) -> BriefingObject:
    """
    GET /v1/briefings/{briefing_id}: 완료된 브리핑 결과를 조회한다.
    - 미완료(PENDING / RUNNING) 시: HTTP 409 Conflict
    - 미등록 briefing_id 시: HTTP 404 Not Found
    - 실패 결과 조회 시: 500/502/503/504/422 안전한 ErrorResponse 매핑 유지
    """
    return manager.get_briefing_result(briefing_id)
