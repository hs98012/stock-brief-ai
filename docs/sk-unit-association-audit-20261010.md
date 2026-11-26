# SK unit association READ ONLY 진단 — 2026-10-10

최초 구조 문제는 **혼합 선언의 단위 집합을 특정 metric/value에 귀속시키는 source-bound mapping 부재**다. 선언은 존재하지만 영업이익 금액 후보가 `원`/`조원` 두 개여서 유일하지 않다. Frozen admission 이전에 chain이 끊긴다. SK HOLD를 유지한다.

## 1. 생성 diagnostic 파일

- `scripts/audit_sk_unit_association.py`: 불변 observation과 frozen rank를 읽고 실제 production 함수의 locals를 trace한다. Counterfactual은 메모리에서만 실행하고 원래 함수를 `finally`에서 복원한다. 합성 후보는 graph/admission/retrieval/pack에 입력하지 않는다.
- `evals/results/paddle/sk-unit-association-final-20261010.json`: 전체 후보/span/bbox/topology, 값별 geometry, 실제 predicate, counterfactual, search trace, 모든 backend/app·frontend/app 파일 hash.
- `evals/sk-unit-association-reviewed-20261010.json`: 판정 및 회귀 요약과 artifact hash.
- `evals/results/paddle/sk-unit-regression-20261010.json`, `sk-unit-composite-verification-20261010.json`, check/targeted/replay 로그.

원본 fixture·gold·production을 변경하지 않았다. 기존 사용자 변경을 보존했다. 초기 diagnostic 결과와 final 결과를 덮어쓰지 않고 별도로 저장했다.

## 2. SK challenge requirement

`holdout-sk-compound-01`: HBM 고객 다변화 narrative와 물리 p2 표의 `3Q26F / 영업이익 / New 73.2 / Old 79.3 / 조원`을 함께 요구한다. Gold의 단위는 기대값이며 source association을 승인하는 근거로 쓰지 않았다.

현재 `requirements_for` 결과도 JSON에 보존했다. 표 requirement는 money family와 Old 비교를 요구하며, narrative requirement는 별도다. 2022/2023 비교 사례가 아니라 **동일 3Q26F의 New/Old 비교**다.

## 3. unit 후보 목록

연결 가능한 선언은 **1개 OCR region, lexical 단위 4개, 구조 경로의 eligible whole-word 후보 0개**다.

| raw / canonical / semantic | final_text span | bbox | page / topology | verification |
|---|---|---|---|---|
| 원 | [425,426) | U | p2 / T0 r0 c0 | literal source만 검증; association 미승인 |
| 조원 | [427,429) | U | p2 / T0 r0 c0 | 동일 |
| % | [431,432) | U | p2 / T0 r0 c0 | 동일 |
| %pt | [434,437) | U | p2 / T0 r0 c0 | 동일 |

U=`[187.3291473388672,469.6220397949219,246.66114807128906,480.95428466796875]`.
전체 raw 선언=`(원,조원, %, %pt)` [424,438), source=`paddle_structure`, confidence=94.93110775947571. 모든 substring bbox는 **동일 recognized text region의 bbox**이며 문자별 bbox가 아니다. 최근접 비교로 단위들을 구분할 수 없다.

Production cell ID/ownership ID/context ID/unit primitive ID는 생성되지 않아 null이다. `p2:paddle:0:r0:c0`는 보고서용 좌표 라벨이며 production ID가 아니다. 저장된 spatial observation의 table ID는 `9bc11f77b2c75d75507d4b5a`다. 각각의 target row/column ID와 source span은 전체 JSON에 보존했다.

p2 차트의 `(백만원)` [205,210), `(조원)` [211,215) 및 목표주가 표의 원/비율 표기는 target table 범위 밖이다. 다른 영역에서 단위를 가져오지 않았다. Native는 쉼표 한 word뿐이고 native table은 0개다. `ocr_words`의 동일 선언은 selected_words의 원관측이며 독립 후보로 중복 집계하지 않는다.

## 4. unit scope 분류

네 단위 모두 **table-level declaration**이다. 위치는 rowspan=2인 merged header cell T0/r0/c0이지만 특정 value column의 단일-unit header는 아니다. 영업이익 row-level, value cell-level, column-specific 또는 document-level 단위 증명은 없다. Header 위치와 table-level 의미를 서로 다른 경쟁 scope로 집계하지 않았다.

최초 ambiguity 분류는 **B. MULTIPLE_UNIT_CANDIDATES**, 구조 배경은 **F. MIXED_UNIT_TABLE** 및 **C. UNIT_SCOPE_AMBIGUOUS**다. A. UNIT_MISSING으로 판정하지 않는다. 단위 문자는 있고 귀속 mapping이 없다. Canonical 단위 자체는 네 개로 분명하며 ownership 충돌이나 component 유실이 최초 원인은 아니다.

## 5. period/value별 unit 후보

각 값에 대해 `_unit`을 따로 호출했으며 전부 None이다. 승인 unit/source/scope/ownership/proof는 없다. 값·지표·기간 OCR confidence와 source spans는 value_matrix에 개별 기록했다.

| period | facet | value | 후보 subset | associated unit |
|---|---|---|---|---|
| 3Q26F | New | 73.2 | 원, 조원 | 미결정 |
| 3Q26F | Old | 79.3 | 원, 조원 | 미결정 |
| 3Q26F | 변경율 | -7.6 | %, %pt | 미결정 |
| 2026F | New | 255.2 | 원, 조원 | 미결정 |
| 2026F | Old | 268.1 | 원, 조원 | 미결정 |
| 2026F | 변경율 | -4.8 | %, %pt | 미결정 |
| 2027F | New | 386.2 | 원, 조원 | 미결정 |
| 2027F | Old | 409.0 | 원, 조원 | 미결정 |
| 2027F | 변경율 | -5.6 | %, %pt | 미결정 |

기존 구조 parser는 New/Old만 자식 header로 취급하므로 실제 decision trace는 **6개**이고 spatial observation은 변경율을 포함한 **9개**다. 기간 간 단위 동일성을 가정하지 않았다. 현재 source로 금액 6개가 같은 scale인지 확정할 수 없다. 서로 다른 단위를 쓰는 것은 명시 source mapping/변환 proof가 있는 경우에만 별도 검증할 사항이다.

## 6. metric-unit geometry 관계

영업이익 metric [694,698)의 bbox=`[182.66258239746094,540.9486083984375,212.6619110107422,552.9474487304688]`.

네 후보의 bbox가 같으므로 모두 metric과 y-overlap=0, x-overlap ratio=0.8444443540199671, baseline 거리=71.9931640625pt다. 기존 baseline 및 column alignment 판정 모두 false, 양방향 containment도 false다. X축 일부 겹침만으로 unit ownership을 승인하지 않는다.

New 73.2와 unit은 row/column overlap=0, baseline 거리=71.65985107421875pt, baseline/column alignment=false다. Old와 다른 기간값의 비교도 value_matrix에 별도 계산했다. 하나의 공유 bbox이므로 geometry가 특정 canonical 단위를 지목하지 않는다.

## 7. topology 관계

Paddle raw HTML+cell boxes를 기존 `decode_tables`로 재도출한 결과가 저장된 두 table과 exact equality다. 실적표는 24×10이며 unit은 r0/c0(rowspan=2), metric은 r6/c0, 3Q26F New/Old는 r6/c1,c2, parent period는 r0/c1(colspan=3)이다.

선언은 unit cell에 overlap ratio=1.0으로 유일하게 속한다. Metric membership=0.9338430355851561, New=0.9512082180186181, Old=0.9486650824214438로 각각 기존 >0.8 기준을 통과한다. 따라서 target source→cell geometry 실패가 최초 원인이 아니다.

**Topology membership은 명확하지만 unit→metric/value 귀속 topology edge가 없다.** Geometry와 topology가 상충하는 현상도 최초 원인이 아니다. Header cell이 table에 속한다는 사실은 네 unit 중 하나를 row/column에 배정하는 proof가 아니다. Unit declaration의 merged rowspan은 현재 validator의 별도 제약 대상이지만 이번 실제 경로는 그 validator에 도달하기 전에 중단된다.

## 8. 현재 association 우선순위

- `_cell_topology`: `local or row_units or column_units or table_units`; cell > row > column/header > table. 첫 nonempty bucket의 길이가 1이어야 한다. Mixed declaration은 `literal_units`에서 제외돼 네 bucket 모두 빈 배열이다.
- `extract_native_facts`(Paddle adapter도 재사용): row > column > table이며 whole-token `UNIT_TOKEN.fullmatch`를 요구한다. Cell suffix 예외를 포함한 다른 처리가 있으므로 모든 parser에 동일 규칙이 있다고 주장하지 않는다.
- `spatial_tables._unit`: 단일 explicit row/header > value suffix `%`/`%p` > ratio row/column의 단일 `%`/`%pt` > 단일 money unit. 순서형 declaration 배정이나 최근접-unit 선택은 없다.
- `validate_unit`: 이미 선택된 unit의 surface/suffix/association을 검증한다. 테이블 순회 안에서 same-cell, same-row, column-header 조건 등을 검사하며 전체 후보를 다시 우선순위 정렬해 선택하는 함수가 아니다.

이번 진단에서 우선순위를 추가하지 않았다.

## 9. mixed-unit 여부

같은 table header에 금액 `원`/`조원`과 비율 `%`/`%pt`가 동시에 명시된다. USD-KRW, 매출액/영업이익, 영업이익률/Bit growth/ASP 증감율과 New/Old/변경율 subcolumn이 함께 존재한다. Mixed-unit declaration/table은 확인됐다.

Row 또는 변경율 column에 따라 서로 다른 unit family가 필요하지만 실제 `%`와 `%pt`, 금액 scale의 명시 mapping은 없다. Header unit과 개별 cell unit이 충돌하는 사례는 관측되지 않았다(개별 cell unit 없음). 특정 기간에만 적용되는 modifier/단위 footnote도 이 표와 저장 metadata에서 확인되지 않았다. 페이지/문서 전체에 그런 proof가 없다는 확장 주장은 하지 않는다.

## 10. source proof

로컬 원본 PDF SHA-256=`90672edb08c701b7b827f21823079d4e4239f27260ebf774c4e4d8ad61ccacd1`이 사전 gold와 일치함을 확인했다. **물리 p2를 직접 렌더해 시각 확인**했다(`/tmp/sk-unit-page2-20261010.png`). 표2 왼쪽 header의 `(원, 조원, %, %pt)`와 영업이익 New/Old 73.2/79.3이 실제로 있다. 해당 row/cell에 별도의 조원 표기는 보이지 않는다.

저장 native/Paddle/selected span과 raw HTML도 대조했다. 선언의 존재 proof는 충분하지만 **영업이익→조원 association proof는 부족**하다. Gold 기대값, 다른 차트의 `(조원)`, 숫자 규모, declaration 순서를 귀속 증명으로 사용하지 않았다. 현재 증명만으로 금액 scale을 확정할 수 없습니다.

## 11. 최초 failure predicate와 전체 chain

1. Source unit declaration은 존재한다. Paddle raw→decoded 24×10 table→metric/value/header cell membership까지 복원된다.
2. Structured 경로: `literal_units`의 `UNITS.fullmatch('원,조원,%,%pt')`가 false. `_cell_topology`의 `chosen=[]`; `len(chosen) == 1`이 **0 != 1**이라 line 500의 continue. `_association`, `_primitive`, `validate_unit`, unit dependency 생성에 도달하지 않는다. 실제 locals를 sys.settrace로 기록했다.
3. Spatial 경로: `_unit`에서 explicit=[], value suffix=false, New/Old rate branch=false, amounts=`['원','조원']`. `len(amounts)==1`이 **2 != 1**, line 51에서 None 반환. `extract_spatial_facts`가 unresolved `unit_ambiguous` observation을 기록하고 `if not unit: continue`로 fact 생성을 중단한다. 변경율은 rates=`['%','%pt']`로 동일하게 유일성 false다.
4. 재도출 unresolved observation 전체는 저장 metadata와 exact equality. 영업이익 validated fact=0, graph node=0, verified dependency group=0.
5. Frozen chunks에는 네 unit source substring 모두 coverage=false지만 **승인된 dependency가 누락된 사례가 아니다**. 이미 source stage에서 검증 unit이 없다.
6. Comparison candidate=0 → verified table candidate=0 → pack=[] → coverage=false → HOLD.
7. 독립 narrative 장애도 보존됐다. p1 AMD/NVIDIA/Rubin chunk의 frozen BM25/vector/RRF는 각각 20/105/35 및 19/100/33. Global pool 20 밖이다. Unit을 해결해도 narrative complete를 자동 보장하지 않는다.

원인 label을 단순히 unit association으로 남기지 않고 **복수 money scale을 가진 table declaration의 row/column attribution 부재**로 좁혔다.

## 12. association vs admission 구분

**A. source unit association 실패**다. Verified unit이 존재하는데 dependency admission이 빠진 B가 아니다. C. frozen chunk→retrieval 누락 또는 D. pack→coverage recognition 실패도 target table의 최초 원인이 아니다. Unit text의 frozen chunk 부재는 source rejection의 뒤 결과다.

삼성은 verified native `조 원` component proof가 존재했고 freeze에 `조`가 빠졌던 admission 사례다. SK에는 그 전제인 approved unit primitive가 없다.

## 13. 우회 시 false-complete 위험

Diagnostic-only 강제 생성 결과:

| 정책 | 검증 전 합성 후보 | 위험 | 기존 validator를 모두 적용한 승인 |
|---|---:|---|---:|
| 첫 단위 원 | 116 | 목표 73.2/79.3을 원으로 붙임; ratio/변경율도 원 | 0 |
| table-wide 조원 | 116 | 목표는 gold와 같아도 영업이익률/변경율/USD-KRW 등에 조원 부여 | 0 |
| 가장 가까운 단위 | 생성 안 함 | 네 단위 bbox가 동일해 거리 동률, 임의 tie-break 필요 | 해당 없음 |

첫 단위의 target는 unit validator에서 `unit_suffix_conflict`로 거부된다. **강제 조원 target 9개는 standalone validate_unit(tables=())이 통과**하지만, 원래 `_unit`을 복원한 `spatial_fact_valid`의 source-scope 재검증이 실패한다. 따라서 standalone unit approval만으로 안전하다고 주장하면 안 된다. 원래 spatial validator와 derived-fact exact match를 유지해야 한다.

위 116은 실제 candidate/pack PASS 수가 아니라 validator 전 합성 객체 수다. 실제 false-complete를 발생시켰다고 주장하지 않는다. 잘못된 우회가 귀속 재검증까지 무력화할 때 생기는 위험을 구체적인 row/value로 기록했다. Production gate와 gold는 변경하지 않았다.

## 14. 기존 PASS 사례와 차이

- 현대차: 기존 hash-bound cached offline PASS 15 outcomes freeze 유지. 성공 셀은 명시 value unit과 검증된 metric/row/period chain을 갖는다. 기존 geometry audit의 영업이익률 셀들은 row baseline/column alignment를 통과했다. 이번에 새 인덱스로 현대차를 재처리하지 않았다.
- 삼성: native 동일 row unit cell의 raw `조 원`→semantic `조원`이 하나로 승인되며 두 period primitive가 그 component proof를 공유한다. Full component admission을 검증하면 offline strict PASS. 기존 literal-list strict=false와 Paddle ratio=0.7546206987039663(필수 >0.80)는 유지했다.
- POSCO: frozen selected 영업이익 evidence의 `(십억원)` 선언 [2092,2097)은 단일 scale이다. 현재 개발/compound replay 1/1 유지. SK처럼 동일 금액 family에 두 scale을 선언하지 않는다.
- 기아: `십억원` column-header proof가 검증된 비교값에 연결된다. 현재 coverage=true지만 automatic strict=false/manual review 유지다.

Unit 후보의 양보다 **하나의 canonical unit과 특정 metric/value의 검증된 귀속**이 성공 사례의 차이다.

## 15. production 변경 여부

Production 변경 **0**. Audit 시작/종료의 모든 backend/app 및 frontend/app 파일 SHA-256 동일. Validator/association/threshold/OCR/search/RRF/embedding/LLM/DB write/migration 변경 및 호출 없음. 기존 API·data model 계약도 변경하지 않았다. Tests/check의 빌드 출력과 diagnostic artifact만 생성했다.

## 16. regression

- `./scripts/check.sh`: backend **496 passed / 1 skipped**, frontend **7 passed**, lint/build PASS.
- Targeted **210 passed**. 이 실행에 기존 admission/unit/component/scope/annotation/shared-context/ownership **168개 전부 포함**됐고 별도 collect-only로 168개임을 확인했다. 추가 42개는 structured cells/row association/primitive graph다.
- Current frozen-rank replay: 개발 combined **12/12**(10/10+고정 active controls 2/2), POSCO compound **1/1**, selected pack **20/20 exact equality**, review-aware false-complete **0**.
- 현대차 hash-bound offline PASS **15 outcomes**, 삼성 component-based offline strict PASS, 기아 manual review, SK HOLD 유지.
- 옛 frozen corpus의 삼성/현대차 HOLD 재생 결과와 새 offline PASS fixture를 분리해 보존했다. 새 모델/embedding 호출 없이 `verify_composite_units.py`가 effective state와 exact-gold proof를 검증했다.
- `git diff --check` PASS. 신규 audit/report/evaluation whitespace 검사 PASS. 기존 deprecation warning 17개.

## 17. DB/hash 상태

읽기 전용 `REPEATABLE READ READ ONLY` 트랜잭션의 기존 `hash_active_tables.py`로 active documents/pages/chunks/analysis_runs/page_extractions를 시도했다. Sandbox 밖의 허용된 localhost read 재시도도 **Connection refused**로 실패했다. Live 5개 table hash는 **확인할 수 없습니다**. DB를 기동하거나 쓰지 않았다. Offline replay의 historical hash equality는 live 검증으로 보고하지 않는다. 대신 frozen 입력과 모든 production file의 실행 전후 hash 동일성을 확인했다.

## 18. 다음 구현 후보

1. Mixed declaration을 source-bound 단위 집합으로 표현하고 현재 table/cell topology 및 unresolved reason을 보존하는 일반 metadata 계약을 검토한다. 이것만으로 PASS시키지 않는다.
2. 원본에 명시된 row/column unit assignment 또는 검증 가능한 별도 annotation이 있을 때만 mapping을 추가하는 proof 계약을 검토한다. 현재 p2 자료만으로 누락된 귀속을 자동 확정할 수 없습니다.
3. Cell-level 단위, single-unit header, mixed declaration을 구분하고 승인 단위마다 value/period/owner binding을 요구하는 diagnostic negative fixtures를 후속 구현의 acceptance로 삼을 수 있다.
4. Source proof가 끝내 없으면 HOLD를 유지한다. 선언 순서·숫자 규모·최근접·threshold 완화는 해결책으로 제안하지 않는다. Unit 이후에도 p1 narrative cutoff는 별도 과제다.

| 필수 질문 | 답 |
|---|---|
| SK 최초 unit failure는 정확히 무엇인가? | Structured: mixed whole-token fullmatch=false→chosen=0; Spatial: money candidates 원/조원 때문에 len(amounts)==1=false. 공통 구조 원인은 row/column별 scale 귀속 proof 부재. |
| unit 후보는 몇 개인가? | 선언 1개 안의 lexical 4개; money 후보 2개; eligible whole-word 0개. |
| 서로 다른 unit scope가 동시에 존재하는가? | Target에는 없음. 네 후보 모두 table-level; header 위치는 같은 선언의 topology. 다른 차트/표는 배제. |
| period/value마다 unit이 유일하게 결정되는가? | 아니오. 영업이익 9개 observation 모두 미결정. |
| mixed-unit table인가? | 예. 원/조원/%/%pt 혼합 선언. |
| source에서 unit proof가 충분한가? | 존재 proof는 충분; 특정 영업이익 value→조원 귀속 proof는 부족. |
| 문제는 association인가 admission인가? | A. source association. |
| threshold/heuristic 없이 구조적으로 해결 가능한가? | 집합·membership·미결정 상태는 구조화 가능. 현재 source만으로 PASS까지 해결 가능하다고 확정할 수 없습니다. 추가 명시 귀속 proof 필요. |
| 현재 HOLD는 정당한가? | 예. 단위가 유일하지 않고 narrative cutoff도 독립적으로 남음. |
