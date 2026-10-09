# 작업: 지필로스 MOCK_VIRTUAL 모바일 브리핑 시안 구현

현재 저장소 C:\Users\jfki8\Downloads\Codex\ah-there 에서 아래 범위만 수정하세요.

## 사용자 승인 내용
사용자가 손으로 그린 모바일 시안의 정보 구조를 기존 docs/ui-review/review.html에 반영합니다.
- 대상 회사: 지필로스
- 사용자 제공 웹사이트: www.g-philos.co.kr
- 제안 상품: 법인 장기렌트카
- 미팅 부서: 경영관리팀
- 담당 역할: 차량 담당자
- 원하는 읽기 순서: 회사 개요 → 실적/재무 추이 → 최근 회사 이슈 → 산업/시장 이슈 → 영업 전략 → 출처

이 작업은 UI/UX 검토용 MOCK_VIRTUAL입니다. 외부 검색, 실제 API, 실제 LLM, 실사이트 접속을 하지 마세요. 공개정보로 확인하지 않은 기업 사실, 재무 수치, 기사, 날짜, 출처를 만들어내지 마세요.

## 수정 허용 파일
1. docs/ui-review/DESIGN.md
2. docs/ui-review/review.html
3. tests/test_ui_review_flow.py (기존 테스트의 가장 작은 확장만 필요할 때)

HANDOFF.md는 수정하지 마세요. 최종 검증 후 Codex가 갱신합니다.
백엔드, 도메인 모델, 샘플 JSON 파일, 샘플 생성 스크립트는 수정하지 마세요. 커밋과 배포도 하지 마세요.

## 핵심 구현 요구사항
1. 기존 단일 HTML, 인라인 CSS/JS, 외부 자원 없음, connect-src self를 유지합니다.
2. 현재 embedded JSON 6종의 키와 값, 기존 샘플 버튼, 기존 로컬 Mock API 제출/폴링/결과 렌더링을 그대로 유지합니다.
3. 상단 기본 화면에 지필로스 · MOCK_VIRTUAL 시안을 명확히 표시합니다. 사용자가 제공한 정보만 사실처럼 표시합니다.
4. 기본 입력값: company_name=지필로스, sales_profile.company=아!거기, industry=모빌리티·렌터카, product_service=법인 장기렌트카, target_customer=법인 차량 운영 기업, sales_goal=법인 장기렌트 도입 상담, meeting_context.department=경영관리팀, role=차량 담당자, meeting_purpose=법인 차량 운영 현황 및 장기렌트 도입 검토, past_notes=빈 값.
5. 기존 샘플과 API 결과 렌더러는 새 정보 구조로 정리합니다.
   - 회사 개요: 회사명, 확정 법인/업종/지역/식별 신뢰도 및 웹사이트
   - 실적/재무 추이: 계약에 재무 시계열이 없으므로 숫자/그래프를 날조하지 말고 '공개적으로 확인 가능한 재무 추이 자료가 없습니다.'라는 빈 상태를 보여줍니다. 시각적 차트 틀/범례는 가능하지만 데이터 선/막대/수치는 금지합니다.
   - 최근 회사 이슈: 실제 계약의 sources를 날짜 순서로 카드화하되 source의 제목/날짜/요약/링크만 사용합니다. 가상 출처임을 표시합니다. sources가 없으면 빈 상태입니다.
   - 산업/시장 이슈: 현재 계약에 구분된 산업 동향 필드가 없으므로 '실제 공개정보 조사 후 표시됩니다.' 빈 상태를 사용합니다.
   - 영업 전략: demand_hypotheses, meeting_questions, small_talk을 한 섹션 아래 명확히 나눠 배치합니다. 모든 가설에는 HYPOTHESIS · 미팅에서 확인을 표시합니다.
   - 출처: 기존 native details와 MOCK_VIRTUAL 고지를 유지합니다.
6. 손그림의 모바일 구조를 살리되 현재 DESIGN.md 토큰을 재사용합니다. 새 임의 색상이나 외부 아이콘은 추가하지 마세요.
7. 375px 모바일에서는 위 순서로 세로 흐름, 768px 이상에서는 회사 개요와 재무 빈 상태를 2열로 보여줄 수 있습니다. 1280px에서도 본문 최대 폭과 가독성을 유지합니다.
8. 기존 접근성을 유지합니다.
9. 기본 첫 렌더도 지필로스 컨텍스트가 보이게 하되 embedded SUCCESS 샘플 객체는 바꾸지 마세요. 가장 작은 방법으로 별도 UI 전용 컨텍스트/표시를 더하거나 입력 폼/헤더를 통해 충분히 드러내세요. 가짜 BriefingObject를 새로 만들지 마세요.
10. DESIGN.md의 제품 읽기 순서, 재무/산업 빈 상태, 사용자 제공 정보와 검증된 공개정보 경계를 먼저 갱신한 뒤 HTML을 맞춥니다.

## 검증
- 인라인 JS 문법 유지
- 기존 tests/test_ui_review_flow.py 통과
- embedded 6개 JSON 샘플 변경 없음
- git diff --check 통과

최종 답변에는 수정 파일, 핵심 변경, 실행한 검증과 결과, 남은 한계를 간결하게 보고하세요.
