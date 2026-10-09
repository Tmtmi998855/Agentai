"""Async job manager and in-memory bounded store for briefing generation jobs."""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator
import uuid
import anyio
from fastapi import FastAPI

from app.core.exceptions import (
    AhThereException,
    CitationIntegrityException,
    ProviderAuthException,
    ProviderException,
    ProviderTimeoutException,
)
from app.domain.job_models import (
    BriefingCreateRequest,
    BriefingJobStatusResponse,
    BriefingJobSubmitResponse,
    JobRecord,
    JobStatus,
)
from app.domain.models import BriefingObject, current_iso_time
from app.services.orchestrator import BriefingOrchestrator

logger = logging.getLogger(__name__)


class BriefingJobStore:
    """Bounded, thread/task-safe in-memory storage for briefing jobs."""

    def __init__(self, max_capacity: int = 100):
        self.max_capacity = max_capacity
        self._store: dict[str, JobRecord] = {}

    def add_job(self, record: JobRecord) -> None:
        if len(self._store) >= self.max_capacity:
            raise AhThereException(
                f"Job store capacity reached. Maximum allowed is {self.max_capacity}.",
                error_code="JOB_STORE_FULL",
            )
        self._store[record.job_id] = record.model_copy(deep=True)

    def get_job(self, job_id: str) -> JobRecord | None:
        record = self._store.get(job_id)
        if record:
            return record.model_copy(deep=True)
        return None

    def update_status(self, job_id: str, status: JobStatus) -> None:
        job = self._store.get(job_id)
        if job:
            job.status = status

    def set_completed(self, job_id: str, briefing: BriefingObject) -> None:
        job = self._store.get(job_id)
        if not job:
            return
        if job.status == "COMPLETED":
            raise AhThereException("Cannot overwrite an already completed job", error_code="JOB_ALREADY_COMPLETED")
        job.status = "COMPLETED"
        job.result = briefing.model_copy(deep=True)
        job.completed_at = current_iso_time()

    def set_failed(self, job_id: str, exc: BaseException) -> None:
        job = self._store.get(job_id)
        if not job:
            return
        job.status = "FAILED"
        job.completed_at = current_iso_time()

        if isinstance(exc, ProviderAuthException):
            job.error_code = "PROVIDER_AUTH_ERROR"
            job.error_http_status = 502
            job.error_message = "분석 서비스를 일시적으로 이용할 수 없습니다."
        elif isinstance(exc, ProviderTimeoutException):
            job.error_code = "PROVIDER_TIMEOUT"
            job.error_http_status = 504
            job.error_message = "분석 서비스 응답 시간이 초과되었습니다."
        elif isinstance(exc, ProviderException):
            job.error_code = exc.error_code or "PROVIDER_ERROR"
            job.error_http_status = 502
            job.error_message = "분석 서비스를 일시적으로 이용할 수 없습니다."
        elif isinstance(exc, CitationIntegrityException):
            job.error_code = "INVALID_CITATION"
            job.error_http_status = 422
            job.error_message = "인용 무결성 검증 실패"
        elif (isinstance(exc, AhThereException) and exc.error_code == "JOB_CANCELLED") or isinstance(exc, asyncio.CancelledError):
            job.error_code = "JOB_CANCELLED"
            job.error_http_status = 503
            job.error_message = "작업이 취소되었습니다."
        elif isinstance(exc, AhThereException):
            job.error_code = exc.error_code
            job.error_http_status = 400
            job.error_message = "요청 처리 중 오류가 발생했습니다."
        else:
            job.error_code = "INTERNAL_SERVER_ERROR"
            job.error_http_status = 500
            job.error_message = "내부 처리 중 오류가 발생했습니다."

    def clear(self) -> None:
        self._store.clear()


class BriefingJobManager:
    """Lifespan task manager executing async briefing generation jobs in background TaskGroup."""

    def __init__(self, max_capacity: int = 100):
        self.store = BriefingJobStore(max_capacity=max_capacity)
        self.task_group: anyio.abc.TaskGroup | None = None
        self._orchestrator: BriefingOrchestrator | None = None

    @asynccontextmanager
    async def lifespan(self, app: FastAPI) -> AsyncGenerator[None, None]:
        self.store.clear()
        async with anyio.create_task_group() as tg:
            self.task_group = tg
            try:
                yield
            finally:
                tg.cancel_scope.cancel()
                self.task_group = None

    def set_orchestrator(self, orchestrator: BriefingOrchestrator | None) -> None:
        self._orchestrator = orchestrator

    def submit_job(self, request_data: BriefingCreateRequest) -> BriefingJobSubmitResponse:
        if self.task_group is None:
            raise AhThereException(
                "Job manager lifespan is not active",
                error_code="JOB_MANAGER_UNAVAILABLE",
            )

        job_id = str(uuid.uuid4())
        record = JobRecord(
            job_id=job_id,
            briefing_id=job_id,
            status="PENDING",
            request_data=request_data,
        )
        self.store.add_job(record)
        self.task_group.start_soon(self._run_job_wrapper, job_id)

        return BriefingJobSubmitResponse(
            job_id=job_id,
            status="PENDING",
            status_url=f"/v1/briefing-jobs/{job_id}",
            result_url=f"/v1/briefings/{job_id}",
            provenance="MOCK_VIRTUAL",
        )

    async def _run_job_wrapper(self, job_id: str) -> None:
        job = self.store.get_job(job_id)
        if not job:
            return

        self.store.update_status(job_id, "RUNNING")
        orchestrator = self._orchestrator or BriefingOrchestrator()

        try:
            briefing = await orchestrator.execute_pipeline(job.request_data)
            self.store.set_completed(job_id, briefing)
        except (asyncio.CancelledError, anyio.get_cancelled_exc_class()) as exc:
            cancelled_exc = AhThereException("작업이 취소되었습니다.", error_code="JOB_CANCELLED")
            self.store.set_failed(job_id, cancelled_exc)
            logger.info("작업 취소 처리 완료: job_id=%s, exc_class=%s", job_id, exc.__class__.__name__)
            raise
        except Exception as exc:
            self.store.set_failed(job_id, exc)
            err_code = getattr(exc, "error_code", None) or "INTERNAL_SERVER_ERROR"
            logger.error(
                "작업 실행 중 예외 기록: job_id=%s, error_code=%s, exc_class=%s",
                job_id,
                err_code,
                exc.__class__.__name__,
            )

    def get_job_status(self, job_id: str) -> BriefingJobStatusResponse:
        job = self.store.get_job(job_id)
        if not job:
            raise AhThereException(f"Briefing job with ID {job_id} not found", error_code="JOB_NOT_FOUND")

        return BriefingJobStatusResponse(
            job_id=job.job_id,
            status=job.status,
            provenance=job.provenance,
            created_at=job.created_at,
            completed_at=job.completed_at,
            error_code=job.error_code,
            error_http_status=job.error_http_status,
        )

    def get_briefing_result(self, briefing_id: str) -> BriefingObject:
        job = self.store.get_job(briefing_id)
        if not job:
            raise AhThereException(f"Briefing with ID {briefing_id} not found", error_code="BRIEFING_NOT_FOUND")

        if job.status in ("PENDING", "RUNNING"):
            raise AhThereException(
                "Briefing generation job is still in progress",
                error_code="JOB_NOT_COMPLETED",
            )

        if job.status == "FAILED":
            if job.error_code == "PROVIDER_TIMEOUT":
                raise ProviderTimeoutException(message=job.error_message or "분석 서비스 응답 시간이 초과되었습니다.", detail={})
            elif job.error_code == "PROVIDER_AUTH_ERROR":
                raise ProviderAuthException(message=job.error_message or "분석 서비스를 일시적으로 이용할 수 없습니다.", detail={})
            elif job.error_code == "INVALID_CITATION":
                raise CitationIntegrityException(message=job.error_message or "인용 무결성 검증 실패", detail={})
            elif job.error_http_status == 502 or (job.error_code and job.error_code.startswith("PROVIDER_")):
                raise ProviderException(
                    message=job.error_message or "분석 서비스를 일시적으로 이용할 수 없습니다.",
                    error_code=job.error_code or "PROVIDER_ERROR",
                    detail={},
                )
            elif job.error_code == "JOB_CANCELLED":
                raise AhThereException(message=job.error_message or "작업이 취소되었습니다.", error_code="JOB_CANCELLED", detail={})
            else:
                raise AhThereException(
                    message=job.error_message or "내부 처리 중 오류가 발생했습니다.",
                    error_code=job.error_code or "INTERNAL_SERVER_ERROR",
                    detail={},
                )

        if job.result is None:
            raise AhThereException("Briefing result data is missing", error_code="RESULT_MISSING")

        return job.result.model_copy(deep=True)
