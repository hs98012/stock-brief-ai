# Query reporting scope 구현 보고 — 2026-10-08

scope 계약은 구현했으며 현대차는 HOLD를 유지한다. Scope-local metric/period/value 증명은 통과하지만 frozen chunk가 필수 원문 span을 덮지 못하므로 coverage_complete=false다. 회사/문서 예외나 index 재작성으로 PASS시키지 않았다.

## 1. 변경 파일

- `backend/app/query_scope.py`: query literal proof, source membership 재검증, scope-local selection.
- `backend/app/evidence_requirements.py`: metric과 독립적인 scope requirement와 match audit.
- `backend/app/metric_annotations.py`: source scope/collision audit, 명시 scope에 한정한 collision authorization.
- `backend/app/evidence_bundle.py`: question binding 및 requirement를 전달하는 pack 재검증.
- `backend/tests/test_query_scope.py`: 46 positive/negative/tampering tests.
- `scripts/audit_query_scope.py`: 기존 observation만 사용하는 offline proof audit.
- `api-contract.md`, `acceptance.md`, `qa-rules.md`: 지원 범위/승인/QA 계약.
- 이 보고서와 `evals/results/paddle/query-scope-*` 검증 artifact/log/diff.

시작 시 다수의 사용자 변경 및 untracked 파일이 있었으며 이를 보존했다. 이번 변경만의 diff는 `query-scope-changes-20261008.diff`다. DB/model migration은 추가하지 않았다.

## 2. 기존 scope 정보 손실 지점

query → `table_requirements()`에서 metric 앞 prefix를 마지막 period 뒤로 절단 → `연결 기준` 유실 → scope 없는 requirement → `metric_identity()` annotation 검증/표 전체 canonical collision → `query_label()` 거부 → 비교 후보/pack 누락 → HOLD.

Requirement에는 scope 필드가 없었다. Canonical exact matching과 이후 normalized metric matching이 있었지만 query scope matching은 없었다. Shared context는 source cell 추출/ownership에서 먼저 검증되었고 requirement matching에서도 같은 context의 metric row 유일성과 비교 chain을 검사했다. Query scope selector로 쓰이지는 않았다. Collision은 annotation identity 생성 단계에서 전체 table label을 대상으로 기록되고 annotation 승인 단계에서 거부됐다. 구현 전 이 경로를 사용자에게 보고했다.

## 3. Query scope requirement 모델

`scope: consolidated | separate | null`, `scope_proof: [{char_start,char_end,quote,scope}]`, `scope_ambiguous: bool`. Offsets는 requirement의 `clause` 기준이다. Metric identity, entity, period와 분리했다. Proof를 clause에서 재추출해 비교하고 evidence bundle에서는 제출된 question의 해당 clause scope와도 비교한다.

지원 literal은 연결/consolidated, 별도/개별/separate/standalone의 6개다. 개별/standalone은 별도 회계 범주로 정규화한다. 기존 structured parser가 처리하는 query에서 scope가 날짜 앞 또는 metric 앞에 있는 표현, optional `기준`을 지원한다. 한 clause에 연결·별도를 동시에 요구하는 multi-scope parsing은 지원하지 않고 HOLD한다. 자연어 parser/metric vocabulary를 확장하지 않았다.

## 4. Source scope membership 모델

`metric_identity.source_scope = {scope,membership}`와 모든 `scope_metrics[].source_scope`에 원문 context span/context ID/metric ownership ID/member row bbox를 보존한다. Literal scope 단어는 후보를 지명할 뿐이며, 기존 `context_membership()`/`row_groups()` 검증을 재사용한다. Native merged cell에 rowspan이 없어도 row-group geometry 계약으로 context와 metric을 구분한다. Fragmented unit span도 기존 unit helper로 후보에서 제외한다.

선택된 fact의 승인된 `metric_context_ownership`과 rederived membership/독립 ownership ID가 일치해야 한다. Publication에서는 identity 전체를 page로부터 다시 계산해 비교한다. Caller metadata만으로 scope를 승인하지 않는다. 저장 observation이나 DB schema를 변경하지 않는다.

## 5. Candidate selection 순서

원문 primitive 검증 → annotation authorization/canonical label → 전체 collision audit 보존 → canonical metric match → query literal scope/source membership match → scope-local row 유일성 → 선택 row의 기존 ownership/unit/period/value/column/source/cell 검증 → 같은 owner graph comparison → chunk coverage와 evidence pack 검증.

이미 source extractor가 승인한 primitive도 pack에서 원문으로 재검증한다. RRF rank가 scope/ownership ambiguity를 해소하지 않는다.

## 6. Annotation → canonical → scope filtering

`영업이익률3)`의 verified footnote만 `영업이익률`을 노출한다. `canonical_metric_collision` 및 모든 collision spans는 identity에 남긴다. 명시 query scope와 verified source membership으로 유일 후보임을 증명했을 때만 그 requirement에 대한 collision 거부를 해소한다. Scope 없는 기존 annotation validator 호출은 계속 collision을 거부한다. Annotation proof를 삭제하면 scope만으로 승인하지 못한다.

## 7. Scope-local uniqueness 규칙

전체 table의 canonical 후보를 수집하고, 명시 scope 안의 후보가 정확히 하나일 때만 승인 후보로 남긴다. 같은 scope의 2개 후보, source membership을 알 수 없는 경쟁 후보, scope 미지정 collision, scope mismatch는 HOLD한다. 경쟁 row의 downstream chain이 실패해도 canonical 후보 audit에서 삭제하지 않는다.

Reason: `query_scope_proof_invalid`, `query_scope_ambiguous`, `source_scope_unverified`, `source_scope_membership_invalid`, `metric_scope_mismatch`, `metric_scope_ambiguous`. 기존 annotation/ownership/unit error taxonomy도 유지했다.

## 8. Positive/negative/tampering tests

Scope tests 46개. 6 literal × 기준 유무 parser proof, 날짜 앞/metric 인접 표현, 연결·별도 pack 분리, verified annotation 이후 scope-local 승인, annotation 없는 canonical collision, native merged cell의 missing rowspan을 검증한다.

Scope 없음/충돌/mismatch, 같은 scope의 중복 row, literal만 있고 membership 없음, unsafe source span, annotation proof 삭제는 HOLD. Query scope/proof 삭제·변조, 일관되게 위조된 parser clause, source context 변경+hash 갱신, source span 삭제, membership/context ID/ownership ID 변조, period/value 변경, opposite-scope comparison 삽입, 동일 value span 재소유를 검증했다. 새 query로 별도를 요구하는 것과 이전 연결 evidence의 query binding을 위조하는 것은 구분된다.

Annotation/shared-context/ownership/row/column/graph를 합친 targeted suite는 166 passed.

## 9. 현대차 전체 collision 후보

동일 native table의 canonical collision은 2개다. 단위는 모두 원문 `%`.

| Scope | Raw → canonical | Row | 2021 / 2022 / 2023 | Context ID | Metric owner |
|---|---|---:|---|---|---|
| 연결 | 영업이익률3) → 영업이익률 | 17 | 5.6 / 6.9 / 9.3 | a5d310833ef4cb375ed99772 | e57298f7178d0603a4ea3a10 |
| 별도 | 영업이익률 → 영업이익률 | 19 | 1.2 / 4.3 / 8.5 | a405b86482c5e3b4d58e33d2 | 440b6c67984dd0cc2ea0af05 |

Audit는 같은 observation의 별도 paddle_structure raw 후보도 숨기지 않는다(char_start=2830, source scope 미검증). 이것은 위 native table의 두 canonical row와 구분한 별도 source 관측이며 승인 후보가 아니다.

## 10. 현대차 query scope

실제 frozen query: `표의 연결 기준 2022년과 2023년 영업이익률을 비교해줘.`

`연결` literal `[3,5)`를 `scope=consolidated`와 함께 두 period requirement에 보존한다. 현대차는 offline fixture이며 live documents/active extraction으로 승격하지 않았다.

## 11. Scope 적용 후 남은 후보

Native table에서 연결/영업이익률3) row 17 하나. 별도 row 19는 mismatch로 제외한다. 비교 fact는 2022→2023, 2023→2022의 두 방향이며 metric row가 두 개라는 의미가 아니다. `영업이익률3)` annotation은 verified이고 canonical label은 `영업이익률`이다.

## 12. Period/value ownership 결과

연결 row의 unit은 `%` 하나이고 2022=6.9, 2023=9.3 chain이 유일하다. 두 방향의 graph/annotation/원문 pack-span validator가 모두 true다. 두 primitive owner는 모두 `e57298f7178d0603a4ea3a10`. 별도 4.3/8.5 값을 비교 primitive에 포함하지 않는다.

## 13. Evidence pack 격리 결과

일반 positive fixture에서는 선택 scope의 primitive/value만 pack에 들어가고 반대 scope 삽입은 거부된다. 현대차의 비교 후보에도 연결 값만 있다. 그러나 frozen admitted chunk가 native metric/value/context/annotation footer spans를 덮지 못한다. `verified_table_candidate_count=0`, selected pack은 `[]`다. Span의 원문/geometry 유효성과 indexed chunk coverage는 서로 다른 조건이며 둘 다 요구한다. Empty pack을 PASS 증거로 주장하지 않는다.

## 14. 현대차 challenge 전/후

이전 annotation 단계 HOLD → 이번 HOLD. Scope-local selection과 원문 comparison 검증은 새로 통과하지만 frozen chunk coverage가 실패한다. `coverage_complete=false`, strict_pass=false. 검색/chunk admission/OCR을 수정해 강제로 PASS시키지 않았다.

## 15. 개발/POSCO/삼성/SK 회귀

개발 combined comparison recall 12/12 = candidate 10/10 + frozen active control 2/2. Classic-only recall은 이전과 동일한 11/12이며 12/12로 혼동하지 않는다. Compound coverage 1/1, POSCO fixed regression 1/1, 삼성 challenge false-complete 0, SK HOLD. 기아는 coverage=true지만 strict_pass=false인 manual strict review 상태를 유지한다.

이전 `metric-annotation-final-20261008.json`과 개발/fixed/challenge selected pack 20건 전체가 JSON 동등하다. Active control 두 건은 immutable baseline replay이며 live 재검색 결과가 아니다.

## 16. 전체 테스트 결과

- `./scripts/check.sh`: backend 463 passed / 1 skipped; frontend 7 passed; lint(0 warnings)와 production build 통과.
- 마지막 native missing-rowspan test를 추가한 뒤 backend 전체 재실행: **464 passed / 1 skipped**.
- 최종 targeted scope/annotation/shared/ownership/row/column/graph: **166 passed** (scope 46개).
- Backend 17 warnings는 기존 FastAPI/Swig deprecation이며 테스트 실패는 없다.
- `scripts/audit_unit_precision.py --row-association`: frozen rank/observation regression 완료, OCR/embedding/LLM/DB 호출 없음.

## 17. Hardcoding / diff

변경 production modules에서 현대차/hyundai/005380/6.9/9.3/4.3/8.5/특정 row selector 없음. Bounded 6 reporting literal만 지원한다. `git diff --check` 통과. Current baseline 대비 `structured_cells.py`, `unit_validation.py`, `search.py`, `primitive_graph.py`, `chunking.py`, `embedding_service.py`, `pdf_pipeline.py`, `paddle_structure.py` hash가 모두 같다. Geometry threshold/unit validator/검색/RRF/OCR/embedding/LLM 변경 없음.

## 18. DB hash / 서비스 상태

REPEATABLE READ / READ ONLY transaction으로 SELECT 후 rollback했다. 작업 전=작업 후=기존 shared-context baseline. 아래 다섯 table의 row JSON/count만 검증한 것이며 DB 전체 파일/WAL 동일성을 뜻하지 않는다.

| Table | Count | SHA-256 |
|---|---:|---|
| documents | 10 | 90a528749fa287d8614fe5383fa6c8a37f67498e778206108d5796860565f8b4 |
| pages | 75 | 1cf7866151671415c87cc90b8a439c48969ebdc7a95611ba289fc041179cb575 |
| chunks | 231 | bce2ec67ef0b99dca798891b76998fedc9cbbe969c01a749906619198033bf0e |
| analysis_runs | 311 | ce0bab08903d1fafb004361a493d67ff41ae332ca93563faf92715d5b70810fd |
| page_extractions | 0 | 4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945 |

Backend/postgres/ocr-worker running healthy, frontend running(healthcheck 없음). 서비스 재시작/기동, migration, active revision 변경, DB mutation, OCR 재처리, embedding 생성, LLM 호출 없음. 실행 중 서비스가 수정 코드를 재로딩했는지는 확인할 수 없습니다.

## 19. 남은 ambiguity / 제한

Scope/row/value ambiguity는 해당 native table에서 해소됐다. End-to-end evidence coverage는 frozen chunk admission 때문에 부족하다. 별도 source의 paddle raw row scope는 미검증이다. 원본 PDF 시각 재검증은 확인할 수 없습니다. 이번 증명은 PDF hash에 묶인 기존 native words/bbox/cells와 offline fixture에 한정된다. Multi-scope clause/인접하지 않은 기타 reporting context 표현은 자동 추론하지 않는다.

## 20. 다음 작업 후보

별도 작업으로 frozen admitted spans와 native metric/context/value/footnote span의 index coverage 차이를 read-only 조사한다. Scope 계약과 index admission 계약을 구분하고 재처리/DB 변경 없이 먼저 재현·원인 증거를 확보한다. 이번 작업에서는 frozen index를 변경하지 않았다.

## 필수 질문 답변

1. Query에 연결/별도 scope가 실제로 있는가? **예. 연결 기준**이 있다.
2. Parser가 손실 없이 보존하는가? **예. scope/proof/offset을 두 requirement에 보존**한다.
3. Source scope는 원문/구조 증거로 확인되는가? **예. native context literal/membership/geometry/독립 owner로 검증**한다. 원본 PDF 시각 검증은 확인할 수 없습니다.
4. Canonical collision은 전체 table에 있는가? **예. 연결 row 17과 별도 row 19**, audit에 보존한다.
5. Query scope를 적용하면 정확히 하나인가? **예. 해당 native table의 연결 row 17 하나**다.
6. 선택 candidate의 period/value chain은 유일한가? **예. 2022 6.9% → 2023 9.3%, 같은 metric owner**다.
7. 반대 scope 값이 pack에 들어갈 가능성은 제거됐는가? **현재 승인 경로에서 scope/owner/graph 재검증으로 거부**한다. Positive/혼입 tests가 통과했고 현대차 비교 후보에 별도 값은 없다. 실제 현대차 pack은 비어 있다.
8. 따라서 coverage_complete=true가 정당화되는가? **아니오. frozen chunk coverage가 실패하므로 false/HOLD**가 정당하다.

주요 검증 파일: `query-scope-reviewed-20261008.json`(회귀/pack 비교), `query-scope-hyundai-final-20261008.json`(query/source/collision/chain/missing chunks), `query-scope-final-20261008.json`(전체 frozen replay), `query-scope-active-{before,after}-20261008.json`(DB), `query-scope-{check,backend,targeted}-20261008.log`(검사).
