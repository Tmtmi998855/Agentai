# Ah! There (아!거기) — B2B Sales Briefing Service Backend V0

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

## 테스트 실행

```bash
# 가상환경 생성 및 의존성 설치
uv venv
uv pip install -e ".[dev]"

# 단위 테스트 실행 (단위 테스트 25건 전건 실행)
.venv/Scripts/python.exe -m pytest -q -m "not integration"
```
