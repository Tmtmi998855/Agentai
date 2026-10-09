# CLAUDE.md — 아!거기 (Ah! There)

## 프로젝트 개요
아!거기는 영업사원의 영업 맥락과 고객사 공개정보를 결합해 잠재 수요 가설 및 미팅 질문을 생성하는 B2B 영업 미팅 브리핑 서비스 백엔드이다.

## 핵심 원칙
- 특정 업종(렌터카 등) 하드코딩 금지
- FACT와 HYPOTHESIS 엄격 분리 및 evidence_id 추적
- ReasoningProvider 추상화를 통한 멀티 LLM 공급자 지원
- API Key/시크릿 절대 노출 금지
- Pydantic 기반 데이터 구조 및 검증
