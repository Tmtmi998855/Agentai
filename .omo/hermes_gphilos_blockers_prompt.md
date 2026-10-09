# 지필로스 UI 검수 차단 이슈 수정

대상 저장소: C:\Users\jfki8\Downloads\Codex\ah-there
수정 허용: docs/ui-review/review.html, tests/test_ui_review_flow.py, 필요하면 docs/ui-review/DESIGN.md 한정.
외부 검색/API/실사이트 접속, 백엔드 수정, embedded JSON 6종 수정, 커밋, 배포 금지.

현재 독립 검수 BLOCK:
1. 지필로스 시안 고지인데 초기 본문은 render("success")로 가상테스트고객A가 보임.
2. 기본값 지필로스로 Mock API를 제출하면 mock_fixtures가 지필로스의 미검증 사업장/채용/확장 사실을 생성할 수 있음.
3. sources URL이 링크 요구에도 span 텍스트임.

최소 수정 요구:
A. embedded JSON은 그대로 두고, 별도 UI 전용 renderGPhilosPreview()를 추가합니다. 가짜 BriefingObject를 만들지 않습니다.
- 사용자 제공 정보만 표시: 지필로스, www.g-philos.co.kr, 법인 장기렌트카, 경영관리팀, 차량 담당자.
- 회사 개요의 확정 법인/업종/지역/식별은 모두 공개정보 검증 전 또는 확인 전.
- 재무/최근 회사 이슈/산업 이슈는 명시적 빈 상태.
- 수요 가설 없음: 확정 FACT가 없어 만들지 않았다고 표시.
- 미팅 질문은 회사 사실을 주장하지 않는 확인 질문만: 현재 법인 차량 운용 방식/계약 갱신 일정/의사결정 기준/운영 불편 등.
- small talk는 확정 이슈 확보 후 표시 빈 상태.
- 출처 0개.
- 샘플 도구에 '지필로스 시안' 버튼을 기존 6개 앞에 추가하고 초기 aria-pressed=true. 기존 success는 false.
- render("gphilos") special branch로 초기 렌더. 기존 6종 버튼/데이터/렌더는 유지.

B. submit handler의 fetch 직전에 일반 경계 추가:
- companyName이 '가상'으로 시작하지 않으면 로컬 Mock API를 호출하지 말고 idle 상태로 복원.
- 안내: 'Mock 분석은 가상 고객사명만 실행할 수 있습니다. 지필로스 실제 분석은 공개정보 공급자 연결 후 진행합니다.'
- 사용자가 가상 고객사명으로 바꾸면 기존 POST/POLL 흐름 정상 동작.
- 이는 지필로스 한 회사 하드코딩이 아니라 모든 실제 회사명 오표시 방지 경계.

C. source URL 링크:
- javascript/data/file 등 금지. URL()로 파싱한 http/https만 href로 사용하고 target=_blank, rel=noopener noreferrer.
- 그 외는 기존 텍스트 표시.
- 최근 회사 이슈와 출처 details 양쪽에 동일 규칙 적용.
- 새 헬퍼는 최소 하나. 보안 분기 회귀 테스트 추가.

D. tests/test_ui_review_flow.py 최소 확장:
- 기존 flow test에서 company_name을 '가상테스트고객A'로 설정해 기존 POST 흐름 유지.
- 별도 또는 같은 Node test에서 company_name='지필로스' 제출 시 fetch 0회, submit disabled=false, 안내 문구 포함을 확인.
- 안전 URL helper http/https 허용, javascript/data/file/invalid 차단 확인.
- 초기 render gphilos 및 섹션 순서를 보호하는 최소 검증 추가.

수정 후 node --check와 tests/test_ui_review_flow.py만 실행하고 결과를 보고하세요. 다른 파일 변경 금지.
