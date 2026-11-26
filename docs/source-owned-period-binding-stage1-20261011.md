Source-Owned Period Binding — 1단계 구현 및 검증 (2026-10-11)

1. **변경 파일**
   - 신규: `backend/app/period_binding.py`, `backend/tests/test_period_binding.py`.
   - Production 연동: `structured_cells.py`, `fused_extraction.py`, `fused_candidates.py`,
     `extraction_provenance.py`, `index_admission.py`, `evidence_bundle.py`, `fact_fusion.py`.
   - 감사 도구: `scripts/audit_counts_requirement.py`, `scripts/audit_unit_precision.py`.
   - 계약 문서: `api-contract.md`, `acceptance.md`, `qa-rules.md`.
   - `primitive_graph.py`, BM25/vector/RRF, chunk cutoff, unit/scope validator 및 geometry threshold는 변경하지 않았다.

2. **기존 계약과 구조적 원인**
   `_cell_topology`는 첫 두 row의 제한된 literal 기간 형태를 header로 보고,
   header가 두 개 미만이면 전체 표를 버렸다. 단일 기간의 source proof가 충분해도
   fact를 만들지 못했다. 각 header/value의 geometry 검사는 있었지만 값 열에 대한
   전체 기간 후보의 유일성 검사는 별도 계약이 아니었다. 날짜처럼 생긴 금액도
   header 후보가 될 수 있었다. `_numeric`은 paragraph 내 앞선 기간/지표와
   paragraph 전체 status를 사용해 문장/구문 소유 관계가 약했다.
   한국어 축약 연도·전치된 기간 행·item/value label의 기간 등도 기존 지원 범위 밖이었다.
   이 작업은 그 모든 형태를 해결했다고 주장하지 않는다.

3. **일반화 규칙**
   `source-owned-period-v1`은 문자열 거리 대신 원문 span, source SHA-256,
   물리 page/table identity, topology, column group과 metric row membership을 증거로 사용한다.
   단일 header도 승인 가능하지만 값 열의 period owner는 정확히 하나여야 한다.
   미지원 날짜 header도 충돌 검사의 후보에 포함하며 연도나 century를 추정하지 않는다.
   앞선 기간 header 아래의 지표 행에 속한 숫자는 year-shaped amount여도 value로 유지한다.

4. **Table / paragraph 지원 범위**
   표: 기존 literal 연도/quarter 기간 열, 단일·복수 기간, 검증 가능한 parent + New/Old 등의 child header.
   표의 지표·단위·값 셀과 header geometry는 기존 검증을 그대로 통과해야 한다.
   문장: 같은 source의 명시적 한 sentence 안에서 한 period와 한 metric으로 연결된 구문.
   다른 subject/미등록 지표를 통과하거나 문장/문단을 넘어 기간을 상속하지 않는다.
   한 지표의 복수 동일 단위 금액은 명시적 benchmark 연결이 없으면 거절한다.

5. **Ownership 검증**
   표 proof에는 parent column group, value column, metric row, parent/child/value bbox와
   literal metric/period/value/unit span이 포함된다. 기존 `_association`의 unique span-cell
   membership, row group 및 geometry 검증 후 생성하고, 저장 fact는 원문에서 재구성한다.
   외부 table ID, header owner, row/column, source span 또는 foreign document ID의 변조는
   admission을 통과하지 못한다. Document namespace는 기존 page/graph/pack 경로가 제공한다.
   문장 proof에는 sentence 범위와 period/metric/value/unit/status의 실제 source span이 포함된다.

6. **Actual / forecast**
   Literal A와 F/E를 구분하고, 같은 column group의 실적/확정과 예상/전망 qualifier가
   충돌하면 거절한다. 문장 전체에 actual과 forecast가 함께 있거나 period suffix와
   predicate가 불일치하면 거절한다. 서로 다른 명시적 문장은 독립적으로 검증한다.
   문장 P(preliminary)의 final/forecast status를 임의로 결정하지 않는다.

7. **추가 테스트**
   독립 synthetic **34개**: 단일/복수 header, multi-level header, 명시적 문장,
   별도 actual/forecast 문장, source proof 및 legacy archive 재검증 positive를 포함한다.
   Negative는 복수 period owner, 다른 column/row/table/document, period span 삭제,
   header owner 변조, actual/forecast 충돌, 동일 문단의 다른 지표/미등록 subject,
   미지원 날짜 후보, 동일 지표의 불명확한 복수 값, 새 버전의 proof 삭제를 포함한다.
   회사명·sealed question ID·정답·원문 bbox를 복사하지 않았다.

8. **Verified fact 생성**
   충분한 metric/period/value/unit source proof를 가진 표에서 새로운 primitive가 생성된다.
   `period_binding.approved`만으로 complete financial fact 또는 factual correctness를 승인하지 않는다.
   표의 unit validation/metric compatibility 및 query의 scope/annotation/requirement 검증은 유지된다.
   문장 binding은 candidate의 관계 proof이며 numeric admission/pack의 unit·source 검증도 필요하다.

9. **Dependency admission 연동**
   기존 primitive graph가 새 fact와 proof를 보존하고 `dependency_groups`가 period proof를 전달한다.
   기존 source-span dependency slices가 physical chunk에 들어간다. 원문 quote는 바뀌지 않는다.
   새 parser는 `fact-fusion-paddle-v4`이며 새 표/문장 observation의 proof 삭제를 거절한다.
   Legacy table은 강화된 source rederivation을 통과해야 하며 additive metadata는 생략 가능하다.
   Legacy numeric observation은 기존 검증 경로를 유지하고 새 period contract로 재인증했다고 주장하지 않는다.
   Frozen observation을 현재 parser version으로 바꿔서 검증하지 않는다.

10. **Synthetic end-to-end**
    단일 기간, 복수 기간 비교, multi-level source의 세 trace에서
    source → primitive graph → dependency admission → exact chunks → 기존 BM25 →
    verified candidate → evidence pack → coverage가 PASS다.
    문장은 기존 numeric candidate → numeric pack 경로의 targeted test로 검증했다.
    서비스·DB·OCR·embedding·LLM 호출 없이 실행했다.

11. **기존 regression**
    Development combined comparison recall **12/12**, POSCO compound coverage **1/1**.
    기존 selected pack **20/20 완전 동일**. 기아는 coverage true / automatic strict false /
    manual REVIEW를 유지하고 SK와 Counts는 HOLD를 유지한다.
    최신 baseline의 validated fact metadata 및 원래 observation/rank로 재검증했다.
    이전 raw observation과 비교한 cashflow pack의 metadata 차이는 별도 로그에 남겼다.
    현대차 offline PASS와 삼성 offline PASS를 현재 validator로 재검증했다.
    기존 BM25/vector/hybrid 모드 15 pack 및 두 fixture pack, 합계 **17 pack**이 동일하다.
    재검증 결과는 `offline-pass-regression.json`에 기록했다.
    합쳐진 comparison envelope 대신 원래 primitive unit proof를 검증했다.

12. **False-complete 방어**
    Review-aware false-complete **0**. Coverage와 automatic strict 및 manual REVIEW를 구분한다.
    Unit/scope/annotation 검증을 period proof로 대체하지 않는다. 새 proof가 없거나 변조되면 HOLD다.
    기존 geometry/unit/scope/graph/search/chunk guard 파일 8개의 hash가 이전 감사와 동일하다.

13. **전체 테스트**
    Targeted ownership/shared-context/unit/admission/period/Counts 테스트 **178 passed**.
    `./scripts/check.sh`: backend **570 passed / 1 skipped**, frontend **7 passed**, lint/build PASS.
    Skip은 설치되지 않은 `google.genai`에 대한 기존 테스트다. `git diff --check` PASS.
    최초 red 단계와 Counts 감사 도구의 이전 predicate 추적 실패도 로그에 보존했다.

14. **Hardcoding 검사**
    새 production module에 holdout 회사·질문 ID·정답·bbox literal은 없다.
    Fixture는 corpus를 읽지 않는 임의의 기간/값/geometry다. Gold, query rewriting,
    retrieval cutoff/parameter/RRF, 모델 설정은 변경하지 않았다.

15. **Holdout v1 불변**
    Sealed bundle **64개** 파일을 manifest hash 목록과 대조했다.
    First-run/report/receipt 등을 포함한 보호 artifact **51개**의 SHA-256·permission·flags가 전후 동일하다.
    First-run directory immutable flags도 유지된다. 원래 15문항의 prediction/scoring은 재실행·재채점하지 않았다.
    원래 run ID: `7db3bde0-1c92-4c7c-b0c2-f9a73c7db505`.
    Manifest: `e953979e5413db83d4355b205ddfacf6abdfbb8ceef4cfaa2e84d1a5f5527b57`.
    Frozen configuration: `2ebceaf80a38250dad3077d19b4ce773b653b12ad3380d99fbee55fd7acf2332`.
    Configuration file 자체 SHA-256과 semantic frozen configuration hash는 서로 다른 항목이다.
    허가된 production 구현으로 현재 code는 봉인 당시 code와 다르다. Baseline archive/manifest를
    재봉인하거나 갱신하지 않았다. 새 코드의 holdout 점수 개선 여부는 측정하지 않았다.

16. **DB / production 안전성**
    PostgreSQL Exited (0), backend/OCR worker/frontend도 종료 상태를 유지했다.
    Live DB 5개 table hash: **NOT_VERIFIED**. 기존 평가의 DB hash 동등성은 역사적 기록일 뿐이다.
    Migration, DB write, active revision 변경, production OCR/embedding 재처리는 없었다.
    Production source 구현은 변경했으며 deployment와 서비스 재기동은 하지 않았다.

17. **미지원 구조**
    전치된 기간 행, item/value label 속 기간, 축약 연도의 century 확장,
    임의 multi-level header, 여러 지표가 섞인 자유 문장, 원격 heading/다른 문단/다른 page의 기간 상속은
    이번 새 계약에서 지원하지 않는다. 범위 밖 구조에서 관계를 추정해 complete로 승인하지 않는다.

18. **다음 후보**
    전치된 기간 행의 row-owner proof, 한국어 quarter의 literal year 확인,
    item/value label의 period ownership을 각각 독립 fixture와 함께 확장할 수 있다.
    Unit association과 scope association은 별도 계약 개선 작업으로 진행한다.
    새 실험은 별도 run으로 구분하고 holdout v1 최초 결과는 계속 보존한다.

최종 답변:
기존 실패는 제한된 header 형태와 최소 두 header 조건, period 후보의 ownership 계약 부족,
paragraph 범위의 기간 상속에서 발생했다. 새 계약은 source SHA/span과 header column group,
metric row/value cell membership 및 같은 문장 구문 proof를 더 활용한다.
복수 period와 actual/forecast 충돌은 차단한다. 새 verified table fact가 생성되고
admission과 pack까지 전달된다. 기존 PASS/HOLD/REVIEW 상태는 frozen development/offline regression으로
유지됐으며, live DB는 NOT_VERIFIED다. Holdout 하드코딩과 최초 결과 변경은 없다.
이번 검증은 retrieval/evidence와 source ownership 검증이며 LLM 답변 생성 평가는 아니다.
