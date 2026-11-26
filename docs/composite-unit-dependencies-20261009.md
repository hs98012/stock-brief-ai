# Composite unit dependency admission — 2026-10-09

이번 변경은 검증된 unit의 source component를 보존하는 일반 계약이다. 삼성의
Paddle geometry threshold, parser 단위 사전, 검색 parameter 또는 fallback 순서를
변경하지 않았다. 신규 삼성 fixture만 offline으로 재생성했다.

1. **변경 파일**: `backend/app/unit_dependencies.py`(신규),
   `unit_validation.py`, `index_admission.py`, `table_evidence.py`,
   `backend/tests/test_unit_dependencies.py`(신규),
   `scripts/audit_index_admission.py`, `scripts/verify_composite_units.py`(신규),
   `api-contract.md`, `acceptance.md`, `qa-rules.md`, 이 보고서와 신규 audit artifacts.
   시작 당시 저장소에는 이미 다수의 수정/미추적 파일이 있었으며 reset하지 않았다.

2. **기존 처리**: `unit_candidates`는 source text의 literal multi-token 단위를
   찾고 `located`로 union bbox/offset을 만든다. `_cell_topology`는 같은 observed
   cell의 contributor만 합치고, `_primitive`는 union `unit` source span을 갖는다.
   `validate_unit`은 전체 surface와 value/cell 관계를 검증한다. 기존
   `dependency_groups`는 검증 graph node의 source spans를 복사했다.
   Atomic/composite의 component 목록과 semantic proof ID는 없었다.

3. **누락 원인**: frozen observation의 과거 fact는 unit=`원`, span=[33,34)였다.
   `fused_extraction`의 선택 fact→`fact_span` loop에서 이 suffix만 admission했다.
   따라서 frozen `index_segments`→`structured_spans`→chunk에 [31,32) `조`가 없다.
   현재 parser의 재도출은 `조 원` [31,34)을 정상 복원하며, graph comparison도
   통과한다. **현재 parser가 `조`를 dependency에서 다시 버리는 것은 아니다.**
   옛 frozen index가 새 primitive의 전체 unit proof를 담지 못하는 것이 직접 원인이다.
   기존 v1을 새 full-unit primitive로 재생성하면 union도 admission될 수 있지만,
   component membership/traceability를 명시적으로 보장하는 계약은 없었다.

4. **새 계약**: `verified-dependencies-v1` group에
   `unit_dependency.contract=semantic-unit-components-v1`을 추가했다.
   `kind=atomic|composite`, raw/canonical unit, full source span,
   ordered components, semantic unit ID, cell/table/row/context/ownership binding,
   검증 association을 보존한다. admission 권한은 기존 source-revalidated graph
   primitive에서 나온다. unverified fact의 token 존재만으로 group을 만들지 않는다.

5. **component 계산**: approved unit 범위와 같은 source stream의 원본 word
   offset을 교차시킨다. 각 교집합이 component이고 원래 word span/bbox도 따로
   보존한다. inline 단위는 unit substring의 offset만 취하고 bbox는 원래 관측
   bbox를 유지한다. whitespace gap은 typography로 허용하되 non-whitespace gap,
   overlap/중복 관측 또는 누락은 거부한다. 주변 N글자/line/cell 전체 확장과
   단위 문자열별 분기는 없다. full unit span과 모든 component를 admission한다.

6. **ownership/ambiguity**: 모든 component는 하나의 approved unit association,
   같은 source, unit cell 및 semantic unit ID에 묶인다. source에 명시된
   owner/table/row/context/cell/unit ID가 충돌하면 거부한다. 같은 original source
   token이 다른 semantic unit ID들에 귀속되면 해당 admission groups를 제외한다.
   기존 계약에서 허용한 verified header 공유는 동일 unit ID와 별도 metric
   binding으로 보존한다. proximity 자체는 admission 권한이 아니다.

7. **검색/proof**: group anchor의 기존 semantic search text와 물리적 page slice를
   구분한다. `final_text`, chunk content, 원문 quote/bbox를 덮어쓰지 않는다.
   `unit_is_covered`는 full unit span과 모든 component에 기존 `span_is_covered`를
   적용하며 `verified_table_candidates`에 연결했다. 검색 anchor에 단위 이름이
   보여도 원문 component chunk가 빠지면 candidate/evidence complete가 될 수 없다.

8. **테스트**: 신규 17개. `%` atomic, 두 component, 세 component,
   metric/value 비교 pack, 동일 proof/cell binding과 source 보존, verified header
   재사용을 검증한다. partial unit chunk, owner/row/table/context/unit membership
   충돌, duplicate observation, 다른 cell/row, unverified primitive, unrelated proof
   injection을 거부한다. `million USD`, `billion KRW`와 임의 3-component 단위는
   **이미 semantic 검증된 unit 이후의 일반 계약**을 테스트한다. 기존 lexical
   parser가 이 영어 단위를 새로 인식한다는 주장은 하지 않는다.

9. **삼성 source/component**: physical page 56, native raw=`조 원`, canonical=`조원`.
   unit cell=T0/r2/c1. `조`=[31,32), bbox=[162.471923828125,
   101.28958892822266,168.846923828125,111.18209075927734].
   `원`=[33,34), bbox=[170.47442626953125,101.28958892822266,
   176.84942626953125,111.18209075927734].
   semantic unit ID=`92745bf52f372d7a271ad4ba86579c2f924a4e235eb6b716cbc4392b56f026aa`.
   selected primitive IDs: 2022=`f5d73023d1ad98d1e69958a1`,
   2023=`a2ee30fa832fb7802e29bf5d`.
   Explicit metric-context ownership ID는 null이며 기존 unique source/cell/row
   association이 ownership proof다. null을 새로운 owner ID로 꾸미지 않았다.

10. **admission 전/후**: `조` false→true, `원` true→true.
    component segment=[31,32),[33,34), full segment=[31,34).
    overlapping proof slices는 기존 chunk construction으로 하나의 source chunk에
    포함된다: `12c59cc1-b7d8-57f2-832b-c680fe41d4c4`.
    전체 page fixture는 263→288 chunks, 67 verified groups, searchable anchor 59개.
    각 segment/group/chunk ID와 source binding은 final fixture 및 verification
    JSON의 `unit_matrix`에 기록했다. 다른 frozen corpus는 재생성하지 않았다.

11. **span coverage**: full `조 원` false→true. 두 component 각각 true이며 selected
    comparison pack의 union unit source span도 포함된다. whitespace 제외를 이용해
    `조` 누락을 complete로 인정하는 경로는 없다.

12. **candidate**: 삼성 verified table candidate 0→2. Native metric anchor
    BM25/RRF rank=13. 기존 verified candidate promotion에 의해 pack 후보가 된다.
    BM25/RRF parameter와 우선순위는 그대로다. 신규 vector embedding/rank는
    **확인할 수 없습니다**. 새 fixture 평가는 fresh BM25이며 full hybrid가 아니다.

13. **selected pack**: []→1개. anchor=`f6696670-b341-585b-95f6-4fe51c649fd5`,
    원문 [26,30) 영업이익. 검증된 두 native period primitive와 양방향 comparison,
    full unit source proof를 포함한다.

14. **coverage/strict**: coverage false→true. 기존 gold의 metric/period/value와
    **각 unit component의 원문 quote/bbox/offset**을 source 재검증된 admission
    group 및 selected primitive ID를 통해 정확히 대조했다.
    Component proof를 따라가는 offline exact-gold strict=true다.
    **기존 literal source_spans 목록만 비교하는 strict=false는 그대로 남는다**:
    gold는 `조`, `원` 개별 span이고 primitive는 `조 원` union이다.
    이를 숨기거나 gold를 수정하지 않았다. 새 verifier는 임의 substring/proximity가
    아니라 selected primitive의 재검증된 동일 unit proof만 exact-gold witness로
    사용한다. Production PASS 승격/기존 frozen 판정 덮어쓰기는 수행하지 않았다.

15. **Paddle diagnostic (A)**: 6.6 source→cell ratio=0.7546206987039663,
    기준 >0.80, 여전히 FAIL이다. 원본 word/cell bbox로 ratio를 재계산했다.
    `_cell_topology`가 row/column 검사 전에 token을 제외한다.
    **실제 evidence path (B)**는 native source와 기존 Paddle topology의 검증 chain이다.
    **최종 coverage (C)**는 그 native unit proof가 완전히 admission되어 true다.
    독립 verified candidate를 허용하는 기존 contract에 따라 Paddle 실패는 이
    native evidence path의 blocker가 아니다. 새로운 fallback 순서는 만들지 않았다.

16. **현대차/기아/SK**: 현대차 기존 PASS fixture는 source/embedding hash-bound
    cached 15 outcomes를 검증하고 freeze 유지한다. 새 embedding/검색 실행은 없다.
    기아 coverage=true/automatic strict=false/기존 manual review 유지. SK HOLD 유지.
    옛 pre-admission 현대차 corpus의 HOLD replay와 현재 PASS freeze는 구분한다.

17. **개발/POSCO**: frozen-rank 개발 combined 12/12, POSCO compound 1/1,
    기존 selected pack 20/20 exact equality가 통과했다. 결과는 final regression 및
    verification JSON에 기록했다.

18. **전체 검사**: `./scripts/check.sh` backend 496 passed/1 skipped,
    frontend 7 passed, lint/build PASS. admission/unit/component/scope/annotation/
    shared-context/ownership targeted 168 passed. 기존 deprecation warnings 17개.
    진행 중 source가 보완되어 중단된 첫 regression은 폐기하고 final code로 재실행했다.

19. **hardcoding/diff**: 신규 production dependency module에 회사명·예시 단위·
    삼성 숫자/좌표 하드코딩 0. 기존 unit parser 사전은 변경하지 않았다.
    `git diff --check` 및 수정 파일 trailing whitespace 검사 통과.
    geometry/graph/search/chunking/scope/annotation/fused-index 소스 hash는 이전
    READ ONLY baseline과 동일하다. 기존 사용자 변경은 보존했다.

20. **DB/hash**: enforced READ ONLY REPEATABLE READ snapshot 전/후 5개 모두 동일.
    documents=10, pages=75, chunks=231, analysis_runs=311, page_extractions=0.
    `composite-unit-active-before/after-20261009.json`에 전체 hash를 보존했다.
    DB write/migration/OCR/production embedding/LLM 호출은 없다.

21. **false-complete**: 기존 review policy를 유지한 frozen replay 0, 신규 삼성
    component proof 검증 0, cached 현대차 PASS를 포함한 effective 판정 0이다. 기존 literal-strict 표현 불일치는
    별도 공개한다. Component-aware 판정은 실제 gold component proof를 충족해야
    하며 coverage=true만으로 PASS하지 않는다. 결과는 final verification JSON 참조.

22. **남은 blocker**: 삼성 새 chunk의 vector embedding이 없어 새 full-hybrid
    성능은 확인할 수 없습니다. 기존 literal-list strict consumer는 composite
    proof 표현을 인식하지 않으므로 이 consumer의 판정은 false다. 이번 결과는
    source/component admission 및 offline proof 검증이며 production 승격이 아니다.
    기아 narrative manual review는 기존 상태로 남는다.

23. **다음 작업 후보**: 다른 strict audit consumer에도 동일한 verified unit
    component proof adapter를 적용하고 freeze 비교하기. 별도 허용 범위에서 실제
    신규 offline embedding을 이용한 full-hybrid 평가하기. Paddle raw OCR/cell bbox
    mismatch는 독립 진단 과제로 유지하기.

## 필수 질문 답변

| 질문 | 답변 |
|---|---|
| `조 원` 모든 source component 검증? | 예. selected native primitive의 unit association 재검증 및 gold component exact match. |
| 모든 component admission? | 예. `조`/`원` 각각과 full union 모두 보존. |
| Partial unit evidence의 false-complete 차단? | 예. full span+각 component coverage 필수, partial chunk negative test 통과. |
| Unrelated component merge 차단? | 예. 검증 범위/association/owner/proof membership 이외 span은 거부. |
| `span_is_covered=true`? | 예. 삼성 full unit 및 두 component 모두 true. |
| Selected pack 도달? | 예. native comparison pack 1개. |
| 삼성 coverage=true 정당화? | 예. native chain, comparison, exact source proof, 모든 required span의 pack coverage 검증. |
| Paddle 0.7546 failure 남음? | 예. threshold >0.80 그대로, FAIL. |
| 최종 evidence 판정의 실제 blocker? | 아니오. 기존 contract에서 독립 native proof candidate가 유효함. 기존 literal-list strict에는 별도 표현 blocker가 남음. |
| Review-aware false-complete 0 유지? | 예. Frozen replay 0, 신규 삼성 0, effective 판정 0. Literal-only strict 결과는 별도 보존. |
