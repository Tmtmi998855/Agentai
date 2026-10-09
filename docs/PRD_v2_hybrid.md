# Ah!There — 기획/설계서 v2 (메신저 + 웹 하이브리드) · 검수 반영본

- 작성일: 2026-10-09
- 기반 문서: 사용자 v2 초안(Hermes Agent 중심 하이브리드), `아거기_Hermes_Master_PRD_v1.md`(2026-09-22), `HANDOFF.md`(V0 백엔드 현황)
- 이 문서의 목적: v2 초안을 **이미 구현된 V0 백엔드(FastAPI, 테스트 200건)** 와 충돌 없이 합치고, 초안에서 고쳐야 할 부분을 바로잡는다.

---

## 0. v2 초안 대비 수정 사항 요약

1. **질문 3선에 근거 추적을 붙였다.** 초안의 `questions JSONB`는 근거 없이 문장만 저장하는 구조라 v1의 핵심 원칙(FACT/HYPOTHESIS 분리, evidence_id 추적)과 충돌한다. 각 질문에 `evidence_ids`, `grounded`(서버 계산), Q3에는 `value_prop_id`를 붙였다.
2. **Perplexity Sonar 답변을 사실로 바로 쓰지 않는다.** Sonar의 본문은 LLM이 요약한 문장이다. 인용 URL만 검색 결과로 받아 기존 EvidenceBuilder → 원문 대조(EXACT_EXCERPT_MATCH) → FACT_CONFIRMED 경로를 그대로 탄다.
3. **"법인 장기렌터카 초기 타깃"과 "업종 하드코딩 금지"를 둘 다 지킨다.** 업종별 문구는 코드가 아니라 `app/data/sales_templates.json` 데이터로만 관리한다.
4. **DB 스키마를 고쳤다.** 아래 5장 참고 (유니크 키, 타임스탬프, 소구점 ID 저장, RLS).
5. **클라이언트를 Android에서 텔레그램 + Next.js 웹으로 바꾼다.** v1 PRD의 Android Compose 단계는 보류한다.
6. **FastAPI 백엔드는 버리지 않는다.** 파이프라인은 Python 코드 그대로 MCP 서버(`app/mcp_server.py`)가 불러 쓰고, FastAPI는 로컬 검토 UI와 `/v1/sales-templates` 같은 웹용 API로 유지한다.

---

## 1. 서비스 정의

- 서비스명: Ah!There (한글 표기는 확인 필요 — 기존 문서는 "아!거기", v2 초안은 "아데어")
- 타깃: 외근·미팅이 잦은 B2B 필드 영업사원 (초기 검증 업종: 법인 장기렌터카/플릿)
- 한 줄 정의: 메신저로 기업명만 보내면 미팅 직전에 읽을 현장 브리핑과 **전략 질문 3선**을 받고, 상세 근거는 웹 리포트에서 본다.
- North Star: AI가 만든 질문이 실제 고객 미팅에 도움이 되었는가?

## 2. 듀얼 채널 UX

- 메신저(텔레그램 우선): 트리거와 즉시 실행. 현황 요약 최대 3줄 + 질문 3선 + 리포트 링크. 30초 안에 읽는 분량.
- 웹 대시보드(Next.js): 리포트 상세(기업/산업 출처 분리, 원문 링크), 미팅 메모, 과거 리포트 아카이브.
- 메신저 확장 시 확인 필요:
  - 카카오톡: 개인 계정 봇은 불가. 카카오톡 채널 + 카카오 i 오픈빌더 스킬 서버 연동이 필요하다.
  - iMessage: 공식 봇 API가 없다. 후순위.

## 3. 핵심 로직

### 3.1 영업 프로필 템플릿 (3단계 온보딩) — 구현 완료

- 데이터: `app/data/sales_templates.json` (카테고리 4종: 법인 모빌리티, IT 인프라/클라우드, 그룹웨어/SaaS, 사무기기)
- 소구점 그룹: `COST`(비용 절감) / `TAX`(세무·회계 혜택) / `OPS`(운영 효율성)
- 선택 규칙: 카테고리 1개, 그 카테고리의 품목 1개, 그 카테고리의 소구점 1~3개 (중복·타 카테고리 소구점 거부)
- 저장은 ID만 한다. 라벨이 바뀌어도 기존 유저 데이터가 깨지지 않는다.
- 기존 자유 텍스트 `SalesProfile`로 자동 변환되므로 P1~P4 파이프라인은 그대로 동작한다.

### 3.2 듀얼 리서치 — 구현 완료 (Mock 기준)

- 1차(기업 레벨): `{기업명} 최근 6개월 주요 뉴스 공시 / 시설 증설 투자 / 신규 채용`
- 2차(산업 레벨): `{고객사 산업} 산업 최신 시장 동향 / 원가 규제 이슈 / 업계 공통 과제`
- 고객사 산업은 요청의 `target_industry`가 우선, 없으면 기업 식별 결과의 업종을 쓴다.
- 쿼리는 공개 식별자 + 주제어로만 조립하고 기존 `SearchPrivacyFilter`(PII·CRM 키워드 차단)를 통과해야 한다.
- 수집된 근거에는 `scope:company` / `scope:industry` 태그가 붙고, 고객용 출처(`BriefingSource.scope`)에도 노출된다.

### 3.3 전략 질문 3선 (P5) — 구현 완료

- 순서·유형 고정: Q1 `COMPANY_ISSUE`(기업 이슈 인지) → Q2 `INDUSTRY_TREND`(산업 트렌드 공감) → Q3 `SOLUTION_BRIDGE`(솔루션 브리지)
- 서버 강제 규칙 (위반 시 `INVALID_CITATION`으로 차단):
  - 인용 evidence_id는 FACT_CONFIRMED 근거만
  - Q1은 기업 범위, Q2는 산업 범위 근거만
  - Q3의 `value_prop_id`는 영업사원이 선택한 소구점만
  - `grounded`는 LLM 값을 무시하고 서버가 다시 계산 (근거 없으면 메신저에 "근거 부족·일반 질문" 표시)
- 프롬프트: `app/prompts/p5_strategic_questions.py` (v1.0.0). 질문은 "사실 단정"이 아니라 "미팅에서 확인할 가설" 형태로 쓰게 한다.

## 4. 시스템 아키텍처

```text
[영업사원] ──텔레그램──▶ [Hermes Agent (게이트웨이 + LLM 오케스트레이션)]
                                 │ MCP (stdio)
                                 ▼
                      [ah-there MCP 서버  app/mcp_server.py]
                        ├─ list_sales_templates
                        ├─ save_sales_profile
                        └─ create_meeting_briefing
                                 │ (같은 프로세스에서 Python 파이프라인 호출)
                                 ▼
   Entity → P1 → P2 → 듀얼 검색(Perplexity) → Evidence/원문 검증 → P3 → Rule Engine → P4 → P5
                                 │
                                 ▼
                      [Supabase Postgres: users / reports]  ◀── service_role 키 (서버 전용)
                                 │
                                 ▼
                      [Next.js 웹 뷰어 /report/{id}]  (Vercel, 서버 컴포넌트에서만 조회)
```

- 초안의 "MCP Server 1 = Perplexity, MCP Server 2 = Supabase" 구조 대신 **도메인 MCP 서버 1개**로 묶었다. 이유: Hermes LLM이 검색·저장을 직접 조합하면 FACT 검증, 인용 무결성, 개인정보 필터를 우회할 수 있다. 검증 로직은 서버 코드 안에 있어야 한다.
- Hermes는 결과의 `messenger_text`를 수정 없이 그대로 답장하도록 MCP 서버 instructions에 명시했다.

### 4.1 Hermes Agent 연동 예시 (확인 필요)

Hermes Agent의 MCP 설정 키 이름과 형식은 설치 버전의 공식 문서로 확인한 뒤 적용한다. 아래는 형태 예시다.

```yaml
# ~/.hermes/config.yaml (예시 — 키 이름은 Hermes 공식 문서로 확인 필요)
mcp_servers:
  ah-there:
    command: "/path/to/Agentai/.venv/bin/python"
    args: ["-m", "app.mcp_server"]
    env:
      REPORT_STORE: "supabase"
      SUPABASE_URL: "https://<project-ref>.supabase.co"
      SUPABASE_SERVICE_ROLE_KEY: "<서버 전용 키>"
      REPORT_BASE_URL: "https://ahthere.com/report"
```

### 4.2 보안 주의 (다중 사용자 전환 전 필수)

- 현재 `messenger_user_id`는 Hermes LLM이 도구 인자로 넘긴다. 프롬프트 인젝션으로 다른 사람 ID를 넣을 수 있다. 1인 MVP에서는 허용하되, 다중 사용자 전에는 게이트웨이가 발신자 ID를 서버에 직접 주입하도록 바꿔야 한다. (Hermes가 발신자 정보를 도구 컨텍스트로 넘겨주는지 확인 필요)
- 리포트 링크는 UUID v4(추측 불가)지만 링크를 받은 누구나 열람할 수 있다. 질문·소구점은 영업 전략 정보이므로 웹 공개 전 매직링크 만료 또는 로그인을 붙인다.

## 5. 데이터베이스 (Supabase) — `db/supabase/migrations/001_init.sql`

초안 대비 변경점:

- `messenger_user_id UNIQUE` → `UNIQUE (messenger_type, messenger_user_id)`. 텔레그램과 카카오의 ID가 우연히 같을 수 있다.
- `TIMESTAMPTZ DEFAULT timezone('utc', now())` → `DEFAULT now()`. `timezone('utc', now())`는 시간대 없는 timestamp를 돌려주고, timestamptz 컬럼에 넣을 때 세션 시간대로 다시 해석돼 시각이 어긋날 수 있다. (Supabase 기본 세션 시간대가 UTC라 당장 증상은 없지만, 설정이 바뀌면 깨지는 구조다.)
- `category/product/value_props`에 한글 라벨 대신 템플릿 ID와 `template_version` 저장.
- `reports`에 `status`, `briefing`(전체 JSON), `meeting_memo`(웹 메모) 추가. `sources`는 FACT_CONFIRMED 출처만 저장.
- 두 테이블 모두 RLS 활성화, anon 정책 없음. 백엔드와 Next.js 서버 컴포넌트만 service_role 키로 접근한다. (Next.js 클라이언트 번들에 service_role 키를 넣으면 안 된다.)

## 6. 도구별 역할

- Hermes Agent: 텔레그램 입출력, 대화 흐름, MCP 도구 호출
- ah-there 파이프라인(Python): 검색 계획, 근거 검증, 가설/질문 생성, 인용 무결성 검사
- Perplexity API (sonar): 기업·산업 공개 웹 검색 (인용 URL만 근거 후보로 사용)
- 추론 LLM: 기존 `ReasoningProvider` 추상화 유지 (OmniRoute/OpenAI 호환). 초안의 "GPT (Luna 계열)"은 정확한 모델명 확인 필요.
- Supabase: 유저 템플릿, 리포트 저장
- Next.js + Vercel: 리포트 뷰어

## 7. 로드맵 (현재 상태)

- Step 1 프롬프트 검증: **부분 완료.** P5 계약·서버 검증·Mock 흐름 완료. 실제 LLM으로 20~30개 기업 품질 평가는 미실행.
- Step 2 Hermes 도구 연동: **코드 완료.** MCP 서버 3개 도구 + Supabase 저장소 구현. Hermes 실제 연결은 미실행(설정 형식 확인 필요).
- Step 3 텔레그램 봇 개방: 미착수. Hermes 게이트웨이로 텔레그램 연결 후 E2E 확인.
- Step 4 Next.js 웹 뷰어: 미착수. `reports` 행(`briefing` JSON)을 렌더링하는 `/report/[id]` 페이지.
- 선행 과제: 오케스트레이터에 실제 Perplexity/LLM 공급자 주입 (현재 기본값은 Mock). `HANDOFF.md`의 "실공급자 1개 회사 검증"과 같은 작업이다.
