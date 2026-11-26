# Sealed Holdout v1 — First-run Failure Attribution Audit

0/10 evidence coverage의 주된 원인은 **실제 pipeline의 proof 연결 실패**다. Scorer 계약 문제도 별도로 존재하지만 빈 pack/HOLD는 scoring 전에 결정되었다. 이번 감사에서 prediction/scoring/production/gold는 변경하지 않았고 최초 평가 또는 scoring을 재실행하지 않았다.

1. **First-run 무결성**: ID `7db3bde0-1c92-4c7c-b0c2-f9a73c7db505`, config `2ebceaf80a38250dad3077d19b4ce773b653b12ad3380d99fbee55fd7acf2332`. Manifest·PDF/gold bytes·code/adapter·prediction inventory·scoring·기존 report/receipt hash PASS. 모든 기존 immutable flag를 유지했다. Before/after 근거는 별도 audit의 integrity-before/after.json에 저장했다.

2. **Scorer schema**: `prediction.status`는 실행 상태 HOLD/COMPLETE/ERROR이고 `fact.status`는 forecast/actual/provisional/unspecified다. `prediction.predict`는 coverage가 true인 경우만 COMPLETE로 저장하며 search DTO를 그대로 복사한다. `score_case`의 top-level HOLD 해석은 정상이다. `fact_check`는 gold.value_status를 candidate.value_status와 literal 비교하지만 production candidate는 status를 노출한다. Gold에는 forecast뿐 아니라 reported, reported_not_explicitly_final이 있어 단순 필드명 alias로도 의미 계약이 완성되지 않는다. Scope 및 estimate_version 표현도 명시적으로 검토해야 한다.

   | 구분 | 판정 |
   |---|---|
   | A. 이름만 다른 정상 계약 | 이름이 다른 것은 관측됨. 정상 adapter normalization 계약은 없음 |
   | B. 실제 top-level status 해석 오류 | 관측되지 않음: HOLD 15개가 그대로 HOLD |
   | C. 정상 evidence가 scorer에서 거절될 가능성 | 잘못된 field predicate상 가능. 이번 run에는 완전한 정상 pack이 없어 실제 완전한 정상 prediction의 오판 사례로 확정하지 않음 |
   | D. 점수와 무관한 표시 문제 | 아님: nested field는 strict/recall 조건에 직접 사용됨 |

   전체 retrieved positive fact candidate는 value_status를 갖지 않는다. Core metric/period/unit/value가 지정 page에서 일치하는 top-5 fact는 카카오02의 2개뿐이며 이 둘도 scope가 없으므로 schema mismatch 외의 실제 검증 실패가 남아 있다. Strict가 coverage aggregate에도 결합되지만 이번에는 coverage=true 자체가0이고 pack도 모두0이라 scorer 수정만으로 실제 coverage를 개선할 수 없다. 대체 점수는 계산하지 않았다.

3. **Cross-page proof**: NAVER01/02·셀트리온01/02의 7개 fact는 p1 scope와 p2 value를 연결해야 한다. 원문 scope/value token은 저장되어 있지만 pipeline의 source_memberships, dependency_groups, chunk ownership, verified source span 처리는 page-local이다. 승인된 cross-page ownership graph는 artifact에 없다. Scorer도 모든 proof.page가 fact.source_page여야 하고 모든 offset을 그 page.final_text에서 검증한다. 따라서 raw evidence의 존재와 approved dependency의 존재를 구분해야 한다. Pipeline 지원 부족과 scorer 표현 한계가 둘 다 있으며, 이미 검증된 cross-page pack이 scorer 때문에만 거절되었다고 주장하지 않는다. 문서·page·span·table/metric owner가 포함된 proof graph를 검증하는 별도 version 계약이 필요하다.

4. **Answerable 10개 최초 attribution**: 기존 broad taxonomy의 table/fact 8건을 period 4건·unit 4건으로 세분화하고 본문 period 실패 1건을 추가해 공통 period taxonomy는5건이다. 아래는 frozen 입력에서 확인한 predicate이지, 저장되지 않은 silent-continue의 역사적 실행 순서를 만들어 낸 로그가 아니다. Native/Paddle 및 fallback은 병렬 대안 경로다. 한 branch의 실패를 모든 branch의 유일 원인으로 단정하지 않는다.

   | 질문 | 최초 taxonomy | 최초 함수/판정 경계 |
   |---|---|---|
   | sh1-naver-01 | UNIT_ASSOCIATION_FAILED | `_cell_topology` | 
   | sh1-naver-02 | UNIT_ASSOCIATION_FAILED | `_cell_topology` | 
   | sh1-kakao-01 | PERIOD_VALUE_ASSOCIATION_FAILED | `_cell_topology` | 
   | sh1-kakao-02 | SCOPE_ASSOCIATION_FAILED | `source_memberships` | 
   | sh1-celltrion-01 | PERIOD_VALUE_ASSOCIATION_FAILED | `_cell_topology` | 
   | sh1-celltrion-02 | PERIOD_VALUE_ASSOCIATION_FAILED | `_cell_topology` | 
   | sh1-orion-01 | UNIT_ASSOCIATION_FAILED | `_cell_topology` | 
   | sh1-orion-02 | UNIT_ASSOCIATION_FAILED | `validate_unit` | 
   | sh1-kt-01 | PERIOD_VALUE_ASSOCIATION_FAILED | `_numeric` | 
   | sh1-kt-02 | PERIOD_VALUE_ASSOCIATION_FAILED | `_cell_topology` | 

   - `sh1-naver-01`: Native 통합 row는 len(labels)!=1. 분리된 Paddle topology에 native token을 대응시킨 경로는 금액 metric에 %를 선택하여 unit_compatible=false. OCR token 경로는 chosen unit 개수가1이 아니어서 제외된다. [함수](../backend/app/structured_cells.py:398)
   - `sh1-naver-02`: Native merged row에서 len(labels)!=1. 분리된 Paddle topology 경로는 native % 단위가 금액 metric과 충돌하고, OCR은 chosen unit 비유일/단위 header-column geometry 불일치로 제외된다. [함수](../backend/app/structured_cells.py:398)
   - `sh1-kakao-01`: Paddle 표는 존재하지만 기간이 첫 column의 data row에 있어 column>0, row<=1인 period parent 후보가 0개다. len(headers)<2에서 target primitive가 생성되지 않는다. [함수](../backend/app/structured_cells.py:398)
   - `sh1-kakao-02`: 원문 scope word 2개 모두 table containment >0.8을 만족하지 않는다. source_memberships가 source_scope ownership을 만들지 못하고 selection의 source_scope_unverified에서 후보가 거절된다. target primitive는 각 fact당2개 있으나 target dependency group은0개이며, 이 admission 손실의 별도 세부 predicate는 역사 로그가 없어 확정하지 않았다. [함수](../backend/app/query_scope.py:18)
   - `sh1-celltrion-01`: 실제 25년 2분기/연간 header는 PERIOD_CELL의 quarter/year literal fullmatch에 들어가지 않아 parent/header count=0. native/Paddle 모두 len(headers)<2. 신규/이전 facet이 확인된 primitive로 연결되지 않는다. [함수](../backend/app/structured_cells.py:398)
   - `sh1-celltrion-02`: 동일 target table의 한글 기간 header에서 parent/header count=0. GPM과 같은 core tuple가 다른 approved fact에 있어도 gold 지정 value source bbox의 target primitive는0개이므로 해당 proof로 승인하지 않는다. [함수](../backend/app/structured_cells.py:398)
   - `sh1-orion-01`: 표 topology/period는 있으나 native token 경로가 EPS에 % 단위를 붙여 compatibility=false. OCR 경로는 literal unit 후보가 유일하지 않아 primitive 생성 전 제외된다. [함수](../backend/app/structured_cells.py:398)
   - `sh1-orion-02`: Native token 경로는 row/column association과 unit compatibility를 통과하나 validate_unit에서 unit_association_unverified. OCR 경로는 len(chosen)!=1. 단위 literal 존재만으로 값 ownership을 승인하지 않는다. [함수](../backend/app/unit_validation.py:75)
   - `sh1-kt-01`: 실제 fused_extraction._numeric에서 native paragraph(312:379)는 period_count=0으로 not periods가 참이다. OCR paragraph(1902:2314)는 period2/metric4를 포함하지만 forecast==actual==true여서 제외된다. Source token은 있으나 claim의 기간/상태가 연결되지 않았다. [함수](../backend/app/fused_extraction.py:18)
   - `sh1-kt-02`: Item/value 표의 기간은 metric row의 literal이고 column header는 구분/내용이다. dated column parent/header는0개여서 len(headers)<2에서 제외된다. Native/Paddle topology는 이미 존재한다. [함수](../backend/app/structured_cells.py:398)

   KT의 이전 봉인 보고서에 있던 legacy numeric_evidence의 같은-line 설명은 실제 first-run 경로를 설명하지 못한다. 실제 fused paragraph predicate는 위와 같다. 원본 보고서는 수정하지 않고 이번 감사에서 정정했다.

5. **최초 유형 발생 건수**: PERIOD_VALUE_ASSOCIATION_FAILED **5/10**(표4, 본문1), UNIT_ASSOCIATION_FAILED **4/10**, SCOPE_ASSOCIATION_FAILED **1/10**. SOURCE_EXTRACTION_MISSING/TABLE_TOPOLOGY_MISSING를 최초 원인으로 확정한 사례는0이다. 필요한 원문 token과 decoded target table이 존재한다. METRIC_ASSOCIATION_FAILED 및 CELL_GEOMETRY_REJECTED는 NAVER의 일부 대안 branch에서 관측됐고, PRIMITIVE_NOT_GENERATED·DEPENDENCY_NOT_ADMITTED·SEARCHABLE_CHUNK_MISSING·RETRIEVAL_CANDIDATE_MISSING·PACK_REJECTED·COVERAGE_RECOGNITION_FAILED·SCORER_SCHEMA_MISMATCH·CROSS_PAGE_PROOF_UNSUPPORTED는 별도 downstream/계약 범주로 기록했다. 이를 최초 원인 수에 중복 합산하지 않았다. DEPENDENCY rejection의 실제 filter history는 확인할 수 없습니다.

6. **Pipeline vs scorer**: 실제 pipeline에서 10개 질문 모두 pack이0이다. 8개 표 질문은 지정 source primitive가 없고, 카카오02는 primitive가 있어도 source scope가 검증되지 않는다. KT01는 본문 numeric fact가 생성되지 않는다. 이후 HOLD를 scorer가 정상 전달했다. Scorer schema/cross-page predicate는 proof 평가를 추가로 막는 별개의 계약 문제이며 이번 coverage 실패를 설명하는 유일 원인이 아니다.

7. **Page availability와 proof recall**: 14/15는 answerable의 **15개 factual unit** 중 top-5에 지정 document/page가 있는 수이며, 질문 기준으로는9/10이다. 전체15개 질문의 성공률이 아니다. 원문·unit·scope·estimate version·footnote 및 owner closure까지 검증한 frozen evidence recall은0/15다. Page hit를 fact recall로 대신 집계하지 않았다.

8. **Source → pack 손실 위치 및 count**: 아래는 source page의 전체 pool 수이므로 다른 fact를 포함한다. 괄호의 target primitive는 원문 value 위치/quote로 식별한 approved archive 수이고, source/proof/fact/group/chunk ID는 attribution-trace.json에 각 fact별로 기록했다. Gold fact_unit_id와 기존 primitive/group/chunk ID는 원본 값이다. audit_proof_id/table_audit_id/cell_audit_id는 ID가 없는 원본 관측의 SHA-256 locator이며 새 evidence 승인이나 원본 ownership ID가 아니다. 중간의 pre-approval 생성/거절 수는 저장되지 않아 null/NOT_RECORDED로 유지한다. 일부 값 fragment가 chunk에 있다는 사실도 dependency ownership을 보장하지 않는다.

   | 질문 | native+OCR→selected words | decoded cells | approved primitive(all; target별) | group(all; target별) | physical/searchable page chunks | verified table pool / top5 numeric | pack / coverage |
   |---|---:|---:|---|---|---|---|---|
   | sh1-naver-01 | 442+426→868 | 212 | 3; [0] | 3; [0] | 80/6 | 0/0 | 0/false |
   | sh1-naver-02 | 442+426→868 | 212 | 3; [0, 0] | 3; [0, 0] | 80/6 | 0/0 | 0/false |
   | sh1-kakao-01 | 349+144→493 | 84 | 0; [0, 0] | 0; [0, 0] | 15/15 | 1/0 | 0/none |
   | sh1-kakao-02 | 293+295→588 | 1140 | 450; [2, 2] | 100; [0, 0] | 507/42 | 2/9 | 0/false |
   | sh1-celltrion-01 | 302+268→570 | 370 | 24; [0, 0] | 16; [0, 0] | 49/8 | 0/12 | 0/none |
   | sh1-celltrion-02 | 302+268→570 | 370 | 24; [0, 0] | 16; [0, 0] | 49/8 | 0/21 | 0/none |
   | sh1-orion-01 | 673+599→1272 | 571 | 4; [0] | 4; [0] | 109/13 | 0/0 | 0/false |
   | sh1-orion-02 | 673+599→1272 | 571 | 4; [0] | 4; [0] | 109/13 | 0/0 | 0/none |
   | sh1-kt-01 | 382+159→541 | 113 | 54; [0] | 46; [0] | 95/27 | 0/0 | 0/false |
   | sh1-kt-02 | 274+284→558 | 247 | 1; [0] | 1; [0] | 161/14 | 0/0 | 0/none |

   - Period/unit precondition 미충족 → approved target primitive0 → target dependency0 → 일부 필수 span 미index → page만 검색되고 verified fact가 없음 → pack0.
   - 카카오02: target primitive는 존재 → table 밖 scope가 source ownership을 얻지 못함 → target group0 및 selector source_scope_unverified → pack0. Group filter의 개별 거절 이력은 별도 미기록이며 scope만으로 모든 admission 손실을 단정하지 않는다.
   - KT01: native 기간 없는 paragraph/OCR 실적상태 혼합 → numeric fact0. 관련 본문 chunk는 존재하지만 source-bound fact가 없어 promotion/pack은0.
   - Requirements0인 answerable은 카카오01, 셀트리온01/02, 오리온02, KT02의5개다. search.rank_rows는 requirements가 없으면 pack 구성 분기를 실행하지 않아 coverage=null이고 adapter는 HOLD한다. 이는 독립적인 후속 query contract 문제다.

9. **개발용 synthetic 설계 후보**: 아래 설계만 작성했으며 새 fixture/test를 구현하거나 실행하지 않았다. 기업명·정답·bbox를 v1에서 복사하지 않는다. 실제 금융 수치/PDF를 만들지 않으며 인공 값은 synthetic label로만 사용한다.

   - **DEV-P1** `PERIOD_VALUE_ASSOCIATION_FAILED`: 독립 인공 grid에 column 기간 표와 같은 내용을 전치한 row 기간 표를 작성한다. 기간은 2027A/2028F, 인공 값17/29, metric 두 종류, 원문 단위는 같은 cell/정상 declaration로 고정한다. 좌표는 새 grid generator의 새 좌표를 사용한다. 기대: 두 orientation에서 동일 source-owned period/value proof 및 별도 modifier가 보존된다. column/row overlap 또는 동일 값의 중복 기간이 있으면 HOLD.
   - **DEV-P2** `PERIOD_VALUE_ASSOCIATION_FAILED`: 독립 명시 header에 27년 3분기와 New/Old 자식 column을 배치하고 별도 observed year context를 둔다. 값과 좌표는 모두 새 synthetic 값이다. 기대: literal raw period와 신규/이전 facet의 source span을 별도로 보존한다. 관측 없는 세기·F/E/실제 여부를 추정하지 않는다. 상충 parent header에서는 HOLD.
   - **DEV-P3** `PERIOD_VALUE_ASSOCIATION_FAILED`: 항목/내용 표에서 기간이 항목 cell에 포함된 synthetic EPS row를 만들고 별도 연도의 EPS row도 둔다. 기대: row-owned 기간이 같은 row 값에만 연결된다. 옆 row·다른 표의 기간 또는 단위는 빌리지 않는다.
   - **DEV-P4** `PERIOD_VALUE_ASSOCIATION_FAILED`: 연결 실적 문장과 별도 실적 문장을 독립 paragraph로 두고 명시적 owner를 갖는 기간 heading을 둔다. 별도 future 전망 문장도 배치한다. 기대: heading-to-claim ownership이 검증될 때만 기간을 연결한다. 다른 기간이 끼거나 actual/forecast가 같은 claim에서 충돌하면 HOLD.
   - **DEV-U1** `UNIT_ASSOCIATION_FAILED`: 새 인공 표에 금액/EPS/rate row와 서로 다른 money/per-share/% header를 둔다. Native/Paddle 서로 다른 token 분할을 독립 fixture로 모델링한다. 기대: metric family·literal unit·value owner가 모두 맞아야 승인한다. nearest % 또는 단위 suffix만으로 금액을 승인하지 않는다.
   - **DEV-U2** `UNIT_ASSOCIATION_FAILED`: 복합 단위 declaration과 단위가 grid 밖 title/footnote에 있는 표를 두며 owner link가 있는/없는 변형을 설계한다. 기대: 명시 관계가 없으면 HOLD. mixed declaration 전체가 값마다 동일 unit이라는 가정은 금지한다.
   - **DEV-S1** `SCOPE_ASSOCIATION_FAILED`: 인공 표 밖의 K-IFRS scope footnote에 table owner ID를 주고 같은 문서의 별도 표에는 상충 scope를 둔다. 기대: 명시적 table ownership만 허용한다. 같은 페이지 또는 가까운 위치만으로 scope를 상속하지 않는다.
   - **DEV-D1** `DEPENDENCY_NOT_ADMITTED`: 동일 value word를 두 다른 cell/table owner가 소유하는 native/Paddle 중복과 유일 owner control을 설계한다. 기대: 유일 owner는 admission 가능, 충돌 owner는 fail closed. 이번 run의 target group 손실 원인이 이 조건이라고 확정한 것은 아니다.
   - **DEV-SC1** `SCORER_SCHEMA_MISMATCH`: 새 synthetic 완전 proof DTO에서 top-level HOLD/COMPLETE/ERROR와 fact-level forecast/actual/provisional/unspecified를 별도로 명시한다. 기대: 엄격한 enum/alias 계약을 검사하고 reported_not_explicitly_final을 actual과 임의 합치지 않는다. status 표시 변경으로 evidence coverage가 바뀌면 실패.
   - **DEV-X1** `CROSS_PAGE_PROOF_UNSUPPORTED`: 새 인공 문서 page1 scope→page2 value의 명시적 table ownership graph와 link 없는 control/다른 문서의 동일 span을 설계한다. 기대: 문서/page/span/owner를 모두 검증하는 dependency closure만 허용하고 cross-document·link 없는 proximity proof는 거절한다.

10. **Production 수정 없이 가능한 문제**: audit telemetry/field diagnostics 개선, source형 enum과 별도 scorer-v2 계약 명세 및 synthetic 설계, page-aware proof 평가 구조 명세는 evaluation tooling만으로 분리할 수 있다. 기존 v1 scorer/점수는 수정하지 않는다. 이 방법으로 pipeline evidence가 새로 생기지는 않는다.

11. **Production 계약 변경이 필요한 문제**: 기간의 role/orientation/owner 연결, table/unit/metric의 explicit ownership, table 밖 scope 관계, paragraph claim별 period/status binding, source별 duplicate ownership/admission, cross-page dependency closure, query requirement generation이다. 단순 threshold 완화·가까운 span 상속·기업별 예외로 해결하지 않는다. 향후 API/data model이 바뀌는 작업에서 api-contract.md/acceptance.md/qa-rules.md를 함께 갱신해야 한다.

12. **최초 결과 불변**: coverage0/10, false-HOLD10, expected HOLD5/5, false-complete0, strict0/10, frozen recall0/15는 그대로다. Prediction inventory `19d19c1211a56a62d036ebee29b72a861a813301245f005a296e455f35350d16`, scoring `ed10709ce26ceb3cb03ee16d654353cb4145276a692be19b03e385cfc26ec85c` 동일. Hash/flag 해제 또는 덮어쓰기 없음. 새로운 holdout prediction/scoring/retrieval/ranker 실행0, 실제 LLM 호출0, OCR 재처리0, embedding 재생성0. 기존 회귀 검사의 synthetic 함수 호출은 별도이며 holdout 분모에 포함하지 않는다. 기존 pure predicate/원문 metadata의 사후 검사는 evaluation 재실행이 아니다.

13. **DB**: localhost:5432 READ ONLY 접속 시 Connection refused. PostgreSQL은 exited(0) 상태이며 사용자가 서비스를 그대로 유지하도록 선택했다. 따라서 **이번 감사의 live 5-table hash는 NOT_VERIFIED**다. 과거 first-run의 봉인 before/after snapshot과 checksum은 재검증했고 동일하지만 이를 현재 DB hash로 대체하지 않았다. 과거 count: documents10, pages75, chunks231, analysis_runs311, page_extractions0. DB write/migration/revision 변경0, 서비스 시작0.

14. **Regression**: 이번 `./scripts/check.sh` PASS — backend536 passed/1 skipped, frontend7 passed, lint/build PASS. Immutable cached regression verifier PASS: 현대차/삼성 offline PASS, 기아 manual REVIEW, SK/Counts HOLD, 개발12/12, POSCO1/1, selected pack20/20, review-aware/effective false-complete0. Protected source149개 hash 동일. Skip은 기존 google.genai SDK 미설치이며 새 LLM 실행 없음.

15. **다음 개발 작업 1순위**: **Source-owned period binding 계약** 하나를 추천한다. 동일 taxonomy 최초 실패5개/4문서로 가장 반복적이고 primitive 생성 전에 발생한다. 먼저 DEV-P1~P3의 독립 table fixture와 ambiguity control로 literal period·orientation·metric/value owner·estimate qualifier를 명세하고, 한 가지 형태씩 incremental하게 검증한다. 본문 parent-period 문제 DEV-P4는 같은 계약의 확장 검증 대상이다. Geometry/신뢰도 cutoff는 유지하고 원문에 없는 qualifier/세기를 추정하지 않는다. 이번에는 설계 제안만 한다.

   | 계층 | 최초 영향 | 반복성/계약 위험 | 일반화/검증 |
   |---|---|---|---|
   | 기간 ownership | 5 | 높음: transposed/year-literal/row period/prose context / 중간: qualifier 및 ownership 유지 필수 | literal period role + orientation/owner binding, geometry threshold 유지 / DEV-P1~P4 및 ambiguous controls; 단계적 table subset부터 |
   | 단위 ownership | 4 | 높음: mixed header/title declaration / 높음: 단위 스케일 오인/false-complete | 원문 전체 unit과 value 소유권 증명 / DEV-U1~U2 및 기존 suffix/geometry tests |
   | scope ownership | 1 | 높음: 표 밖 scope footnote / 높음: 별도/연결 혼동 | explicit table/source relation, proximity 상속 금지 / DEV-S1, cross-page controls |
   | dependency admission | target group 결여 관측 9개 table 질문; 독립 최초 원인 수 미확정 | 다중 source/owner 가능 / 높음 | 거절 predicate telemetry와 unique owner proof / DEV-D1; 이번 artifact의 group filter history는 확인할 수 없습니다 |
   | scorer schema/cross-page | 잠재 status 10개/15 facts, cross-page 4개/7 facts | 확정적 DTO predicate 문제 / 새 evaluation version 필요 | 별도 scorer-v2의 typed DTO + page-aware proof ownership / DEV-SC1/DEV-X1; v1 score 대체 금지 |

16. **독립 검증 계획**: v1의 알려진 failure는 개발 피드백으로만 취급한다. 새 문서 SHA·기업·질문·source span/bbox가 겹치지 않는 holdout을 새 code/config/scorer version 및 분모와 함께 사전 봉인하고 prediction/scoring을 분리한다. 새로운 scorer-v2를 v1 prediction에 적용하는 실험이 이후 별도로 승인되더라도 사후 진단 run으로만 기록하고 최초 v1 결과를 대체하거나 새로운 blind 평가라고 부르지 않는다. Synthetic 및 regression이 통과한 뒤 새 독립 holdout에서 source-owned proof recall/strict/false-complete를 평가한다.

최종 답: 0/10의 직접 원인은 실제 pipeline failure다. Scorer 오류도 함께 있지만 이를 고쳐도 저장된 coverage/pack은 달라지지 않는다. 같은 최초 taxonomy는 period5개이며, page는 찾았어도 period/unit/scope ownership이 primitive/dependency로 연결되지 못했다. 다음 일반 계약은 source-owned period binding이다. Sealed v1 최초 결과는 변경 없이 유지되었다.
