Source-Owned Unit Binding — Stage 2 (2026-10-12)

1. 변경 파일
   신규 `backend/app/unit_binding.py`, `backend/tests/test_unit_binding.py`.
   연동: `structured_cells.py`, `unit_validation.py`, `evidence_requirements.py`,
   `index_admission.py`, `fact_fusion.py`, `period_binding.py`.
   Legacy fixture의 새 proof 제거: `test_period_binding.py`.
   계약: `api-contract.md`, `acceptance.md`, `qa-rules.md`.
   검증 산출물: `evals/results/unit-binding-stage2-20261011/` (작업 시작일 명칭 유지).

2. 기존 실패 조건
   추출기는 `local or row_units or column_units or table_units`로 앞선 범위를 선택했다.
   선택한 span만 full-unit/geometry/component 검증하므로 다른 적용 선언과의 충돌은
   독립 계약으로 남지 않았다. Fragmented composite, suffix-only unit, 다른 행·열의
   선언, 혼합 header, merged scope/geometry는 원문 검증 없이 복구할 수 없었다.

3. 새 계약
   `source-owned-unit-v1`은 source SHA-256, page/table/row/column identity,
   metric/value/unit span, metric/value/header/unit cell, 적용 scope, context,
   기존 period proof와 unit component dependency를 함께 보존한다.
   해당 metric의 source stream에서 적용 가능한 owner가 정확히 하나여야 한다.
   Native/OCR의 독립 관측을 결합해 하나의 proof를 만들지 않는다.
   기존 cross-stream suffix conflict 검증은 유지한다.

4. 지원 범위
   A: value cell의 literal suffix/unit. B: 독립 unit cell 또는 metric의 `(unit)` row 선언.
   C: value와 동일한 column의 observed header. D: 기존 validator가 승인하는
   parenthesized 단일 table 선언 (`(단위:억원)` 포함)과 observed column topology.
   E: 각 행 또는 각 cell에 귀속이 명시된 mixed unit.
   원문 span·geometry·period·metric/context 검증을 모두 통과해야 한다.

5. Mixed ambiguity
   서로 다른 행/열의 선언은 membership으로 분리한다. 적용 가능한 복수 선언은
   canonical이 같더라도 HOLD다. `(억원,%)`, `(단위:억원,%)`의 mapping 없는 선언은
   local unit으로 덮어쓰지 않는다. 좁은 범위가 상위 범위를 제한한다는 source proof를
   이번 단계에서 추정하지 않는다. 자동 scope override는 지원하지 않는다.

6. Composite 보존
   기존 `semantic-unit-components-v1`과 `verified-dependencies-v1`을 재사용한다.
   `조 + 원`, `백만 + 원`, `million + USD`의 원문 공백·각 component span/bbox/source를
   보존한다. Missing component observation/proof/physical chunk는 완전한 unit evidence가 아니다.
   Currency/scale/%/%pt를 서로 변환하거나 동등 unit으로 취급하지 않는다.

7. Period 통합
   기존 `source-owned-period-v1` 내용을 바꾸지 않고 새 unit proof에 포함한다.
   새 parser는 `fact-fusion-paddle-v5`다. v4의 period proof 필수 검사는 유지한다.
   Legacy observation의 version은 변경하지 않으며 원문 재구성으로만 승인한다.

8. Verified fact
   Unit approval은 metric/period/value/geometry/context 검증 뒤 생성된다.
   독립 E2E에서 8종 구조, 총 16개 fact를 확인했다. Unit이 해결돼도
   scope/annotation/comparison/requirement는 각각 기존 gate를 통과해야 한다.
   Numeric prose/vertical chart는 기존 literal suffix 계약을 유지하며 이번 새 table
   ownership contract로 모든 자유 문장을 재인증했다고 주장하지 않는다.

9. Dependency/pack
   Primitive graph의 기존 fact preservation을 통해 `unit_binding`이 유지된다.
   Admission group에도 binding을 전달하고 모든 component를 dependency slices로 보존한다.
   Physical chunk는 원문 exact slice이고 search representation은 별도다.
   Pack에서 stored proof와 원문을 재검증한다. 새 v5 proof 삭제/변조는 HOLD다. 관측 table의 새 topology fallback에도 unique unit owner 검사를 적용한다.
   기존 validator의 header band와 literal source 검증은 그대로 재사용한다. Legacy frozen fact는 기존 버전을 유지한다.

10. Synthetic tests
   독립 38개: positive 8, negative 30. Company/gold/holdout bbox를 복사하지 않았다.
   Negative: 복수 table/local/header/cell owner, 다른 row/column, source span 삭제,
   component 삭제·누락, ownership/scope/canonical/source/proof 변조, unit 추정,
   mapping 없는 mixed declaration과 prefix 혼합 선언, 새 topology fallback의 ambiguity 우회 차단, 이웃 table 선언의 상속 차단을 포함한다.

11. Synthetic E2E
   `synthetic-e2e.json`: 8/8 coverage complete, 각 graph 2 nodes / admission 2 groups,
   총 16 verified facts. 원문 component와 physical chunk exactness를 확인했다.
   DB/OCR/embedding/LLM/corpus 호출은 없다.

12. 기존 regression
   고정된 최종 production code로 offline replay를 완료했다.
   개발 12/12, POSCO 1/1, selected pack 20/20 동일, 현대차·삼성 offline PASS,
   기아 REVIEW, SK·Counts HOLD를 유지했다. Offline PASS pack 17개도 동일하다.
   Review-aware false-complete는 0이다. `regression-summary.json` 참조.
   최초 장시간 감사는 실행 중 source 변경을 hash guard가 감지해 폐기했다.
   최종 감사는 모든 source hash를 고정하고 통과했다. 감사 도구의 반복 검증 캐시는
   document/page/parser/text/table facts/provenance의 전체 preimage로 구분하며,
   distinct input은 원래 validator로 검증하고 mutable audit sink는 캐시하지 않는다.
   반환 값은 deepcopy하고 retrieval/판정/threshold는 변경하지 않는다.
   Sealed v1의 기업/정답을 새 평가나 fixture에 사용하지 않는다.

13. False-complete
   복수 owner·proof/component 부재·변조는 admission/coverage를 승인하지 않는다.
   Review-aware 판정에서는 coverage와 automatic strict/manual REVIEW를 구분한다.
   Unit proof가 다른 미검증 requirement의 PASS 근거가 될 수 없다.

14. 전체 테스트
   최종 `check-completion.log`와 `targeted-completion.log`, `table-context.log` 참조. Targeted 167 passed (`targeted-completion.log`), unit/업로드/row 보존 60 passed.
   Backend 전체 608 passed / 1 skipped, frontend 7 passed, lint/build PASS.
   추가 mixed prefix 회귀를 포함한 전체 check는 backend/frontend/lint/build를 검증한다.
   기존 skip은 미설치 google.genai 테스트다. 중첩 macOS sandbox-exec 실패는
   동일 check를 환경 제한 밖에서 실행해 검증했으며 테스트를 약화하지 않았다.

15. Hardcoding/diff
   Production unit module에 기업/질문 ID/PDF/holdout 정답·좌표 예외는 없다.
   Metric에 맞춰 단위를 임의 주입하지 않는다. Literal USD unit은 일반 lexer 확장이다.
   Validator geometry thresholds, BM25/vector/RRF, Gold와 모델 설정은 변경하지 않았다.
   `git diff --check` 통과. 작업 시작 시 존재하던 사용자 변경은 유지했다.

16. Sealed holdout
   Bundle 64개 파일 hash와 first-run 관련 51개 파일 SHA-256/permission/flags가 동일하다.
   `protected-before.json`, `protected-after.json`, `integrity.json`으로 대조한다.
   V1 재실행·재채점·Gold 변경·first-run artifact 수정은 없다.

17. DB
   Read-only docker status에서 PostgreSQL Exited (0). Live DB hash NOT_VERIFIED.
   DB write/migration, service 재기동, production OCR/embedding/LLM 호출은 없다.

18. 미지원
   Merged/multi-level unit 영역의 명시적 child mapping, parent declaration override,
   footnote modifier의 원격 범위, 다른 page/table의 단위 상속, 자유 문장의 복합 scope,
   임의 currency/scale 변환은 지원하지 않는다. 관계를 추정하여 complete로 만들지 않는다.

19. 다음 후보
   명시적인 parent/child unit scope partition과 exclusion proof, merged unit header의
   column group membership, 각주 modifier의 value range proof를 독립 fixture로 확장한다.
   다음 실험도 v1 first-run과 분리하며 live DB 검증은 서비스가 승인된 시점에 별도 수행한다.
