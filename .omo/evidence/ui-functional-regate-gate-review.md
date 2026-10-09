# UI Functional Re-gate Review

- **recommendation**: APPROVE
- **originalIntent**: 로컬 Mock API 연결 UI에서 서버 중단 등 비HTTP 실패를 표시할 때 기술 상세가 `HTTP 상태: undefined`로 노출되지 않도록 하고, 기존 제출·폴링·결과·샘플 전환 흐름에 회귀가 없는지 재검수한다.
- **desiredOutcome**: `SUBMIT_ERROR`, `POLLING_TIMEOUT`, 기타 미매핑 오류와 오류 코드 누락 모두 `HTTP 상태: 해당 없음`으로 표시되고, UI/API 대상 회귀 테스트가 통과한다.
- **userOutcomeReview**: 현재 구현은 미매핑 오류와 오류 코드 누락을 `해당 없음`으로 정규화한다. 대상 테스트는 실제 `review.html`의 헬퍼를 Node VM에서 실행해 `SUBMIT_ERROR`와 `undefined` 입력을 검증하며, 제출 완료 흐름과 샘플 전환 복구도 함께 통과했다.
- **blockers**: 없음

## Checked artifacts

- `docs/ui-review/review.html:324-336` — 알려진 오류 매핑, `HTTP_<숫자>` 처리, 그 외 `해당 없음` 반환.
- `docs/ui-review/review.html:439-445` — 오류 화면의 `HTTP 상태`가 `getHttpStatusLabel(sample.error_code)`만 사용함.
- `docs/ui-review/review.html:644-652` — 연결 실패를 `SUBMIT_ERROR`로 변환해 동일 오류 렌더러로 전달함.
- `tests/test_ui_review_flow.py:259-312` — 실제 인라인 JS에서 헬퍼를 추출해 `SUBMIT_ERROR`, 폴링·조회 오류, 미지 코드, `undefined`가 모두 `해당 없음`인지 실행 검증함.
- `tests/test_ui_review_flow.py:49-237` — COMPLETED 결과 조회 signal과 샘플 전환 시 제출 버튼 복구를 실행 검증함.
- `HANDOFF.md` — 대상 테스트 수와 현재 Mock 범위, Chrome 실측 주장 및 미구현 범위를 명시함.

## Reproduced evidence

- `python -B -m pytest -q tests/test_ui_review_flow.py tests/test_api.py`: **13 passed**, 2 dependency deprecation warnings.
- 집중 회귀 선택 실행: **4 passed**, 9 deselected, 2 dependency deprecation warnings.
- `git diff --check`: 공백 오류 없음. 줄바꿈 변환 경고만 존재.

## Direct remove-ai-slops / programming pass

- 제품 수정은 단일 헬퍼와 기존 오류 렌더 경계에 머물러 불필요한 새 추상화나 의존성이 없다.
- 회귀 테스트는 단순 문자열 존재가 아니라 실제 헬퍼를 Node VM에서 실행한다. 다만 정규식으로 함수 소스를 추출하는 방식은 구현 위치에 결합되어 있어 유지보수 비용이 있다. 현재 명시된 실패 모드 재발을 직접 탐지하므로 NOTE이며 승인 차단 사유는 아니다.
- 삭제 전용·요청 제거만 확인하는 테스트, 항상 참인 단언, 제품 구현을 재작성한 별도 로직은 발견하지 못했다.
- `review.html`은 큰 단일 파일이지만 이번 재검수의 명시 기준은 오류 라벨 회귀이며, 구조 분리는 범위 밖 NOTE다.

## Evidence gaps / residual risks

- 이번 재검수에서는 Chrome을 새로 구동하지 않았다. 부모가 전달한 서버 중단 및 재기동 Chrome 실측은 보조 증거로만 취급했고, 승인 판단은 현재 소스와 Node VM 실행 결과에 근거했다.
- 전체 172개 오프라인 테스트와 외부 DNS/TCP 0건 주장은 이번 좁은 재검수에서 재실행하지 않았다. 해당 주장은 대상 기준인 오류 라벨 수정 판정에 필요하지 않다.
- 실제 외부 공급자·검색·인증·DB는 구현 및 검증 범위 밖이며 HANDOFF에도 동일하게 제한 사항으로 기록되어 있다.
