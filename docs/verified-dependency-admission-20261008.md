# Verified primitive dependency admission — 2026-10-08

1. **변경 파일**: `backend/app/index_admission.py`(신규), `fused_extraction.py`,
   `fused_index.py`, `chunking.py`, `backend/tests/test_index_admission.py`(신규),
   `scripts/audit_index_admission.py`(신규), `api-contract.md`, `acceptance.md`,
   `qa-rules.md`, 이 보고서. 기존 사용자 변경을 보존했다.

2. **기존 admission 조건**: fusion에서 선택한 `facts`의 quote를 `fact_quote`,
   각 source span을 `fact_span`으로 등록했다. 안전한 paragraph는 최소 길이,
   문장 종결, non-grid 조건을 만족해야 했다. unsafe/conflict span은 제외됐다.
   `structured_spans`는 등록된 범위만 chunk로 만들었다. `searchable`은
   `paragraph`/`fact_quote`의 시작을 포함하는 chunk만 승인했다.

3. **CHUNK_MISSING 코드 원인**: `fused_extraction.py`의 `for fact in facts`
   admission loop가 별도로 보존한 `primitive_cells` dependency를 인식하지
   않았다. frozen fixture의 period는 선택 fact span으로 남았지만 나중에
   검증된 context/metric/unit/value는 등록되지 않았다. annotation definition/
   marker는 `metric_identity` metadata와 `annotation_spans`에서 복원되는
   proof이며 기존 index loop에는 포함되지 않았다. 검색 cutoff 문제가 아니다.
   archive의 comparison metadata 생략도 validator 연결에서 복원해야 했다.

4. **새 계약**: `verified-dependencies-v1`. C 방식으로 정확한 source slices와
   page-local evidence group을 연결한다. source 재검증을 통과한 primitive만
   group을 생성한다. table/row/primitive/ownership/context/scope, raw/canonical,
   annotation proof, anchor, dependency spans, search text를 저장한다.

5. **dependency 계산**: `primitive_graph`의 검증된 node에서 parser comparison
   부분을 제거하고 그 cell의 명시적 source spans와 검증된 annotation spans만
   취한다. archived primitive는 현재 source 재추출 결과의 정확한 preimage일
   때만 생략된 comparison metadata를 복원한 뒤 기존 validator를 통과시킨다.
   같은 table/page 또는 거리로 span을 추가하지 않는다. 비교는 기존 graph
   edge로 연결된 두 primitive group의 union을 사용한다. query-requested pair
   이외의 연산 proof를 생성하지 않는다.

6. **searchable 규칙**: group의 metric/row anchor를 포함하는 chunk에만 전체
   chain의 검색 표현을 붙인다. 원문 label·scope·unit·period/value와 검증된
   canonical label이 포함된다. proof-only span은 별도 검색 hit가 필요 없다.
   원문과 `content`, offsets, quote는 바꾸지 않는다. 기존 paragraph/fact_quote
   searchable 규칙은 유지한다.

7. **scope/ownership**: scope literal과 source membership, metric ownership을
   재검증한다. collision은 scope-local unique selection을 통과해야 admission
   된다. 연결/별도는 별도 group과 anchor를 갖는다. 같은 canonical label로
   합치지 않는다. ambiguous scope/owner는 승인하지 않는다.

8. **annotation**: raw label → located marker → unique verified definition →
   canonical 관계를 group에 저장한다. marker와 definition 원문 slices도
   admission한다. annotation 검증 없이 canonical만으로 group을 만들 수 없다.
   정의 전체가 독립 searchable hit가 될 필요는 없다.

9. **duplicate/overlap**: page/offset pair마다 dependency segment를 하나 등록하고
   group IDs를 공유한다. 중복 source storage를 요구하지 않는다. 겹치는 raw
   label/marker slice는 기존 source-range chunk construction으로 합쳐지며,
   신규 계약에서는 서로 닿기만 하는 범위는 합치지 않는다. 같은 value source에
   다른 table/row/owner가 존재하면 해당 group들을 제외한다. group identity는
   primitive/table/row/ownership/context/scope를 포함한다. 기존 retrieval dedup은
   수정하지 않았다: document/page/raw row·metric/unit/value/basis/status/period
   기준이다. 명시적 scope query는 기존 fact matching에서 먼저 다른 scope를
   제외하며, scope 없는 collision은 HOLD하므로 canonical 기준 병합이 없다.

10. **추가 테스트**: 15개. context+metric+unit+period/value 전체 admission,
    두 period 비교 pack, annotation raw/canonical/proof, 연결/별도 분리,
    shared context의 독립 metric chain, idempotence/reference 공유,
    fusion 밖 archived primitive 복원, touching group 분리를 확인했다.
    unverified primitive, 위조 owner/context, 다른 metric value 차용,
    value/unit 누락, annotation proof 누락, unrelated page text,
    동일 value의 위조 owner, scope ambiguity와 unverified archive를 거부했다.

11. **현대차 frozen chunk**: 새 파일
    `evals/results/paddle/dependency-admission-hyundai-final-20261008.json`.
    원본 fixture를 덮어쓰지 않았다. 97페이지, 16→95 chunks, 검증된 primitive
    group 30개, dependency segment 88개, searchable anchors 12개다.
    30개는 각자 검증된 cell의 최소 dependency이며 table의 모든 span이 아니다.
    raw/canonical/annotation/source offsets와 모든 chunk ID는 JSON에 있다.
    연결 anchor: `7fc0202d-d785-52e9-95b9-3a9df85e55a0` (1341:1348).
    별도 anchor: `793a8b32-dd37-5b10-98d1-a4ad9c4e012a` (1398:1403).

    | 필수 source | chunk ID | admission / pack |
    |---|---|---|
    | 수익성지표 | 824899a0-ed7a-5512-a89f-4269292a3d82 | 모두 true |
    | (연결 | e2ae4d16-76bf-5c1a-aa10-b9b695643df9 | 모두 true |
    | 기준) | 04748f4d-cec2-582e-aaf0-eeae3eceeb0d | 모두 true |
    | 영업이익률3) | 7fc0202d-d785-52e9-95b9-3a9df85e55a0 | 모두 true |
    | % | ea561112-b4ae-5363-bb5b-3f7baa5293d2 | 모두 true |
    | 2022 | 93349e03-6865-5051-a85e-4c76d81209c8 | 모두 true |
    | 6.9 | 319692cb-ef13-57bd-a954-c0514bfa7e47 | 모두 true |
    | 2023 | 6eb054f3-e22d-53dd-8508-1690ebe829a7 | 모두 true |
    | 9.3 | efca383b-119e-5415-ae32-991db8dd5f03 | 모두 true |

    annotation marker는 raw label chunk에 포함되고 definition의 각 span도
    admission 및 pack에 포함된다. 전체 provenance matrix를 JSON에 기록했다.

12. **retrieval candidate**: 기존 production `rank_rows`로 새 offline BM25를
    실행했다. 연결 anchor BM25/RRF rank=4, 별도 anchor rank=6. 검증된 table
    candidate 0→2. parameter, top-k=5, candidate limit=20, RRF k=60 그대로다.
    새 embedding을 만들지 않아 신규 vector 결과는 **확인할 수 없습니다**.
    이전 frozen vector ranks를 새 chunk의 rank로 전용하지 않았다.

13. **selected pack**: 현대차 offline 재생성 fixture에서 []→연결 anchor 1건.
    두 비교 방향과 모든 required source spans를 포함한다. 다른 scope value는
    선택되지 않았다. 기존 frozen corpus는 재생성하지 않았다.

14. **coverage**: 현대차 false→true. 두 requirement의 matching, annotation,
    graph comparison, pack source-span validation이 모두 true다. 기존 gold의
    2022/2023 raw metric·unit·value·bbox와 원문 slices를 독립 확인했다.
    `dependency-admission-verification-20261008.json`에 검증 결과를 기록했다.

15. **회귀**: 개발 12/12, POSCO compound 1/1, 삼성 false-complete 0,
    SK HOLD, 기아 coverage=true/strict=false의 기존 review 상태 유지. 기존
    selected pack **20/20 exact equality**. 새 admission을 기존 corpus에 소급
    적용하지 않았다. 이전 현대차 frozen pack은 []로 보존하며 새 fixture만 바뀌었다.
    `dependency-admission-reviewed-20261008.json`과 regression JSON/log에 기록했다.

16. **전체 검사**: admission 15 passed, annotation/scope/shared-context/ownership
    포함 targeted 133 passed. Backend 479 passed / 1 skipped. Frontend 7 passed,
    lint 및 production build 통과. 최종 코드에서 `./scripts/check.sh` 실행했다.
    Deprecation warnings 17건은 기존 framework/SWIG 경고다.

17. **hardcoding/diff**: 새 admission/replay 경로에 회사명·2022/2023·6.9/9.3
    하드코딩 0. 숫자는 fixture/gold/report에서만 나온다. `git diff --check` 통과.
    기존 audit 대비 `search.py`, `evidence_bundle.py`, `evidence_requirements.py`,
    `fused_candidates.py`, `primitive_graph.py`, `metric_annotations.py`,
    `query_scope.py` SHA-256 모두 동일하다. 초기 사용자 변경은 reset하지 않았다.

18. **DB/hash**: READ ONLY REPEATABLE READ snapshot의 5개 table hash 전후 동일.
    documents=10, pages=75, chunks=231, analysis_runs=311, page_extractions=0.
    migration, revision 변경, OCR, embedding, LLM, live DB mutation은 없었다.
    사전·사후 JSON은 `dependency-admission-active-before/after-20261008.json`.

19. **새 false-complete**: 현대차 신규 false-complete 0: 기존 gold/source/bbox,
    scope/annotation/comparison/pack proof를 모두 만족한다. 삼성 false-complete
    **0 유지**, SK HOLD 유지. 기아 coverage=true/strict=false의 기존 review가
    유지되므로 전체 strict false-complete가
    0이라는 주장은 **확인할 수 없습니다**. 신규 오류 0과 구분한다.

20. **남은 blocker**: 신규 chunk의 vector embedding/rank가 fixture에 없으며
    embedding 생성이 금지되어 fresh full-hybrid 재평가는 할 수 없다.
    BM25 candidate/pack/coverage는 검증했다. live promotion은 수행하지 않았다.
    기아 기존 strict/manual review는 이 작업 범위에서 해결하지 않는다.

21. **다음 작업 후보**: 별도 승인 범위에서 신규 chunk의 실제 embedding을
    갖춘 offline full-hybrid fixture 평가. 기아 strict source/narrative review.
    기존 frozen corpus에 admission을 확대한다면 별도 regenerate+gold+pack audit.
    검색 parameter 변경은 필요성을 입증하기 전 제안하지 않는다.

## 필수 질문 답변

- 검증된 metric/context/unit/value span이 모두 admission되었는가? **예**, 현대차
  요청 chain의 period 및 annotation dependency까지 모두 원문 chunk에 포함됐다.
- unrelated span은 admission되지 않았는가? **예**, 신규 dependency segment는
  검증된 group의 명시적 dependency만이다. 기존 admitted segment는 보존했다.
- 연결/별도 scope가 분리 유지되는가? **예**, 별도 group/anchor/ownership이며
  selected pack은 연결 chain만 포함한다.
- searchable chunk가 실제로 생성되었는가? **예**, 연결 metric anchor를 포함해
  12개 searchable anchor가 생성됐다. 모든 proof를 searchable로 만들지 않았다.
- retrieval parameter 변경 없이 candidate로 들어왔는가? **예, BM25 rank=4**.
  신규 vector candidate 여부는 **확인할 수 없습니다**.
- selected pack까지 도달했는가? **예**, 연결 anchor pack 1건.
- coverage_complete=true가 정당화되는가? **예**, 두 gold cell과 annotation,
  scope, ownership, comparison, source coverage 및 selected proof가 모두 검증됐다.
- false-complete 0이 유지되는가? **현대차 신규 0**. 전체 strict 기준 0은
  기존 기아 review 때문에 **확인할 수 없습니다**; 삼성 false-complete는 **0 유지**.
