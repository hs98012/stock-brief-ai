# Shared context / metric row ownership

## 변경 전 추적과 invariant

| 관계 | 기존 표현 / 검증 위치 |
|---|---|
| Source span | `layout_tables.source_span`: 원문 offset/quote/bbox/source. `unit_validation.located`로 실제 observation 대조 |
| Structured cell | `structured_cells._cell_topology`: cell token membership, row_groups, header/value column 및 primitive 생성 |
| Merged context | `_association`: `merged_row_membership_unverified`인 왼쪽 context 후보의 horizontal continuity |
| Context → metric | `metric_context_ownership`: 후보 수가 1이 아니면 `merged_context_multiple_metric_rows`/`merged_context_metric_not_unique`로 일괄 HOLD |
| Row grouping | `row_groups`: tall context가 마지막 child baseline과 aligned이면 peer로 들어가 topology conflict 가능 |
| Metric/unit/period/value | `_association`, ownership, `validate_unit`에서 source uniqueness·row baseline·column intersection 검증 |
| Primitive graph | `primitive_graph._same_label`/`relation`: 같은 metric, row geometry, ownership_id, unit/facet에서만 기간 비교 |
| Query requirement | `evidence_requirements.fact_requirement_match`: metric modifier·entity·period·unit·comparison 조건 |
| Evidence bundle | `evidence_bundle._fact_spans`: unit 및 primitive/graph 재검증. `_pack_for_document`: requirement별 유효 후보 선택 |

변경 전 invariant는 context당 metric 하나였다. 변경 후 context membership은 1:N, metric row ownership은 unit/value에 대해 유일하다. period header는 여러 row에서 공유하되 각 value와 column 연관을 따로 검증한다. 동일 unit을 다른 row가 차용하거나 동일 value를 복수 row에 승인할 수 없다. context 승인 자체는 coverage가 아니다.

## 계약과 격리

`metric_context_ownership.context_membership`은 `approved`, `context_id`, `context_bbox`, `members`, `context_spans`, `status`, `checks`, `rejection_reason`을 가진다. 각 member는 실제 `metric_span`, 관측 `row_bbox`, `metric_ownership_id`를 보존한다. top-level `ownership_id`는 선택한 metric member의 ID다. 같은 scope는 context_id를 공유하고 row마다 ownership_id가 다르다. DB migration이나 새 저장 테이블은 없다.

membership은 원문/cell unique ownership, containment, continuity, 분리된 row boundary와 관측 topology를 검증한다. context literal label을 모든 child row baseline에 반복할 필요는 없다. 단일 metric context의 기존 anchor baseline 검증은 유지한다. shared parent cell은 child row grouping의 peer가 아니다.

개별 chain은 unit/value가 선택 metric baseline에만 속하는지, period/header와 value column이 일치하는지, period 후보와 해당 row/column value가 유일한지 검사한다. source가 중복 cell/table에 속하면 거절한다. source/geometry는 원문 관측값으로 재검증하고 shared proof 삭제/변조도 거절한다. graph는 같은 context 및 같은 row ownership 사이에서만 비교한다.

query target은 전체 membership의 literal metric 후보에서 유일해야 한다. sibling downstream이 탈락해도 같은 이름의 다른 row는 ambiguity로 남는다. comparison의 두 primitive 및 comparison cell은 같은 ownership이어야 한다. evidence pack이 context 전체를 수치 evidence로 승인하지 않으며 context literal span 외에는 선택 row chain만 포함한다.

상태는 `shared_metric_context_verified`, `shared_context_metric_row_ambiguous`, `shared_context_metric_topology_conflict`, `shared_context_value_ownership_conflict`, `shared_context_query_metric_ambiguous`, `shared_context_metric_chain_ambiguous`와 기존 context period/chain 오류를 사용한다. shared status는 membership 승인이지 전체 query PASS가 아니다.

## 테스트 변경

새 shared-context 테스트는 topology 있음/없음, 2개 metric의 2기간 chain, row별 graph edge, target-only 비교 및 단일 기간 pack을 검증한다. unit/value 차용, 동일 value source 공유, 중복 value/cell/unit source ownership, 겹친 metric row, target 미지정, 귀속 불명 value, period ambiguity, mixed comparison, 동일 이름의 두 row, sibling chain 탈락, shared proof 삭제, owner ID 변조를 거절한다.

기존 ownership 테스트 함수들은 유지한다. 새 계약과 정면 충돌하는 “두 분리 metric이면 무조건 HOLD” expectation과 실제 현대차 primitive blanket HOLD expectation만 membership/primitive 승인으로 교체한다. coverage_complete=false는 두 primitive 승인 assertion에서도 유지한다. 나머지 geometry/ownership/column/unit 거절 테스트는 유지한다.

최종 검증·현대차 상세 chain·회귀·DB hash 결과는 `evals/shared-context-reviewed.json` 및 아래 결과 기록을 참조한다.

## 최종 보고 (요청 순서)

1. **변경 파일**: production `structured_cells.py`, `primitive_graph.py`, `evidence_requirements.py`, `evidence_bundle.py`; tests `test_shared_metric_context.py`, `test_metric_context_ownership.py`, `test_row_association.py`; 계약 `api-contract.md`, `acceptance.md`, `qa-rules.md`; 이 문서와 `evals/shared-context-reviewed.json`. raw replay/검증 로그는 `evals/results/paddle/shared-context-*20261007*`에 저장했다. 기존 사용자 변경은 보존했다.
2. **기존 1:1 가정**: `metric_context_ownership`의 후보 1개 검사/개별 baseline context anchor, `row_groups`의 merged parent를 child peer로 취급하는 동작. graph의 row ownership 일치 조건은 유지하되 context membership을 별도로 검사한다.
3. **새 데이터 모델/계약**: shared `context_id` + literal member 목록 + 개별 `metric_ownership_id`/`ownership_id`. 저장은 기존 primitive JSON metadata를 사용한다. DB 모델/migration 변경 없음.
4. **membership vs ownership**: 하나의 context가 여러 metric row를 포함하는 것은 허용한다. unit/value가 두 row에 귀속되거나 row를 유일하게 고를 수 없으면 HOLD한다. period header는 공유 가능하지만 각 value의 column과 따로 연결한다.
5. **chain isolation**: source/cell uniqueness, 분리된 row bounds, 기존 baseline/column threshold, 유일한 period 및 row/column value, row별 unit/value owner, graph 양쪽 owner, comparison cell 재검증. shared proof 누락/변조와 같은 metric 이름의 복수 후보도 거절한다.
6. **테스트**: 새 shared-context 20 cases 모두 통과. topology 있음/없음, 분리 chain, target-only 비교 및 단일 기간 pack PASS. unit/value 차용·동일 source 공유·중복 value/cell·row overlap·미지정 metric·귀속 불명·period ambiguity·mixed comparison·동일 이름/탈락 sibling·proof 삭제·owner 변조 HOLD. 기존 blanket HOLD 두 expectation만 새 invariant에 맞게 갱신했으며 기존 ownership/row/column 검사는 유지했다. 초기 RED: 8 실패/7 통과; 추가 우회 테스트 RED: 2 실패/18 통과; 최종 shared 20 통과.
7. **현대차 세부 chain**: native shared context `수익성지표 (연결 기준)`에서 metric 두 row가 독립적으로 검증됐다. `영업이익률3)`의 `%`, `2022→6.9`, `2023→9.3`는 유일하며 unit validator도 승인했다. `순이익률3)`의 `2022→5.6`, `2023→7.5`는 다른 ownership이다. 두 row의 native graph 총 6 nodes/6 edges는 모두 같은 row ownership 안에서만 연결된다. source span/원문 bbox와 상세 checks는 reviewed JSON에 보존했다.
8. **현대차 challenge 전/후**: 전 `merged_context_multiple_metric_rows`, coverage=false. 후 membership/primitive 승인, query metric mismatch로 coverage=false. 질문의 `영업이익률`은 원문의 `영업이익률3)`과 현재 literal matcher에서 일치하지 않는다. annotation을 임의 제거하지 않았으며 target 미승인 상태에서 comparison도 생성하지 않는다. selected pack은 전/후 동일하다.
9. **회귀**: 개발 combined 12/12(후보 10/10 + 고정 control 2/2), POSCO 1/1, 삼성 coverage=false/false-complete 0, SK HOLD 유지. 현대차·신용보증기금·기아·SK를 포함해 fixed regression 4개와 challenge 5개의 selected pack이 기존 artifact와 exact JSON equality다. 기아 automatic strict=false는 그대로이며 기존 manual strict review를 유지한다. 전체 challenge strict 1/5, false-complete 0.
10. **전체 검증**: targeted shared/ownership/row/column/graph/requirement/unit 117 passed. `./scripts/check.sh`: backend 379 passed/1 skipped, frontend 7 passed, lint/build PASS. skip은 optional `google.genai` 미설치다. offline replay는 원문 observation 및 고정 hybrid rank를 재사용했고 검색/OCR/embedding/LLM은 실행하지 않았다. 두 active control의 점수는 frozen baseline 재검증이며 live 검색 검증은 아니다. 사전 replay는 편집 중 source-hash guard로 폐기했으며, 실제 전/후 비교 baseline은 초기 production snapshot과 전체 module hash가 일치하는 기존 immutable artifact를 사용했다. 새 replay는 source/production hash guards와 development gate를 모두 통과했다.
11. **hardcoding/diff**: production 4개 모듈에서 회사명, 대상 metric 이름, 알려진 bbox, challenge ID, 문서명/expected answer shortcut 없음. row/column threshold 함수 AST와 unit validator 및 OCR/search/embedding/generation source hash 불변. `git diff --check` 및 이번 변경의 added-line whitespace 검사 PASS.
12. **DB/hash 불변**: REPEATABLE READ READ ONLY 트랜잭션의 live 전/후 SHA-256이 documents(10), pages(75), chunks(231), analysis_runs(311), page_extractions(0)에서 모두 일치한다. exact hash는 reviewed JSON 및 active-before/after artifact에 저장했다. migration/reprocessing/OCR/embedding/LLM/active revision mutation 없음.
13. **아직 검증할 수 없는 항목**: 주석이 붙은 metric과 질문의 비주석 metric 사이의 동치성은 확인할 수 없습니다. shared membership과 물리적 chain 승인만으로 이 query coverage를 승인할 수 없다. scope 문구 자체의 query 의미 연결을 새로 추론하지 않는다. active hash 불변은 live table 내용을 검증한 것이며 새 검색 품질 점수는 아니다.
14. **다음 작업 후보**: 원문 기반 일반 annotation/footnote 모델 및 metric 동치 검증(동일 이름 충돌/다른 주석/false-complete negative tests 포함); 질문이 scope를 명시할 때 원문 기반 shared-context entity matching. 이번 작업에서 matcher나 unit 규칙을 완화하지 않았다.

## 명시적 답변

| 질문 | 판정 |
|---|---|
| 현대차 shared context 자체는 검증되었는가? | 예. native geometry/topology/source로 두 row의 membership 승인 |
| `영업이익률3)` metric row는 독립적으로 검증되었는가? | 예. sibling과 분리된 row ownership 승인 |
| `%`는 해당 row에 유일하게 귀속되는가? | 예. native literal unit row association 및 기존 validator 승인 |
| `2022→6.9`, `2023→9.3` chain은 각각 유일한가? | 예. period column 및 row/value intersection 검증 |
| `순이익률3)` row 값과 섞일 가능성은 제거되었는가? | 관측된 native chain과 graph/pack 검증 경로에서 차단. sibling은 별도 ownership이며 cross-row edge 없음 |
| 따라서 coverage_complete=true가 정당화되는가? | 아니오. query metric 동치성이 미검증되어 HOLD/false 유지 |
