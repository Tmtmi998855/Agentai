# CLAUDE.md — 아데어 (Ah! There)

## 프로젝트 개요
아데어는 영업사원의 영업 맥락과 고객사 공개정보를 결합해 잠재 수요 가설 및 미팅 질문을 생성하는 B2B 영업 미팅 브리핑 서비스 백엔드이다.

## 현재 기준 문서
- 제품/아키텍처: `docs/PRD_v2_hybrid.md` (텔레그램 + Hermes Agent + MCP + Supabase + Next.js)
- 진행 현황: `HANDOFF.md`

## 핵심 원칙
- 특정 업종(렌터카 등) 하드코딩 금지
- FACT와 HYPOTHESIS 엄격 분리 및 evidence_id 추적
- ReasoningProvider 추상화를 통한 멀티 LLM 공급자 지원
- API Key/시크릿 절대 노출 금지
- Pydantic 기반 데이터 구조 및 검증
- 업종별 문구(카테고리/품목/소구점)는 `app/data/sales_templates.json` 데이터로만 관리
- 질문 3선(P5)은 Q1 기업 근거 / Q2 산업 근거 / Q3 선택 소구점만 인용 (서버가 검증)
- `.env` 및 실제 키는 커밋 금지
