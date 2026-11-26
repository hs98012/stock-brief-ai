# Counts requirement 조사 — 2026-10-10

결정: **C, production 변경 없이 HOLD 유지**. 질문의 대상 열이 누락됐고 현재
source-bound count primitive/완전성 계약도 지원되지 않는다. Requirement를
강제로 생성해 challenge 정답에 맞추지 않았다. 근거 있는 최종 count 결과는
**확인할 수 없습니다**.

1. **실제 질의**: `표에서  계과 계의 값을 알려줘.`
   `graph-after-final-search-20261002.json`의 저장된 question을 그대로 사용했다.
   `audit_primitive_graph.run()`은 명시 question이 없으면 period와 row_label로
   fallback 질의를 만든다. 이 경로는 열 metric을 포함하지 않으므로 같은
   `계` row_label을 두 번 요청한다. 저장된 question과 생성 코드만으로 이
   손실을 확인했으며 gold cell 값으로 조건을 복원하지 않았다.

2. **전체 failure path**:
   - Query: 두 requested column의 정체성이 없어 `계`를 유일하게 해석할 수 없다.
   - Query parsing/requirement: `requirements_for()`의 복합 질의 조건이 성립하지
     않고 fallback의 `PERIOD.search(question)`도 false여서 `[]`다.
   - Count 대상 정의: `METRIC.search(question)`도 false. 직접
     `table_requirements()`를 호출해도 metric=None, period=None인 generic requirement다.
     이를 `fact_requirement_match()`는 `metric_unspecified`로 승인하지 않는다.
   - Source: raw table/header/total/value/단위 관측은 존재하나 period token은 없다.
   - Primitive/graph: 저장 fact=0, 현재 재도출 fact=0, validated fact=0, graph node=0.
     `_cell_topology()`의 실제 두 source stream trace 모두 header_count=0이다.
     `_vertical()`도 period/short-year header가 필요하고 `primitive_graph()`도
     유효 `period_identity`를 요구한다. 표 명칭 header는 period header가 아니다.
   - Admission/chunk: index_segments=0, structured_spans=0. Raw text를 fallback
     chunk로 승격하지 않았다.
   - 실제 실행 순서: source 준비에서 이미 0 rows가 되어 `rank_rows()`가
     `if not rows`에서 반환한다. 그러므로 저장된 search.requirements는 null이며
     parser는 실행되지 않는다. 별도 parser 호출 결과 `[]`와 구분해야 한다.
   - Evidence bundle: 실행되지 않으며 pack=null, coverage=null, strict=false, HOLD다.

3. **최초 실패 함수/predicate**: 질의 의미 손실은 audit harness의 fallback
   question 생성식(row_label만 사용)이 최초다. Requirement 함수 단독 재현은
   `requirements_for(): PERIOD.search(question) == false → []`다. 실제 검색에서
   requirement 계산에 도달하지 않는 최초 직접 조건은
   `rank_rows(): if not rows`다. Source primitive 경로의 최초 gate는
   `_cell_topology(): len(headers) < 2`(관측값 0)이므로 continue다.
   과거 artifact의 `period association`만으로 전체 원인을 설명할 수 없다.

4. **Count 유형**: source는 **A, 명시된 총수치 조회 후보**다. 실제 질문은
   ‘몇 항목인가’를 묻지 않으므로 행 개수/고유 개수/필터 집계 질의로 분류하지
   않는다. A조차 requested metric이 빠져 어떤 total cell을 선택할지 미정이다.
   B(닫힌 모집단의 검증된 전체 항목 집계)는 이 자료로 증명되지 않는다.
   C(일부 검색 결과)는 전체 count를 승인할 근거가 될 수 없다.

5. **Source evidence**: frozen page 1 native table은 21 rows × 8 columns다.
   header에 `사 고 (건)`, `노인사고`, `전체사고`, `사 망 (명)`, `부 상 (명)`이
   있으며 `계` row에 서로 다른 total cell이 존재한다. 예를 들어 원문 관측
   `42,369`, `196,349`, `761`, `59,776`은 서로 다른 열에 있고 비율 열도 있다.
   이는 raw 관측의 설명이며 승인된 답이나 target 선택 근거가 아니다.
   Header/첫 데이터 행과 겹치는 selected word 54개는 모두 final_text slice와
   일치한다. Bbox/topology도 artifact에 보존했다. 숫자만 존재하는 것과
   metric→scope→unit→total의 검증된 귀속은 다르다. Source PDF SHA-256은
   observation에 바인딩돼 있지만 해당 원본 PDF는 현재 workspace에서 찾지
   못했다. 이번에 새 원본 시각 대조/OCR은 하지 않았다.

6. **완전성**: `계`는 explicit total의 존재 관측이다. 특정 target에 연결된
   승인된 completeness proof는 없다. 지역별 행은 이미 집계된 건수이며 사고
   개별 항목의 완전한 목록이 아니다. 지역 행 수를 사고 수로 세거나 합계를
   계산해 target을 추정하지 않았다. 검색 chunk=0은 실제 사건 수=0을 뜻하지
   않는다. 일부 항목 검색, 원문 반복, 누락된 기간에서 모집단 완전성은
   **확인할 수 없습니다**.

7. **필요한 계약(후속 설계, 이번에는 미구현)**:

   | 최소 필드 | A: explicit total | B: complete members |
   |---|---|---|
   | kind/counting_rule | count / declared_total | count / verified_members |
   | target_entity | 질문에 명시된 metric/column identity | 집계할 항목의 의미 |
   | scope | document/page/table + row/column identity | 닫힌 모집단 경계와 포함/제외 규칙 |
   | period | 명시 source proof 또는 source_unspecified; 추정 금지 | 동일 기간의 전체 구성원 proof |
   | source_dependencies | title/header/row/unit/value span + bbox + source hash | 경계/목록/각 항목 identity span + source hash |
   | completeness_proof | target/scope와 total 선언의 검증된 귀속 | 전체 membership manifest와 누락 없음 proof |

   filters는 조건 질의일 때만, distinct_key는 고유 집계일 때만 필요하다.
   `count=3`만 저장하지 않고 rule/dependency/구성원 identity를 보존해야 한다.
   기간 없는 source는 기간 미명시 사실 자체를 보존하고 현재/특정 연도로
   바꾸지 않는다. 합계 셀 조회와 항목 집계는 별도 proof 규칙으로 검증한다.
   기존 금융 metric의 money/ratio 계약을 count로 오인시키지 않는다.
   Structured primitive와 unit validator에는 이미 `명/건/개`가 있으나
   requirement METRIC/UNIT/MONEY vocabulary와 period gate, graph는 typed count
   계약을 제공하지 않는다. Regex 하나 확장으로 해결되지 않는다.
   A의 source identity는 document hash/page/table/row/column로 바인딩하고,
   반복 chunk·native/OCR 재표현은 같은 total의 독립 구성원으로 세지 않는다.
   B는 구성원 identity를 source span 및 경계 proof에 바인딩하며 동일 항목의
   중복 검색/반복 chunk를 제거한다. Subtotal/total과 그 자식을 함께 더하지
   않고 중첩 분류는 포함 규칙이 검증돼야 한다. 다른 기간/scope가 섞이거나
   필터를 만족하지 않으면 HOLD다. Source proof가 삭제되거나 원문 total과
   산출값이 다르면 HOLD다. 여러 표의 합집합과 distinct count는 이번 계약의
   지원 대상으로 승인하지 않았다.

8. **변경 파일**: `scripts/audit_counts_requirement.py`(gold를 읽지 않는
   offline source/함수 trace), `backend/tests/test_counts_diagnosis.py`, 이 문서,
   `evals/counts-reviewed-20261010.json`(실행 검증 기록).
   Git-ignored raw diagnosis/regression/verification JSON도 보존한다.
   기존 사용자 수정/미추적 파일은 그대로 보존했다.

9. **추가 테스트**: 10개. 현재 query/source의 독립된 실패, period gate를
   우회해도 metric identity 누락, raw cell이 completeness proof가 아님,
   source 삭제 후 승인 불가, 여섯 종류 count 표현의 typed requirement 미지원
   경계를 확인한다. count validator 구현의 positive/negative 테스트로
   확대 해석하지 않는다. 구현이 미정당하므로 요청된 validator positive와
   기간 혼합/소계/중복/필터/불일치 negative matrix는 후속 계약의 필수 조건으로
   남긴다. 현재 테스트로 그 미구현 기능이 지원된다고 주장하지 않는다.

10. **Counts 전후**: requirement=[](직접 호출), search.requirements=null,
    coverage=null → null, automatic strict=false → false, HOLD 유지.
    null을 false나 PASS로 바꾸지 않았다.

11. **기존 판정 보호**: 새 frozen-rank replay와 독립 component verifier로
    현대차 hash-bound offline PASS 15 outcomes freeze, 삼성 관측 offline PASS,
    기아 coverage=true/manual strict review, SK mixed-unit HOLD를 보존한다.
    옛 삼성/현대차 fixture의 HOLD와 이후 관측된 offline PASS를 구분한다.

12. **False-complete**: review-aware 계산을 사용한다. Counts null coverage를
    complete로 세지 않고 기아 manual review도 실패로 재분류하지 않는다.
    세부 실행 결과는 reviewed JSON의 regression 항목을 따른다.

13. **전체 regression**: `./scripts/check.sh` backend **506 passed / 1 skipped**,
    frontend **7 passed**, lint/build PASS. Targeted **262 passed / 1 skipped**
    (parser/bundle/integrity/admission/unit/scope/annotation/shared-context/
    ownership/structured/row/graph 포함). Skip은 optional google.genai 미설치다.
    Frozen hybrid rank 재생이며 신규 live retrieval/OCR/embedding/LLM 평가가 아니다.
    Selected pack/개발/POSCO/frozen PASS 검증 및 diff/변경 파일 hardcoding 검사
    결과는 reviewed JSON에 기록한다.

14. **DB hash**: **NOT_VERIFIED**. `hash_active_tables.py`의
    REPEATABLE READ READ ONLY snapshot 시도는 sandbox에서 Operation not permitted,
    허용된 localhost 재시도는 Connection refused였다. 대상은 documents/pages/
    chunks/analysis_runs/page_extractions다. Hash를 측정하지 못해 기존 baseline과
    비교할 수 없다. Historical equality를 live 확인으로 보고하지 않는다.
    DB 초기화/기동/migration/복원/revision 변경을 하지 않았다.

15. **Production**: 변경 **0**. Audit 전후 backend/app 및 frontend/app의 모든
    파일 SHA-256 동일. OCR/embedding/BM25/RRF/LLM/geometry threshold 변경 없음.
    API/data model 변경이 없어 api-contract.md/acceptance.md/qa-rules.md도 이번
    작업에서는 변경하지 않았다.

16. **다음 후보**: 먼저 사람의 독립적인 실제 질문으로 target 열과 scope를
    명시해야 한다. 이후 source PDF를 확보해 기간 미표기·total/header/unit/행
    귀속을 원문 대조하고, period 없는 explicit-total primitive 및 admission
    계약을 별도 범위로 설계한다. Gold의 열을 fallback 질문에 넣어 이번
    challenge를 성공시키는 것은 하지 않는다. B 집계는 닫힌 모집단 증거를
    가진 별도 fixture에서 검증하고 중복/기간/scope/소계/필터를 검증해야 한다.

| 최종 질문 | 답 |
|---|---|
| Requirement 미생성 최초 원인은? | Harness 질의의 열 identity 손실. Parser 직접 gate는 period 없음; 실제 검색은 admitted rows=0으로 parser 이전 반환. |
| 대상 집합/집계 범위가 유일한가? | 아니오. `계`만으로 여러 count/ratio 열 중 대상을 정할 수 없다. |
| 전체 항목 completeness proof가 있는가? | 없다. Raw total 선언만 관측되며 B의 개별 사고 모집단은 없다. |
| Count 결과를 원문 evidence로 재구성 가능한가? | 현재 검증 계약으로는 불가. 명시 수치의 raw 위치는 보존했지만 요청 target/proof chain이 없다. |
| 자동 PASS가 정당한가? | 아니오. HOLD 유지. |
| 추가 증거는? | 독립적인 명확한 query, source PDF/기간 상태, total의 metric/scope/unit 귀속 proof. B라면 닫힌 모집단 전체 목록과 identity/누락 없음 증거도 필요. |
