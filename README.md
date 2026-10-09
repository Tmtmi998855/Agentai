# Ah! There (아데어) — B2B Sales Briefing Service Backend V0

B2B 영업사원의 영업 맥락과 고객사의 최신 공개정보를 결합해 잠재 수요 가설과 미팅 확인 질문을 생성하는 백엔드 서비스입니다.

## 핵심 구조 및 모듈

- **Reasoning Provider Protocol**: OmniRoute / OpenAI 호환 LLM Gateway Adapter (`app/providers/openai_compatible.py`) 및 Mock Provider
- **Search Provider Protocol**: Perplexity Search Adapter (`app/providers/perplexity_search.py`) 및 Mock Search Provider
- **Domain Models & Contracts**:
  - `DemandHypothesisDraft` (LLM 출력용 가설 초안, `signal_level` 제외)
  - `ScoredDemandHypothesis` (Rule Engine 계산 후 승격된 가설, `signal_level` 필수)
  - `Evidence` & `EvidencePack` (검증된 사실, 출처 등급화 A/B/C)
- **Source Tier Engine**: 정부/공시 (Tier A), 주요 언론 (Tier B), UGC/블로그 (Tier C) 및 자동 분류기 (`app/domain/source_tier.py`)
- **Evidence Builder**: 검색 원문(`RawSearchItem`)을 디두프, URL/날짜 검증, 출처 등급화하여 `EvidencePack` 생성

- **v2 하이브리드 확장** (`docs/PRD_v2_hybrid.md`):
  - 3단계 영업 템플릿: `app/data/sales_templates.json`, `app/domain/sales_templates.py`
  - 듀얼 리서치(기업+산업): `app/services/dual_research.py`
  - 전략 질문 3선(P5): `app/services/strategic_question_composer.py`, `app/prompts/p5_strategic_questions.py`
  - 메신저 답장 포맷: `app/services/messenger_formatter.py`
  - 리포트 저장소(Memory/Supabase): `app/services/report_store.py`, `db/supabase/migrations/001_init.sql`
  - Hermes Agent용 MCP 서버: `app/mcp_server.py` (도구: `list_sales_templates`, `save_sales_profile`, `create_meeting_briefing`)

## MCP 서버 실행 (Hermes Agent 연동용)

```bash
uv pip install -e ".[agent]"
# 소유자 텔레그램 숫자 ID를 반드시 지정 (미지정 시 모든 도구 호출 거부)
AH_THERE_OWNER_USER_ID=123456789 python -m app.mcp_server   # stdio 전송
```

Hermes 설정 예시(`~/.hermes/config.yaml`)는 `docs/PRD_v2_hybrid.md` 4.1 참고.

## 테스트 실행

```bash
# 가상환경 생성 및 의존성 설치
uv venv
uv pip install -e ".[dev]"

# 단위 테스트 실행 (Windows: .venv/Scripts/python.exe, Mac/Linux: .venv/bin/python)
.venv/Scripts/python.exe -m pytest -q -m "not integration"
```
