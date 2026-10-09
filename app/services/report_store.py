"""유저 영업 프로필과 브리핑 리포트 저장소.

- MemoryReportStore: 로컬/테스트용
- SupabaseReportStore: Supabase PostgREST(/rest/v1) 직접 호출. service_role 키는 서버에서만 사용한다.
스키마는 db/supabase/migrations/001_init.sql 참고.
"""

import uuid
from typing import Any, Literal, Protocol

import httpx
from pydantic import Field, SecretStr

from app.core.exceptions import AhThereException
from app.domain.models import BriefingObject, StrictBaseModel, current_iso_time
from app.domain.sales_templates import SalesTemplateSelection, load_sales_template_catalog

MessengerType = Literal["telegram", "kakao", "imessage", "web"]


class ReportStoreException(AhThereException):
    def __init__(self, message: str = "Report store operation failed", error_code: str = "REPORT_STORE_ERROR"):
        super().__init__(message, error_code=error_code, detail={})


class UserProfileRecord(StrictBaseModel):
    id: str
    messenger_type: MessengerType
    messenger_user_id: str = Field(..., min_length=1, max_length=100)
    template: SalesTemplateSelection
    template_version: str


class ReportRecord(StrictBaseModel):
    id: str
    user_id: str
    target_company: str
    status: str
    company_summary: str
    industry_summary: str
    questions: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    briefing: dict[str, Any]
    created_at: str = Field(default_factory=current_iso_time)


def build_report_row(user_id: str, briefing: BriefingObject) -> dict[str, Any]:
    """BriefingObject를 reports 테이블 행으로 변환한다. 고객용 확정 출처만 저장한다."""
    industry_claims = [s.claim for s in briefing.sources if s.scope == "INDUSTRY"]
    questions = (
        [q.model_dump() for q in briefing.strategic_questions.questions]
        if briefing.strategic_questions
        else [{"type": "LEGACY", "question": q} for q in briefing.meeting_questions]
    )
    return {
        "user_id": user_id,
        "target_company": briefing.company.name,
        "status": briefing.status,
        "company_summary": briefing.company_snapshot.summary,
        "industry_summary": "\n".join(industry_claims) or "확인된 산업 동향 근거가 없습니다.",
        "questions": questions,
        "sources": [s.model_dump() for s in briefing.sources],
        "briefing": briefing.model_dump(mode="json"),
    }


class ReportStore(Protocol):
    async def upsert_user_profile(
        self, messenger_type: MessengerType, messenger_user_id: str, template: SalesTemplateSelection
    ) -> UserProfileRecord: ...

    async def get_user_profile(self, messenger_type: MessengerType, messenger_user_id: str) -> UserProfileRecord | None: ...

    async def save_report(self, row: dict[str, Any]) -> ReportRecord: ...

    async def get_report(self, report_id: str) -> ReportRecord | None: ...


class MemoryReportStore:
    def __init__(self) -> None:
        self._users: dict[tuple[str, str], UserProfileRecord] = {}
        self._reports: dict[str, ReportRecord] = {}

    async def upsert_user_profile(self, messenger_type, messenger_user_id, template):
        key = (messenger_type, messenger_user_id)
        existing = self._users.get(key)
        record = UserProfileRecord(
            id=existing.id if existing else str(uuid.uuid4()),
            messenger_type=messenger_type,
            messenger_user_id=messenger_user_id,
            template=template,
            template_version=load_sales_template_catalog().version,
        )
        self._users[key] = record
        return record

    async def get_user_profile(self, messenger_type, messenger_user_id):
        return self._users.get((messenger_type, messenger_user_id))

    async def save_report(self, row):
        record = ReportRecord(id=str(uuid.uuid4()), **row)
        self._reports[record.id] = record
        return record

    async def get_report(self, report_id):
        return self._reports.get(report_id)


class SupabaseReportStore:
    def __init__(self, base_url: str, service_role_key: SecretStr, timeout_s: float = 10.0,
                 transport: httpx.AsyncBaseTransport | None = None):
        if not base_url or not service_role_key.get_secret_value():
            raise ReportStoreException("Supabase URL and service role key are required", "REPORT_STORE_NOT_CONFIGURED")
        self._rest = base_url.rstrip("/") + "/rest/v1"
        self._key = service_role_key
        self._timeout = timeout_s
        self._transport = transport

    def _headers(self, prefer: str = "return=representation") -> dict[str, str]:
        key = self._key.get_secret_value()
        return {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": prefer,
        }

    async def _request(self, method: str, path: str, *, params=None, json=None, prefer="return=representation"):
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                res = await client.request(method, f"{self._rest}/{path}", params=params, json=json,
                                           headers=self._headers(prefer))
        except httpx.HTTPError as exc:
            raise ReportStoreException("Supabase request failed") from exc
        if res.status_code >= 400:
            # 응답 본문에는 입력값이 섞일 수 있어 상태코드만 남긴다.
            raise ReportStoreException(f"Supabase returned HTTP {res.status_code}")
        return res.json() if res.content else []

    @staticmethod
    def _to_user(row: dict[str, Any]) -> UserProfileRecord:
        return UserProfileRecord(
            id=row["id"],
            messenger_type=row["messenger_type"],
            messenger_user_id=row["messenger_user_id"],
            template=SalesTemplateSelection(
                category_id=row["category_id"], product_id=row["product_id"], value_prop_ids=row["value_prop_ids"]
            ),
            template_version=row["template_version"],
        )

    async def upsert_user_profile(self, messenger_type, messenger_user_id, template):
        rows = await self._request(
            "POST", "users",
            params={"on_conflict": "messenger_type,messenger_user_id"},
            json={
                "messenger_type": messenger_type,
                "messenger_user_id": messenger_user_id,
                "template_version": load_sales_template_catalog().version,
                "category_id": template.category_id,
                "product_id": template.product_id,
                "value_prop_ids": template.value_prop_ids,
            },
            prefer="resolution=merge-duplicates,return=representation",
        )
        return self._to_user(rows[0])

    async def get_user_profile(self, messenger_type, messenger_user_id):
        rows = await self._request(
            "GET", "users",
            params={
                "messenger_type": f"eq.{messenger_type}",
                "messenger_user_id": f"eq.{messenger_user_id}",
                "limit": "1",
            },
        )
        return self._to_user(rows[0]) if rows else None

    async def save_report(self, row):
        rows = await self._request("POST", "reports", json=row)
        saved = rows[0]
        return ReportRecord(**{k: saved[k] for k in ReportRecord.model_fields if k in saved})

    async def get_report(self, report_id):
        rows = await self._request("GET", "reports", params={"id": f"eq.{report_id}", "limit": "1"})
        if not rows:
            return None
        return ReportRecord(**{k: rows[0][k] for k in ReportRecord.model_fields if k in rows[0]})


def get_report_store() -> ReportStore:
    from app.core.config import settings

    if settings.REPORT_STORE == "supabase":
        return SupabaseReportStore(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    return MemoryReportStore()
