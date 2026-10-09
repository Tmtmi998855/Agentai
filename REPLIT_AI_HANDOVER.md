# 🚀 아데어 (Ah! There) — Replit AI & LLM 개발 인수인계 문서

이 문서는 **Replit AI, ChatGPT, Gemini** 등 LLM 기반 개발 도구를 활용하여 **아데어 (Ah! There)** 프로젝트의 앱/웹 서비스를 확장 및 개발하기 위해 프로젝트의 최초 기획 의도, 구조적 아키텍처, 현재 구현 완료된 상태 및 향후 개발 과제를 정리한 전용 가이드입니다.

---

## 1. 📌 최초 기획 의도 및 핵심 원칙

### 🎯 서비스 개요
- **서비스명**: 아데어 (Ah! There)
- **목적**: B2B 영업사원의 미팅 성공률을 극대화하는 **영업 미팅 사전 브리핑 서비스**
- **해결하고자 하는 문제**: 영업사원이 고객사 미팅 전 수동으로 뉴스를 검색하고 가설을 세우는 데 드는 시간을 대폭 줄이고, **고객사의 공개 정보(FACT)**와 **영업 맥락(CONTEXT)**을 AI로 결합하여 **맞춤형 수율 가설(HYPOTHESIS)**과 **핵심 미팅 질문(QUESTIONS)**을 자동 생성합니다.

### 🛡️ 4대 핵심 설계 원칙
1. **업종 하드코딩 금지**: 특정 도메인(렌터카, IT 등)에 종속되지 않고 모든 B2B 영업 맥락에 유연하게 대응하는 추상화 구조 유지.
2. **FACT와 HYPOTHESIS의 엄격한 분리**:
   - `FACT`: 검색/공시/뉴스에서 확인된 검증된 사실 (`evidence_id` 필수 인용).
   - `HYPOTHESIS`: Fact에 기반해 AI가 추론한 영업 가설 (근거 없이 주장 금지 - Fail-closed 차단).
3. **Reasoning & Search Provider 추상화**:
   - OpenAI, Perplexity, Naver, DART 등 공급자를 용이하게 교체/추가할 수 있는 인터페이스 구조.
4. **보안 및 PII 정화 (Sanitization)**:
   - 사용자 입력 원문(PII, 내부 거래 조건 등) 및 백엔드 예외 추적 내용(Traceback)을 외부/고객에게 노출하지 않음.

---

## 2. 🏗️ 현재까지의 구현 상태 (V0 백엔드 & UI 완료)

현재 코드베이스는 **FastAPI 기반 비동기 백엔드** 및 **HTML/JS 단일 웹 UI**로 오프라인 MOCK 테스트까지 100% 검증 완료된 상태입니다.

### 📂 주요 폴더 구조
```text
ah-there/
├── app/
│   ├── api/             # FastAPI 엔드포인트 (/v1/briefings, /v1/briefing-jobs, /ui-review)
│   ├── core/            # Config, 예외처리(Exceptions), 보안 정책(Policy)
│   ├── domain/          # Pydantic 데이터 모델 (Models, Pipeline, Jobs)
│   ├── providers/       # LLM 및 검색 공급자 추상화 (Mock, OpenAI, Perplexity)
│   └── services/        # 비동기 작업 관리자(BriefingJobManager), 추론 파이프라인 엔진
├── docs/
│   └── ui-review/       # 웹 UI 검토용 review.html 및 디자인 스펙
├── scripts/             # 오프라인 샘플 생성 스크립트
├── tests/               # pytest 테스트 코드 (170+ 단위/통합 테스트 통과)
├── pyproject.toml       # Python 패키지 의존성 정의
└── HANDOFF.md           # 개발 작업 이력 및 검증 내역
```

### ⚡ 완료된 핵심 기능
1. **비동기 3단계 API 파이프라인 (202 Polling 패턴)**:
   - `POST /v1/briefings`: 브리핑 생성 요청 수신 후 `job_id` 반환 (`202 Accepted`)
   - `GET /v1/briefing-jobs/{job_id}`: 작업 진행 상태 폴링 (`PENDING` -> `RUNNING` -> `COMPLETED` / `FAILED`)
   - `GET /v1/briefings/{briefing_id}`: 완료된 최종 브리핑 리포트 조회
2. **로컬 Mock API & Web UI 연동**:
   - `docs/ui-review/review.html` 프론트엔드가 FastAPI의 `/ui-review` 경로에서 동종 출처로 렌더링되며, 실시간 비동기 폴링을 통해 브리핑 리포트를 출력함.
3. **엄격한 인용 무결성 (Citation Integrity)**:
   - 근거 없는 가설 생성 시 `INVALID_CITATION` 에러로 차단하는 안전장치 구현.

---

## 3. 🗺️ Replit AI와 함께 진행할 향후 과제 (Backlog)

Replit AI / GPT / Gemini를 활용하여 구현할 우선순위 작업 목록입니다:

### 1단계: 실공급자 (Real Provider) API 연동
- [ ] **Perplexity Search API 연동**: `app/providers/perplexity_search.py`를 활용해 실제 웹/뉴스 검색 실행.
- [ ] **OpenAI / LLM API 연동**: `app/providers/openai_compatible.py`에 API Key를 연결하여 실시간 AI 가설 및 질문 추출.

### 2단계: DB 영속화 & 사용자 관리
- [ ] **In-Memory Store -> DB 전환**: 현재 메모리(`max_capacity=100`) 관리 방식을 PostgreSQL(Supabase) 또는 Redis로 전환.
- [ ] **회원가입 & Auth (JWT)**: 사용자별 작성된 브리핑 히스토리 저장 기능 추가.

### 3단계: 프론트엔드/앱 고도화
- [ ] **React / Next.js / Flutter 앱 변환**: 기존 `docs/ui-review/review.html` 단일 페이지를 모바일 앱 및 현대적인 웹 앱 프론트엔드로 변환.

---

## 4. 🤖 Replit AI / GPT / Gemini 지시용 프롬프트 템플릿

Replit AI나 ChatGPT/Gemini에게 코딩 질문이나 기능 추가를 요청할 때 아래 프롬프트를 복사해서 첫 메시지로 전달하세요:

```text
안녕! 나는 "아데어 (Ah! There)" 프로젝트를 Replit에서 개발하고 있어.

[프로젝트 개요]
- 목적: B2B 영업사원을 위한 영업 맥락 + 공개 정보 기반 사전 브리핑 서비스 백엔드 & 웹/앱
- 기술 스택: Python 3.11+, FastAPI, Pydantic v2, Uvicorn, Pytest
- 핵심 규칙:
  1. FACT와 HYPOTHESIS는 엄격히 분리되며, 가설에는 evidence_id 인용이 필수야.
  2. 비동기 작업 폴링 구조(POST 202 -> GET Polling -> GET Result)를 준수해.
  3. 특정 업종에 치우치지 않는 범용적 구조를 유지해 줘.

현재 프로젝트 구조와 REPLIT_AI_HANDOVER.md 문서를 바탕으로 다음 작업을 도와줘:
<원하는 작업 내용 입력 예: Perplexity Search API 연동하기 / DB 영속화 구현하기 등>
```
