# HANDOFF.md — 아!거기 (Ah! There)

- **현재 목표**: 기존 정적 UI 시안(`docs/ui-review/review.html`)을 로컬 Mock 비동기 브리핑 API(`/ui-review` 경로)에 연결 완료하였으며, 실공급자 1회사 검증 준비를 진행한다.
- **현재 상태**:
  1. P3 unconfirmed evidence 인용 시 `supporting_evidence` 및 `contradicting_evidence` 양쪽 모두 `CitationIntegrityException(INVALID_CITATION)`으로 fail-closed 차단 및 파라미터화 검증 완료.
  2. 오프라인 샘플 생성 스크립트(`scripts/generate_ui_review_samples.py`)의 default `output_dir`를 `__file__` 기준 저장소 루트 경로(`docs/ui-review/samples`)로 정정.
  3. UI 검토용 샘플 6종 (`docs/ui-review/samples/`) 및 `manifest.json` 생성 완료.
  4. 샘플 무결성 및 `tmp_path` 재생성 자동 테스트 (`tests/test_ui_review_samples.py`) 완료: BriefingObject/ErrorResponse roundtrip, HTTP 200/502/504/422 상태코드, MOCK_VIRTUAL provenance, 정상 인용 무결성, 감사필드/비밀값 미노출 검증.
  5. 비동기 브리핑 작업 관리자(`BriefingJobManager`), lifespan 격리, in-memory bounded store (`max_capacity=100`), GET/POST 202 Polling endpoints 구현, sanitized error logging 및 exact URL matching 가상 fixture 갱신 완료.
  6. **로컬 Mock API 연동 완료**: 백엔드 비동기 API (`POST /v1/briefings`, `GET /v1/briefing-jobs/{job_id}`, `GET /v1/briefings/{briefing_id}`)와 정적 HTML 시안 (`docs/ui-review/review.html`)이 FastAPI 동일 출처 `/ui-review` 경로를 통해 연결됨.
  7. **UI 입력 폼 및 폴링 구현**: 필수 6개 필드, 선택 4개 필드, MOCK_VIRTUAL 기본값, idle/submitting/PENDING/RUNNING/COMPLETED/FAILED 상태 전환, 중복 제출 방지, 이전 요청/폴링 중단 cleanup, CSP `connect-src 'self'`, 단일 `renderData` 함수 재사용 구현 완료. Vercel 정적 배포에서는 샘플 검토를 계속 지원하며 API 제출 시 안내문구를 표시함.
  8. **실제 모델 미연동**: OmniRoute / OpenAI / Perplexity 등 실재 외부 LLM API는 호출하지 않으며 `OrchestratorMockProvider` 기반 가상 추론 파이프라인으로 작동.
  9. **실제 검색 미연동**: Naver / Google / DART 등 실재 검색/공시 API는 호출하지 않으며 `MockSearchProvider` 기반 동적 가상 데이터 사용.
  10. **선택적 API 미구현**: 회원가입/로그인/Auth(JWT), DB 영속화(PostgreSQL/Redis), 피드백 수집 API, LLM 관측/비용 DB 트래킹은 V0 오프라인 scope 미구현.
  11. 입력값 검증 실패(HTTP 422)는 `VALIDATION_ERROR`와 고정 메시지로 반환하며 내부 메모 등 입력 원문을 노출하지 않음. 공백 전용 미팅 맥락은 거부하고 누락/null은 허용함.
  12. 예상 밖의 HTTP 500은 디버그 설정과 관계없이 정화된 JSON으로 반환하고, 고객용 출처에는 승인된 `verification_record.target_claim`만 사용함. 원본 기획서 확보본의 최신성은 확인되지 않음.
- **검증 결과**:
  - `PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1 .venv/Scripts/python.exe -B -m scripts.generate_ui_review_samples` 성공적 실행.
  - UI 흐름/API 대상 테스트: `13 passed, 2 warnings`. Node 실행 환경에서 POST → COMPLETED 폴링 → 결과 조회 시 signal 미중단, 작업 중 샘플 전환 후 제출 버튼 복구, 오류별 HTTP 상태 라벨을 검증.
  - 외부 DNS/TCP 차단 오프라인 전체 테스트: `172 passed, 2 deselected, 2 warnings`; 외부 DNS 0건, 외부 TCP 0건.
  - FastAPI `GET /ui-review`가 200 `text/html`을 반환하고 폼·실제 API 경로·CSP `connect-src 'self'`를 포함함.
  - Chrome 실측: `분석 준비 → PENDING → COMPLETED → SUCCESS 결과`와 작업 중 샘플 전환 취소/버튼 복구 확인. 375/768/1280px에서 문서 폭이 viewport 폭을 넘지 않았고 브라우저 콘솔 오류·경고는 0건.
  - 독립 재검수: 기능 게이트 `APPROVE`, 시각/CJK 게이트 `PASS`. `SUBMIT_ERROR`의 HTTP 상태 미상 표시는 `해당 없음`으로 실측 확인.
  - `git diff --check` 통과 (공백 오류 없음), UI 샘플 JSON 6종 변경 없음.
- **검증 한계 및 미구현 사항**:
  - [Vercel 프리뷰](https://ah-there-ui-preview.vercel.app)는 정적 샘플 검토 전용이며, 라이브 로컬 Mock API 연동은 FastAPI 동일 출처 `/ui-review`에서 작동함.
  - 제품 검증에서 실제 Perplexity / OmniRoute / LLM 및 외부 웹사이트 호출은 미실행 (Mock 기반).
  - 회원가입/로그인, Auth, DB 영속화, 과거 브리핑 저장, 피드백 API, 관측/비용 DB 저장 미구현.
  - 실측 지연시간(P95 < 45s), 질문 유용성, 3분 이내 읽기 분량, 20~30개 기업 대상 종합 평가 미검증.
- **다음 작업**: 별도 승인·설정 하에 실공급자 1개 회사 검증을 진행한다.
