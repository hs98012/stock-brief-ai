# Source-Owned Scope Binding Stage 3 검증 보고

새 문서의 명시적 source 구조만으로 scope ownership을 증명하는 `source-owned-scope-v1`을 추가했다. 특정 기업·값·bbox 예외, 검색/geometry threshold 변경은 없다. 기존 관측은 원래 parser 계약으로 검증하며 새 scope 계약으로 재인증하지 않는다.

## 1. 변경 파일

- `backend/app/scope_binding.py`: literal 선언, 구조적 membership, parent/child, competing row, query matching, namespace 계약.
- `query_scope.py`: reporting/region 차원과 scope matching 연결.
- `structured_cells.py`: v6 cell scope proof 필수, 원문 재구성 및 버전별 계약.
- `metric_annotations.py`: v6 scope 토큰 분리, namespace, 검증된 scope-local canonical uniqueness.
- `index_admission.py`: scope 및 boundary dependency 보존.
- `evidence_bundle.py`, `extraction_provenance.py`: namespace/source proof 및 scoped fallback 검증.
- `fact_fusion.py`: 새 parser `fact-fusion-paddle-v6`.
- `period_binding.py`, `unit_validation.py`: v4/v5 기존 필수 proof 검사 보존.
- `backend/tests/test_scope_binding.py`: 독립 40개 테스트.
- `backend/tests/test_period_binding.py`: legacy fixture에서 additive scope metadata 제거.
- `api-contract.md`, `acceptance.md`, `qa-rules.md`: 계약/검수 기준.
- `evals/results/scope-binding-stage3-20261012/`: 검증 artifact와 audit 전용 replay 도구.

변경 전의 광범위한 기존 working tree 수정은 보존했다. 이번 작업은 commit/DB migration을 만들지 않았다.

## 2. 기존 실패 원인

기존 query scope는 reporting literal과 merged context membership 중심이었다. Inline row, 독립 scope column, section interval, 다차원 parent/child의 유일한 관계를 생성하는 일반 proof가 없었다. 근접한 header나 상위 scope를 임의 상속하면 competing metric 및 cross-scope contamination을 놓칠 수 있었다.

기존 annotation proof의 `scope_metrics`에는 `(연결` 같은 조각도 포함돼 있었다. 새 scope token 분리를 legacy에 적용하면 정확한 source rederivation이 달라졌다. 이 분리는 v6에만 적용하고, legacy annotation/period/unit/ownership 검증은 그대로 유지한다.

## 3. 새 계약과 ownership

각 cell fact는 literal scope span/bbox, 원문 SHA-256, page/table/row/column identity, metric/value span 및 cell, row group, context membership, ownership/context ID, 독립 period/unit proof를 보존한다. 원문에서 재구성한 proof와 일치해야 한다. Annotation 단계에서 owning document/page namespace를 추가하며 외부 namespace를 거절한다.

Scope가 없는 구조도 scope 선언이 실제로 없다는 판정과 competing metric 목록을 보존한다. 선언의 source proof가 없으면 unscoped로 승격하지 않는다. 기존 membership/ownership ID가 검증돼 있으면 재사용한다.

## 4. 지원 구조

| 구조 | 승인에 필요한 source proof |
|---|---|
| Metric row | 같은 value row의 metric cell 안에 독립적으로 관측된 scope token |
| Scope column | 왼쪽의 독립 cell, 일치하는 row group과 bbox membership |
| Section header | full-width colspan, 명시적 row topology, 다음 section 종료 boundary |
| Merged context | 기존 검증된 context source spans와 독립 metric row membership |
| Parent/child | 독립 scope 차원, adjacent columns, rowspan 및 bbox containment |
| 동일 metric의 복수 scope | 전체 competing metric 목록과 query scope 내 유일한 row |

Native table이 rowspan을 생략했어도 기존 shared-context proof가 독립 row membership을 증명하면 사용할 수 있다. 앞선 context 종료도 기존 membership validator로 검증하며 관련 literal boundary를 dependency에 보존한다.

## 5. Parent/child 증명

같은 차원의 복수 선언은 승인하지 않는다. 인접 column 경계, child row interval의 parent rowspan 내 포함, bbox 포함 관계를 모두 검증한다. Section parent는 full-width interval로 제한한다. 단순히 상위 header가 먼저 나왔다는 이유로 상속하지 않는다. Parent topology 누락·변조는 HOLD다.

## 6. Query/source matching

Reporting(연결/별도)과 region(국내/해외)을 독립 차원으로 비교한다. `연결 국내`는 두 membership이 모두 증명된 fact만 선택한다. 같은 차원의 복수 query, mismatch, scope 없는 query의 서로 다른 scope 후보, scope 내 중복 metric row는 HOLD다. Parent만 질의해서 동일 metric의 여러 child가 남으면 HOLD다. 미검증 competing row도 제외해서 유일성을 꾸미지 않는다.

## 7. Period/unit 통합

Scope 승인 전에 period 및 unit binding이 승인돼야 한다. Proof 안에 이 관계를 보존하고, 기존 source rederivation·unit validator·composite dependency·annotation validator를 계속 실행한다. v4 period/v5 unit의 필수 proof 조건은 v6에서도 유지한다. Scope만으로 coverage/strict를 승인하지 않는다.

## 8. Graph/admission/pack 전달

`Metric + Scope + Period + Unit + Value`의 source proof는 primitive graph node에 남는다. Admission group은 scope, ownership 및 literal scope/boundary dependency를 보존한다. Physical chunk는 정확한 원문 slice다. 기존 searchable anchor를 통해 candidate/selected pack으로 전달하고 pack 단계에서 source proof를 재검증한다. Comparison은 두 leaf의 동일 scope path와 각 period/unit proof가 필요하다.

## 9. Positive/negative 테스트

40개 독립 scope 테스트가 추가됐다. Positive는 다섯 source 구조, query에 따른 유일 선택, 두 scoped comparison, section dependency와 legacy annotation 보존을 검사한다.

Negative는 scope 후보 충돌, query 미명시/mismatch, parent proof 없음, cross-scope value/leaf, span 삭제·변조, context/ownership ID 변조, 같은 scope 중복 metric, 누락된 value의 competing row, period/unit 미검증, foreign table/document/page namespace, scope proof 삭제, scoped native fallback, 부정확한 row geometry, section colspan 삭제, unsupported header 및 expired-context proof 변조를 검사한다.

Fixture는 synthetic임을 명시하며 sealed 기업·정답·값·bbox·gold를 읽지 않는다.

## 10. Synthetic E2E

`synthetic-e2e.json`: 독립 positive 7/7, query scope 미명시 HOLD 5/5, mismatch HOLD 5/5. 다섯 구조의 graph/admission/chunk/pack와 두 comparison의 양쪽 period/unit/scope proof를 저장했다. 서비스·OCR·embedding·LLM 호출은 없다.

## 11. False-complete 방어

새 v6 proof 누락은 거절한다. Unsafe/missing source, competing row, canonical collision, scope mismatch, cross-scope comparison, period/unit 미검증은 coverage를 막는다. Unresolved scoped native fallback은 새 계약을 우회하지 못한다. Legacy observation은 기존 버전과 모든 기존 source validator를 유지한다.

## 12. 기존 challenge regression

최종 `regression-summary.json`: 개발 12/12, POSCO 1/1, selected pack 20/20 동일, 현대차·삼성 offline PASS pack 17/17 동일, 기아 manual REVIEW, SK·Counts HOLD, review-aware false-complete 0. 기존 frozen observations/ranks를 재검증하며 selected pack 전체 JSON을 비교한다. 기아 manual REVIEW와 automatic strict/coverage를 구분하고 review-aware false-complete를 계산한다. Audit 전용 memoization은 전체 source preimage와 계약 옵션을 key로 사용하고 결과를 deep-copy한다. Mutable audit sink는 cache를 우회한다. Production validator, ranking 또는 threshold를 patch하지 않는다.

## 13. 전체 검사

- Scope/period/unit/shared-context/query-scope/admission/component/ownership targeted: 223 passed.
- Backend 전체: 648 passed / 1 skipped.
- Frontend: 7 passed.
- Frontend lint 및 production build: PASS.
- 필수 `./scripts/check.sh`: PASS.
- `git diff --check`: PASS.

## 14. Hardcoding/diff

기업명/값/좌표 기반 예외를 추가하지 않았다. `source-audit.json`은 변경 전후 production hash를 기록한다. Search, embedding, generation, primitive graph, unit binding/component 모듈은 작업 시작 시 hash와 동일하다. BM25/vector/RRF, geometry threshold, LLM 설정 및 금액 변환은 바꾸지 않았다.

## 15. Holdout v1 무결성

Sealed bundle 64개 파일은 manifest hash와 일치한다. Protected first-run/manifest 등 51개 파일의 SHA-256/mode/immutable flags는 전후 동일하다. v1 실행·재채점·gold/first-run artifact 수정은 하지 않았다. `integrity.json`, `protected-before.json`, `protected-after.json` 참조.

## 16. DB 상태

PostgreSQL `Exited (0)`, live DB hash `NOT_VERIFIED`. DB 재기동/write/migration/active revision 변경, OCR 재처리, embedding 생성 및 LLM 호출은 없다. 기존 offline vector ranks/artifacts만 재사용했다.

## 17. 미지원 구조

- 같은 OCR token 안에서 scope/metric을 분리하려고 bbox를 추정해야 하는 구조.
- 불완전한 colspan/rowspan 또는 독립 membership을 증명할 수 없는 remote header.
- 인접 column/포함 관계가 없는 parent/child, 다른 표·페이지로 이어지는 상속.
- 등록되지 않은 scope vocabulary, 한 cell의 복합 선언을 topology 없이 계층으로 해석하는 구조.
- Footnote나 자연어 설명만으로 scope를 추정해야 하는 구조.

이 구조는 HOLD이며 기존 archived observation을 새 scope contract 성공으로 표시하지 않는다.

## 18. 다음 개발 후보

명시적 scope definition/footnote 및 table continuation relation의 독립 source proof 계약. 현재 문서에 없는 관계를 추정하지 않고 boundary/identity proof부터 추가하는 것이 다음 단계다.
