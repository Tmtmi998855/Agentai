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

- 서비스명: Ah!There (아데어) — 2026-10-09 확정. 이전 문서의 "아!거기"와 같은 서비스다.
- 타깃: 외근·미팅이 잦은 B2B 필드 영업사원 (초기 검증 업종: 법인 장기렌터카/플릿)
- 한 줄 정의: 메신저로 기업명만 보내면 미팅 직전에 읽을 현장 브리핑과 **전략 질문 3선**을 받고, 상세 근거는 웹 리포트에서 본다.
- North Star: AI가 만든 질문이 실제 고객 미팅에 도움이 되었는가?

## 2. 듀얼 채널 UX

- 메신저(텔레그램 우선): 트리거와 즉시 실행. 현황 요약 최대 3줄 + 질문 3선 + 리포트 링크. 30초 안에 읽는 분량.
- 웹 대시보드(Next.js): 리포트 상세(기업/산업 출처 분리, 원문 링크), 미팅 메모, 과거 리포트 아카이브.
- 메신저 범위 (2026-10-09 결정): **텔레그램만** 먼저 한다.
  - 카카오톡: 보류. 나중에 카카오톡 채널 + 카카오 i 오픈빌더 스킬 서버로 붙인다(개인 계정 봇은 불가). DB의 `messenger_type`에는 'kakao' 값을 미리 허용해 두어 그때 스키마 변경이 없다.
  - iMessage: 공식 봇 API가 없어 계획에서 제외.

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

### 4.1 Hermes Agent 연동 설정 (공식 문서 확인 완료)

Hermes Agent 공식 문서(hermes-agent.nousresearch.com, MCP·Telegram 페이지) 기준으로 확인한 사항:

- MCP 설정 위치는 `~/.hermes/config.yaml`의 `mcp_servers` 키. 로컬 서버는 `command`, `args`, `env`로 지정한다.
- Hermes는 MCP 서버에 내 셸 환경변수를 넘기지 않는다. `env`에 적은 값과 기본 안전 변수만 전달되므로, 필요한 값은 전부 `env`에 적어야 한다.
- `tools.include`로 노출할 도구를 제한할 수 있다.
- 실행 중인 게이트웨이(`hermes gateway`)는 `config.yaml` 변경을 감지해 MCP 연결을 다시 맺는다. 대화 중에는 `/reload-mcp`로 다시 읽는다.
- 텔레그램은 `~/.hermes/.env`에 봇 토큰과 `TELEGRAM_ALLOWED_USERS`(숫자 ID, 쉼표 구분)를 넣는다. 숫자 ID는 @userinfobot에서 확인한다. 이 값이 없으면 게이트웨이가 모든 사용자를 거부한다.
- 아직 실측 필요: 텔레그램 대화에서 MCP 도구가 실제로 호출되는지 (공식 문서에 명시 없음 → Step 3에서 직접 확인).

```yaml
# ~/.hermes/config.yaml
mcp_servers:
  ah-there:
    command: "/절대경로/Agentai/.venv/bin/python"   # Windows: C:/.../Agentai/.venv/Scripts/python.exe
    args: ["-m", "app.mcp_server"]
    env:
      PYTHONPATH: "/절대경로/Agentai"
      AH_THERE_MESSENGER_TYPE: "telegram"
      AH_THERE_OWNER_USER_ID: "123456789"        # 내 텔레그램 숫자 ID (TELEGRAM_ALLOWED_USERS와 동일)
      REPORT_STORE: "supabase"
      SUPABASE_URL: "https://<project-ref>.supabase.co"
      SUPABASE_SERVICE_ROLE_KEY: "<서버 전용 키>"
      REPORT_BASE_URL: "https://<project>.vercel.app/report"
    tools:
      include: [list_sales_templates, save_sales_profile, create_meeting_briefing]
```

```bash
# ~/.hermes/.env
TELEGRAM_BOT_TOKEN=<BotFather에서 받은 토큰>   # 변수명은 `hermes gateway setup` 마법사 결과를 따른다
TELEGRAM_ALLOWED_USERS=123456789
```

### 4.2 사용자 식별 보안 (2026-10-09 수정 완료)

- 문제: 이전 버전은 Hermes의 LLM이 `messenger_user_id`를 도구 인자로 넘겼다. 메시지에 "다른 사람 ID로 조회해"라는 식의 프롬프트 인젝션이 섞이면 남의 프로필·리포트에 접근할 수 있었다.
- 수정: MCP 도구에서 사용자 ID 인자를 없앴다. 서버는 `AH_THERE_OWNER_USER_ID` 환경변수에 고정된 ID만 쓴다. 값이 비어 있으면 모든 요청을 `OWNER_NOT_CONFIGURED`로 거부한다.
- 이중 잠금: Hermes의 `TELEGRAM_ALLOWED_USERS`를 같은 ID로 설정하면, 봇에 말을 걸 수 있는 사람과 데이터 주인이 항상 같다.
- 다중 사용자로 넓힐 때: 사용자마다 Hermes 게이트웨이 + MCP 서버를 따로 띄우거나, 발신자 ID를 서버가 직접 받는 자체 텔레그램 웹훅으로 바꾼다. (그때 다시 설계)
- 리포트 링크: UUID v4라 추측은 불가능하지만 링크를 받은 사람은 열람할 수 있다. 웹 공개 전 매직링크 만료 또는 로그인을 붙인다.

### 4.3 도메인 (미보유)

- 현재 도메인이 없으므로 기본 리포트 주소는 `http://localhost:3000/report`(로컬 Next.js)다.
- Step 4에서 Vercel에 배포하면 무료 주소 `https://<project>.vercel.app/report`를 `REPORT_BASE_URL`로 쓴다.
- 도메인을 사면 `REPORT_BASE_URL`만 바꾸면 된다. 코드 수정은 필요 없다. (이미 보낸 메신저 링크는 옛 주소로 남는다.)

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
- GPT-6 Luna (OpenAI, 2026-09 출시 저가·고속 모델): 세일즈 템플릿 분류 체계 설계와 질문 프롬프트 엔지니어링(사람이 쓰는 작업 도구). 파이프라인 추론 모델 후보로도 쓸 수 있다. 기존 `ReasoningProvider`가 OpenAI 호환이라 `REASONING_MODEL` 값만 바꾸면 된다(OpenRouter 기준 모델 ID `openai/gpt-6-luna`, OpenAI 직접 호출 시 ID는 OpenAI 콘솔에서 확인).
- 추론 LLM: 기존 `ReasoningProvider` 추상화 유지 (OmniRoute/OpenAI 호환). 특정 모델을 코드에 고정하지 않는다.
- Supabase: 유저 템플릿, 리포트 저장
- Next.js + Vercel: 리포트 뷰어

## 7. 로드맵 (현재 상태)

- Step 1 프롬프트 검증: **부분 완료.** P5 계약·서버 검증·Mock 흐름 완료. 실제 LLM으로 20~30개 기업 품질 평가는 미실행.
- Step 2 Hermes 도구 연동: **코드 완료.** MCP 서버 3개 도구 + Supabase 저장소 구현, 사용자 ID 서버 고정. Hermes 설정 형식은 공식 문서로 확인(4.1). 실제 연결은 미실행.
- Step 3 텔레그램 봇 개방: 미착수. Hermes 게이트웨이로 텔레그램 연결 후 E2E 확인.
- Step 4 Next.js 웹 뷰어: 미착수. `reports` 행(`briefing` JSON)을 렌더링하는 `/report/[id]` 페이지.
- 선행 과제: 오케스트레이터에 실제 Perplexity/LLM 공급자 주입 (현재 기본값은 Mock). `HANDOFF.md`의 "실공급자 1개 회사 검증"과 같은 작업이다.

## 8. 운영 단계 결정 (2026-10-16)

- **MVP (방법 A)**: 내 PC에서 Hermes 게이트웨이 + ah-there MCP 서버 + Codex CLI(GPT-6 Luna)를 실행한다. 사용자는 본인 1명. 폰 텔레그램으로 기업명을 보내 사용한다.
  - 설정: `PIPELINE_MODE=live`, `REASONING_PROVIDER=codex_cli`, `SEARCH_PROVIDER=perplexity`
  - 한계: PC가 켜져 있어야 응답한다. 개인 ChatGPT 구독의 사용량 한도를 따른다. 개인 구독으로 다른 사람에게 서비스하지 않는다.
- **실서비스 (방법 B)**: 클라우드 서버 + OpenAI API 키(또는 OpenRouter)로 전환한다.
  - 코드 변경 없이 설정만 바꾼다: `REASONING_PROVIDER=openai_compatible`, `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `REASONING_MODEL`
  - 전환 시점: ① 두 번째 사용자가 생길 때 ② PC가 꺼져 있어도 응답이 필요할 때 ③ Codex 사용량 한도에 걸릴 때 — 셋 중 하나라도 해당하면 전환한다.
  - 전환 시 함께 할 일: 다중 사용자 식별(4.2), 리포트 링크 만료/로그인, Supabase 실DB, Next.js 뷰어 배포.
