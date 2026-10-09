# 아!거기 (Ah! There) UI/UX 검토 준비도 보고서 (Readiness Report)

- **작성일**: 2026-09-26 (2026-09-27 갱신)
- **문서 목적**: UI/UX 설계 및 검토 직전 백엔드 파이프라인 구현 상태, 도메인 계약 검증 현황, 샘플 JSON 매핑 및 미구현 항목 정리
- **기준 PRD**: Master PRD Draft v1 (2026-09-22, `Master_PRD_Drive_v1.md`)
- **원문 출처**: [아!거기(Ah! There) — Hermes 개발용 Master PRD v1](https://drive.google.com/file/d/1ZdYDvKa3yuyq2dJaZwjNSkqJcOOrIdeV/view). Drive 수정 시각은 `2026-09-22T09:11:53.592Z`; 2026-09-26에 전체 19절을 읽었다. 기존 Hermes 캐시는 없어 링크의 원문을 확보했으며, 다른 최신 문서가 존재하지 않는다고 단정하지 않는다. 원문 SHA-256은 `manifest.json`에 기록했다. (새 기획 원문 최신성은 아직 확인되지 않음)
- **원칙**: 코드 존재가 PRD 변경 승인을 의미하지 않으며, 실제 구현 상태와 PRD 간 차이점 및 미구현 항목을 명확히 기록한다.

---

## 1. 개요

본 보고서는 아!거기 B2B 영업 미팅 브리핑 서비스의 오프라인 파이프라인 및 도메인 계약 구현 상태를 기술한다.
현재 단계는 **비동기 백엔드 로컬 Mock API 및 UI 연동 완료(`/ui-review`), 실공급자/웹호출/DB/Auth 구현 전 오프라인 Mock 기반 파이프라인 검증** 상태이다.
인위적인 숫자 진행률(%) 대신, Master PRD v1의 주요 기능 요구사항별 구현/부분구현/미구현 단계와 검증 결과를 명확히 기술한다.

---

## 2. PRD 기능별 구현 및 검증 매핑

| PRD 절 | 기능 항목 | 구현 상태 | 관련 파일 | 관련 테스트 | 비고 / 차이점 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **7. P1** | Profile Compiler | **부분 구현** | `app/services/pipeline_services.py` | `tests/test_pipeline_v0_stage3.py` | Sales Profile 구조화 컴파일 작동. (P1 사용자 확인 항목, Demand Signal 초안 미구현) |
| **7. P2** | Retrieval Planner | **부분 구현** | `app/services/pipeline_services.py`, `app/services/search_privacy_filter.py` | `tests/test_pipeline_v0_stage3.py`, `tests/test_privacy_filter.py` | 검색 쿼리 생성 및 CRM 비공개 마스킹 구현. (검색 기간, 우선 도메인, 제외 조건 미구현) |
| **7. Evidence**| Evidence Pack & Fact Verification | **부분 구현** | `app/domain/models.py`, `app/services/evidence_builder.py` | `tests/test_evidence_validation.py`, `tests/test_evidence_builder.py` | Source Tier(A/B/C) 및 원문 구절 정확 매칭 `FACT_CONFIRMED` 승격 구조 구현. |
| **7. P3** | Demand Reasoner | **부분 구현** | `app/services/pipeline_services.py` | `tests/test_pipeline_v0_stage3.py` | `supporting`/`contradicting` 미확정 인용 시 `CitationIntegrityException(INVALID_CITATION)` fail-closed 차단. (PRD 11절 존재하지 않는 evidence_id 자동 재평가 미구현) |
| **7. Rule Engine**| Signal Level Scorer | **부분 구현** | `app/services/rule_engine.py` | `tests/test_rule_engine.py` | 5단계 신호 판정(NONE~VERY_STRONG) 서버 모듈화. (최신성/다양성/CRM 확인 가중치 세부 조정 부분 구현) |
| **7, 8. P4** | Briefing Composer | **부분 구현** | `app/services/briefing_composer.py`, `app/services/orchestrator.py` | `tests/test_p4_briefing_composer.py`, `tests/test_briefing_jobs_pipeline.py` | 출력 개수 제한(요약 3~5줄, 질문 3~5개, 가설 최대 3개) 검증. 실제 3분 읽기는 미검증. 로컬 Mock 오케스트레이터는 MEDIUM/LOW를 `ENTITY_AMBIGUOUS`로 조기 분기하지만 실제 후보 선택 흐름은 미구현. |
| **10. Entity**| 기업 식별 (Entity Resolver) | **미구현** | `app/domain/models.py` (도메인 타입만 존재) | - | 독립된 Enterprise Resolver 서비스 및 기업 선택 API 미구현. Mock 식별값만 처리함. |
| **11. Fallback**| 예외 처리기 및 오류 응답 | **부분 구현** | `app/main.py`, `app/core/exceptions.py`, `app/providers/openai_compatible.py` | `tests/test_api.py`, `tests/test_providers.py`, `tests/test_briefing_jobs.py` | 502(`PROVIDER_AUTH_ERROR`), 504(`PROVIDER_TIMEOUT`), 422(`INVALID_CITATION`, `VALIDATION_ERROR`) 계약 구현. 요청 검증 오류는 입력 원문을 응답에서 제거한다. 5xx/네트워크/잘못된 JSON은 `max_retries`만큼 동일 요청 재시도; 4xx/타임아웃은 즉시 반환. PRD의 단계별 1회 재시도 정책과 정확한 일치, 예비 공급자 폴백, 오류를 알려 수정시키는 JSON repair는 미구현/검증 필요. |
| **14. API** | 비동기 Job & Polling API | **구현 완료 (로컬 Mock API & UI)** | `app/main.py`, `app/api/briefings.py`, `app/api/ui_review.py`, `docs/ui-review/review.html` | `tests/test_api.py`, `tests/test_briefing_jobs.py` | PRD 14절의 비동기 `job_id` 생성, Polling API, `/ui-review` HTML 화면 연동 완료. |
| **3, 12, 15**| 사용자/인증/프로필 DB | **미구현** | - | - | 회원가입/로그인, Auth 토큰, 사용자 프로필 DB 영속화 미구현 (V0 오프라인 범주 외) |
| **8, 14, 15**| 브리핑 기록 및 피드백 | **미구현** | - | - | 과거 브리핑 DB 저장 및 질문 도움 피드백 API 미구현 |
| **13, 15**| 관측 및 비용 DB 저장 | **미구현** | `app/domain/models.py` (`ProviderRun` 스키마만 존재) | `tests/test_models.py` | 실행 이력 및 토큰/비용 DB 영속화 미구현 |
| **3. Scope**| CRM 연동 범위 | **MVP 외** | - | - | 사내 CRM 연동은 MVP 스코프 바깥임 |

---

## 3. UI/UX 검토 가능 JSON 샘플 (`docs/ui-review/samples/`)

UI/UX 디자이너 및 프론트엔드 개발자는 `docs/ui-review/samples/` 경로의 6개 표준 JSON 파일 및 `manifest.json`을 통해 오프라인 mock 결과를 검토할 수 있다.
이 샘플들은 `MOCK_VIRTUAL` provenance를 가지며, 실제 웹 검색/원문 수집/LLM 호출 결과가 아닌 오프라인 가상 fixture 결과이다.
세 BriefingObject의 HTTP 200은 로컬 Mock API 및 향후 API의 매핑 결과이며 실제 실공급자 웹/LLM 응답을 관찰한 결과는 아니다. 세 오류 샘플의 502/504/422는 실제 예외 처리기의 반환 상태를 검증했다. 기업 신뢰도, 검색 결과, 원문, LLM 출력은 모두 주입한 fixture다.

1. **`success.json` (BriefingObject, HTTP 200 OK)**
   - 정상 브리핑 완료 흐름 샘플
   - `SUCCESS` 가설 결과는 실제 Rule Engine 판정 상 WEAK/C-tier mock fixture 결과에 기반함 (실제 라이브 LLM/검색 성공 결과 아님)
   - 기업 현황 요약, 아이스브레이킹 주제, demand_hypotheses, 미팅 질문 3개, 출처 목록 포함
   - 원문 비밀값 및 내부 감사 필드(`verified_raw_content`, `verification_record`) 미노출 검증 완료
2. **`insufficient_evidence.json` (BriefingObject, HTTP 200 OK)**
   - 검색 결과나 확정 FACT가 부족할 때의 응답 샘플
   - 가설 생성 없이 근거 부족 경고문(`warnings`) 및 일반 미팅 확인 질문 제공
3. **`entity_ambiguous.json` (BriefingObject, HTTP 200 OK)**
   - 기업 식별 신뢰도가 낮은 경우(LOW)의 응답 샘플
   - `company.resolved_name`이 `null`로 세팅되며 후보 법인 목록(`candidate_entities`) 제시
4. **`provider_auth_error.json` (ErrorResponse, HTTP 502 Bad Gateway)**
   - LLM/공급자 인증 실패 시 마스킹 응답 (HTTP 502, `PROVIDER_AUTH_ERROR`)
5. **`provider_timeout.json` (ErrorResponse, HTTP 504 Gateway Timeout)**
   - 분석 서비스 응답 시간 초과 시 마스킹 응답 (HTTP 504, `PROVIDER_TIMEOUT`)
6. **`invalid_citation.json` (ErrorResponse, HTTP 422 Unprocessable Entity)**
   - LLM 추론 결과가 미확정 `evidence_id`를 인용했을 때 fail-closed 차단 응답 (HTTP 422, `INVALID_CITATION`)

---

## 4. 실공급자 연동 후 검증 필요 항목 (미검증)

다음 항목들은 오프라인 Mock 검토 단계에서는 검증이 불가능하며, 추후 실공급자(Perplexity API, OmniRoute, Groq 등) 연동 후 검증해야 한다:

1. **3분 이내 읽기 분량 (3-minute Readability)**: 실제 생성 텍스트의 가독성 및 분량 실측
2. **질문 유용성 (Question Utility)**: 실제 미팅 현장에서의 가설 및 질문 실효성 평가 (North Star 지표)
3. **실측 지연시간 (Real End-to-End Latency)**: 검색 + LLM + Rule Engine 전체 P95 < 45s 달성 검증
4. **20~30개 기업 대상 종합 평가 (Vertical Proof Evaluation)**: PRD 2, 16, 19절의 20~30개 기업 시나리오 실측 평가

---

## 5. 생성 스크립트 및 테스트 검증

### 샘플 재생성 명령
```bash
PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1 .venv/Scripts/python.exe -B -m scripts.generate_ui_review_samples
```

### 오프라인 단방향 검증 테스트 명령
```bash
PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1 .venv/Scripts/python.exe -B -m pytest -q -p no:cacheprovider -m 'not integration' -k 'not test_web_raw_fetcher_ssrf_redirect_to_private_ip_blocked'
```
(결과: `169 passed, 2 deselected, 2 warnings`)

### 테스트 제외 이유
- `-m 'not integration'`: 외부 HTTP/DNS 네트워크 호출을 포함하는 통합 테스트를 제외하여 오프라인 환경에서 결정론적으로 검증하기 위함.
- `-k 'not test_web_raw_fetcher_ssrf_redirect_to_private_ip_blocked'`: HTTP는 MockTransport지만 최초 `example.com`의 DNS가 모킹되어 있지 않아 실제 시스템 DNS를 호출할 수 있으므로 제외했다. 별도의 모킹된 DNS 리다이렉트 차단 테스트는 실행했다.

## 6. 지금 검토할 수 있는 범위

- JSON 필드 배치, FACT 출처와 HYPOTHESIS 분리, 신호 표시, 근거 부족/기업 선택/공급자 오류 화면 전환의 초안은 검토 가능하다.
- 로딩·완료·실패 화면은 로컬 Job API의 `PENDING`/`RUNNING`/`COMPLETED`/`FAILED` 상태로 초안을 만들 수 있다. 진행률 백분율·완료 알림·재시도 정책은 아직 검증되지 않았다.
- 실제 기업 정보의 양, 출처의 신뢰성, 질문 품질, 긴 텍스트 배치, 실제 분석 시간은 공개정보/LLM 검증까지 판단을 보류한다.
