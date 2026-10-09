# 비동기 브리핑 생성 및 작업 조회 API 명세서 (V0 MOCK_VIRTUAL)

## 개요
아데어 (Ah! There) B2B 영업 미팅 브리핑 서비스 백엔드의 비동기 브리핑 생성 및 작업 상태/결과 조회 API 명세서이다.

본 V0 오프라인 단계에서는 FastAPI lifespan에 연결된 AnyIO TaskGroup과 프로세스 내 메모리 저장소(`BriefingJobStore`)를 활용하여 HTTP 202 Accepted 조기 응답 및 백그라운드 파이프라인 연동을 제공한다.

---

## ⚠️ 현재 상태 및 구현 제약 안내 (Current Limitations & Non-Implemented Features)
1. **로컬 Mock API 연동 완료 및 UI 연결 완료**: 본 백엔드 비동기 API(`POST /v1/briefings`, `GET /v1/briefing-jobs/{job_id}`, `GET /v1/briefings/{briefing_id}`)는 FastAPI의 동일 출처 `/ui-review` 엔드포인트를 통해 HTML UI 화면(`docs/ui-review/review.html`)과 연결 구현이 완료되었습니다. Vercel 프리뷰 정적 배포에서는 샘플 검토를 계속 제공하며, 제출 시 로컬 Mock API 화면(/ui-review) 실행 안내를 표시합니다.
2. **실제 LLM 모델 미연동**: OpenAI / Perplexity / OmniRoute 등의 실시간 외부 LLM API를 호출하지 않으며, 오프라인 `MockReasoningProvider` 기반 가상 응답을 사용합니다.
3. **실제 검색 API 미연동**: Naver / Google / Serper / DART 등 실재 웹/공시 검색 API를 호출하지 않으며, `MockSearchProvider` 및 exact example.com URL fixture 기반 동적 가상 데이터로 검증합니다.
4. **선택적/부가 API 미구현**:
   - 사용자 회원가입/로그인 및 Auth (JWT/OAuth) 미구현
   - DB 영속화 (PostgreSQL/Redis) 및 과거 브리핑 조회 API 미구현
   - 피드백 수집 및 LLM 관측/비용 트래킹 DB 저장 미구현
   - 기업 선택 API 미구현
5. **원안 최신성 미확인**: 원본 기획서 확보본의 최신성은 확인되지 않음.

---

## 핵심 엔드포인트 목록

| 메서드 | 경로 | 설명 | 정상 상태코드 |
|---|---|---|---|
| `POST` | `/v1/briefings` | 비동기 브리핑 생성 작업 접수 | `202 Accepted` |
| `GET` | `/v1/briefing-jobs/{job_id}` | 작업 상태 엔벨롭 조회 (Polling) | `200 OK` |
| `GET` | `/v1/briefings/{briefing_id}` | 완료된 `BriefingObject` 결과 조회 | `200 OK` |

---

## 1. 비동기 브리핑 생성 요청 (`POST /v1/briefings`)

### 요청 헤더
- `Content-Type: application/json`

### 요청 바디 (`BriefingCreateRequest`)
- `company_name` (필수, string, 1~100자): 대상 고객사 정식 명칭 (공백 불가).
- `sales_profile` (필수, object, `extra="forbid"`): 영업 담당자 맥락 프로필.
  - `company` (필수, string, 1~200자): 영업 담당자 소속 회사명.
  - `industry` (필수, string, 1~200자): 소속 산업군.
  - `product_service` (필수, string, 1~200자): 취급 상품 및 서비스.
  - `target_customer` (필수, string, 1~200자): 타깃 고객 유형.
  - `sales_goal` (필수, string, 1~200자): 영업 목표.
- `meeting_context` (선택, object 또는 null, `extra="forbid"`): 미팅 상황 맥락 (공개 검색 쿼리에 유출 금지).
  - `department` (선택, string, 1~500자): 고객사 미팅 부서.
  - `role` (선택, string, 1~500자): 담당자 직책/역할.
  - `meeting_purpose` (선택, string, 1~500자): 미팅 목적.
  - `past_notes` (선택, string, 1~500자): 과거 메모 및 내부 맥락.

#### 요청 예시
```json
{
  "company_name": "무신사",
  "sales_profile": {
    "company": "아데어",
    "industry": "IT 솔루션",
    "product_service": "기업용 B2B 세일즈 솔루션",
    "target_customer": "중견패션기업",
    "sales_goal": "신규 도입 수주"
  },
  "meeting_context": {
    "department": "영업기획팀",
    "role": "팀장",
    "meeting_purpose": "솔루션 데모",
    "past_notes": "이전 미팅 참고 사항"
  }
}
```

### 응답 바디 (HTTP 202 Accepted)
```json
{
  "job_id": "4e8f6af5-790e-49bc-8ec9-176489f2ceb5",
  "status": "PENDING",
  "status_url": "/v1/briefing-jobs/4e8f6af5-790e-49bc-8ec9-176489f2ceb5",
  "result_url": "/v1/briefings/4e8f6af5-790e-49bc-8ec9-176489f2ceb5",
  "provenance": "MOCK_VIRTUAL"
}
```

---

## 2. 작업 상태 조회 (`GET /v1/briefing-jobs/{job_id}`)

작업 진행 상태를 Polling 방식으로 확인한다.

### 상태 전이 흐름
- `PENDING` -> `RUNNING` -> `COMPLETED`
- `PENDING` -> `RUNNING` -> `FAILED`

### 응답 예시 (진행 중: PENDING / RUNNING)
```json
{
  "job_id": "4e8f6af5-790e-49bc-8ec9-176489f2ceb5",
  "status": "RUNNING",
  "provenance": "MOCK_VIRTUAL",
  "created_at": "2026-09-27T00:00:00.000000+00:00",
  "completed_at": null,
  "error_code": null,
  "error_http_status": null
}
```

### 응답 예시 (성공 완료: COMPLETED)
```json
{
  "job_id": "4e8f6af5-790e-49bc-8ec9-176489f2ceb5",
  "status": "COMPLETED",
  "provenance": "MOCK_VIRTUAL",
  "created_at": "2026-09-27T00:00:00.000000+00:00",
  "completed_at": "2026-09-27T00:00:01.200000+00:00",
  "error_code": null,
  "error_http_status": null
}
```

### 응답 예시 (실패: FAILED)
작업 상태 엔벨롭 조회는 HTTP 200 OK를 유지하며, `status="FAILED"`와 정화된 error_code/http_status를 제공한다.
```json
{
  "job_id": "4e8f6af5-790e-49bc-8ec9-176489f2ceb5",
  "status": "FAILED",
  "provenance": "MOCK_VIRTUAL",
  "created_at": "2026-09-27T00:00:00.000000+00:00",
  "completed_at": "2026-09-27T00:00:00.500000+00:00",
  "error_code": "PROVIDER_TIMEOUT",
  "error_http_status": 504
}
```

---

## 3. 완료된 브리핑 결과 조회 (`GET /v1/briefings/{briefing_id}`)

`briefing_id`는 V0 구현에서 `job_id`와 동일한 UUID를 사용한다.

### 응답 상태
- **HTTP 200 OK**: 작업 완료 (`COMPLETED`). `BriefingObject` 반환 (비즈니스 상태: `SUCCESS`, `INSUFFICIENT_EVIDENCE`, `ENTITY_AMBIGUOUS`).
- **HTTP 409 Conflict**: 작업 미완료 (`PENDING` 또는 `RUNNING`).
- **HTTP 404 Not Found**: 미등록 `briefing_id`.
- **HTTP 500 Internal Server Error**: 시스템 내부 처리 오류 (`INTERNAL_SERVER_ERROR`).
- **HTTP 502 Bad Gateway**: 공급자 오류 (`PROVIDER_AUTH_ERROR` / `PROVIDER_ERROR`).
- **HTTP 503 Service Unavailable**: 작업 관리자 이용 불가 또는 취소 (`JOB_MANAGER_UNAVAILABLE` / `JOB_CANCELLED` / `JOB_STORE_FULL`).
- **HTTP 504 Gateway Timeout**: 공급자 타임아웃 (`PROVIDER_TIMEOUT`).
- **HTTP 422 Unprocessable Entity**: 입력값 검증 실패 (`VALIDATION_ERROR`) 또는 인용 무결성 검증 실패 (`INVALID_CITATION`).
