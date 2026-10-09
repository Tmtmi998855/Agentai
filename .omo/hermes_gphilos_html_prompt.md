# 지필로스 UI HTML만 완료

DESIGN.md는 이미 갱신되었습니다. 이제 docs/ui-review/review.html만 수정하세요. 다른 파일은 절대 수정하지 마세요. 외부 검색/API/실사이트 접속, 커밋, 배포 금지.

최소 변경:
1. 기본 폼 값:
company_name=지필로스
sales_profile.company=아!거기
industry=모빌리티·렌터카
product_service=법인 장기렌트카
target_customer=법인 차량 운영 기업
sales_goal=법인 장기렌트 도입 상담
department=경영관리팀
role=차량 담당자
meeting_purpose=법인 차량 운영 현황 및 장기렌트 도입 검토
past_notes=빈 값

2. 헤더/폼 위에서 '지필로스 · MOCK_VIRTUAL 시안' 및 사용자 제공 정보(www.g-philos.co.kr, 법인 장기렌트카, 경영관리팀, 차량 담당자)를 보이되 공개정보 검증 전임을 명시.

3. embedded JSON 6종의 키와 값은 한 글자도 변경하지 말고, 기존 샘플/API 제출/폴링/오류 흐름을 유지.

4. SUCCESS 렌더 순서:
회사 개요 → 실적/재무 추이 → 최근 회사 이슈 → 산업/시장 이슈 → 영업 전략 → 출처.
- 회사 개요: 기존 company 데이터.
- 재무: '공개적으로 확인 가능한 재무 추이 자료가 없습니다.' 빈 상태. 그래프 데이터/수치 금지.
- 최근 회사 이슈: sources를 published_at 내림차순으로 카드화하고 title, published_at, excerpt, url만 사용. MOCK_VIRTUAL 고지.
- 산업 이슈: '실제 공개정보 조사 후 표시됩니다.' 빈 상태.
- 영업 전략: demand_hypotheses, meeting_questions, small_talk을 하위 블록으로 묶음. 모든 가설에 'HYPOTHESIS · 미팅에서 확인' 표시.
- 출처: 기존 details 유지.

5. 375px 세로, 768px 이상 회사 개요/재무 2열. 기존 토큰만 재사용. 의미 없는 새 장식/외부 아이콘/새 파일 금지. 접근성 유지.

6. INSUFFICIENT_EVIDENCE, ENTITY_AMBIGUOUS, 오류 렌더도 깨지지 않게 기존 흐름 유지.

수정 후 HTML에서 inline script를 임시 JS 파일로 추출해 node --check만 실행하고 종료하세요. pytest는 Codex가 수행합니다.
