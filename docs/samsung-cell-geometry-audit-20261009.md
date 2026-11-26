# 삼성 cell geometry READ ONLY 진단 — 2026-10-09

삼성 HOLD를 하나의 row/column geometry 실패로 설명하는 전제는 현재 재생 결과와 맞지 않는다. **Paddle 2023 값의 최초 geometry break는 cell 포함 비율 부족**, **현재 전체 requirement의 최초 break는 native `조 원` dependency의 frozen chunk 누락**이다. 두 경로를 합쳐서 보고하지 않는다.

1. **생성된 diagnostic 파일**

- `scripts/audit_samsung_geometry.py`: 원본 observation, frozen ranks, 실제 production 함수를 읽기 전용 재생한다. Threshold 변경/monkeypatch 없음.
- `evals/results/paddle/samsung-geometry-audit-20261009.json`: bbox/offset/ID, row/column 계산, 원본 pixel 좌표, graph, 후보 coverage, 주변 cell 및 PASS 비교.
- `samsung-geometry-verification-20261009.json`, `samsung-geometry-regression-20261009.json`, 검사/targeted/regression log, DB 전후/source hash JSON. 모두 동일 디렉터리.
- 원문 이미지 `samsung-geometry-page56-20261009.png`와 이 보고서. 기존 파일 변경 없음.

2. **삼성 challenge requirement**

`new-samsung-annual-pair`, physical page 56. 질의: `표의 2022년과 2023년 영업이익을 비교해줘.` 요구사항은 영업이익/money/두 연도 실제 숫자/반대 연도 comparison이다. structured_1=2022→2023, structured_2=2023→2022. Gold 원문 값은 43.4/6.6, 단위 조원. Query에 숫자를 hardcode하지 않는다.

PDF SHA-256 `488884ff61339ada35db6dd3c70316ee106d0d315aeac99bdf132474a88baca0`. 원본 PDF hash 확인, page 56 시각 검사 및 2023 chain의 native word bbox exact equality를 확인했다.

3. **source span/bbox 목록**

BBox는 PDF point, offsets는 저장된 final_text 기준 [start,end). 표시는 9자리, JSON은 원정밀도. OCR/native offset은 서로 다른 text 구간이다.

| Role / text | Source | Offset | Bbox | Candidate cell |
|---|---|---|---|---|
| metric / `영업이익` | native | [26, 30] | [43.866912842, 101.289588928, 69.141914368, 111.182090759] | T0/r2/c0 |
| unit / `조 원` | native | [31, 34] | [162.471923828, 101.289588928, 176.849426270, 111.182090759] | T0/r2/c1 |
| period / `2021년` | native | [327, 332] | [238.154403687, 72.939613342, 259.844421387, 82.832115173] | T0/r0/c2 |
| value / `51.6` | native | [339, 343] | [246.996932983, 101.289588928, 259.846679688, 111.182090759] | T0/r2/c2 |
| period / `2022년` | native | [432, 437] | [311.751892090, 72.939613342, 334.026885986, 82.832115173] | T0/r0/c3 |
| value / `43.4` | native | [444, 448] | [320.474456787, 101.289588928, 334.021697998, 111.182090759] | T0/r2/c3 |
| period / `2023년` | native | [551, 556] | [385.709411621, 72.939613342, 408.201904297, 82.832115173] | T0/r0/c4 |
| value / `6.6` | native | [600, 603] | [398.654449463, 101.289588928, 408.194458008, 111.182090759] | T0/r2/c4 |
| value / `6.6` | paddle_structure | [1472, 1475] | [395.614990234, 99.990371704, 411.612884521, 112.989120483] | none (expected T0/r2/c4) |

Native unit `조 원` [31,34) 는 `조` [31,32) + 공백 + `원` [33,34)의 원문/bbox union이다. Primitive union은 원문 bbox 확장이 아닌 literal multi-word span 표현이다. Native/Paddle metric row는 unique cell membership과 row group으로 증명되며 merged context가 없어 ownership/context ID가 null이다. 이것은 소유권 실패가 아니다. Table/row/column/cell_fact/row_group IDs 및 모든 반복 role은 diagnostic JSON 참조.

4. **cell bbox 목록**

Native `find_tables()` 결과는 저장 observation 및 현재 원본 PDF 모두 0개다. native table cell bbox는 **확인할 수 없습니다**. 사용한 topology/cell geometry는 Paddle HTML + cell_box_list이며, native text도 이 cell에 귀속된다. Structured 단계는 해당 bbox를 그대로 사용한다.

| T0 row/column | Text | Stored Paddle = structured bbox |
|---|---|---|
| 0/3 | 2022년 | [286.157165527, 71.022056580, 356.929290771, 83.934402466] |
| 0/4 | 2023년 | [357.091064453, 70.927635193, 408.113769531, 83.979652405] |
| 2/0 | 영업이익 | [41.519714355, 98.124855042, 146.302841187, 112.375556946] |
| 2/1 | 조원 | [145.445434570, 98.423385620, 205.097640991, 112.433647156] |
| 2/3 | 43.4 | [286.448699951, 98.343795776, 357.193389893, 112.330635071] |
| 2/4 | 6.6 | [357.285064697, 98.122879028, 408.330444336, 112.331680298] |

5. **row geometry 계산**

Production baseline은 font baseline이 아닌 bbox bottom(y1) 차이다. 적용되는 모든 row edge가 PASS다. 각 absolute 값/min height/ratio를 JSON 원정밀도로 보존했다.

| Edge | y overlap pt | overlap ratio ≥ .8 | bottom distance pt | min height pt | baseline ratio ≤ .2 | 결과 |
|---|---:|---:|---:|---:|---:|---|
| metric → value c2 | 13.935340881348 | 0.998784965728 | 0.016952514648 | 13.952293395996 | 0.001215034272 | PASS |
| unit → value c2 | 13.952293395996 | 1.000000000000 | 0.041137695312 | 13.952293395996 | 0.002948454003 | PASS |
| metric → value c3 | 13.986839294434 | 1.000000000000 | 0.044921875000 | 13.986839294434 | 0.003211724540 | PASS |
| unit → value c3 | 13.907249450684 | 0.994309661956 | 0.103012084961 | 13.986839294434 | 0.007364929474 | PASS |
| metric → value c4 | 14.206825256348 | 0.999860930338 | 0.043876647949 | 14.208801269531 | 0.003087990825 | PASS |
| unit → value c4 | 13.908294677734 | 0.992721987548 | 0.101966857910 | 14.010261535645 | 0.007278012452 | PASS |
| metric → unit | 13.952171325684 | 0.995853738361 | 0.058090209961 | 14.010261535645 | 0.004146261639 | PASS |
| value 2022 → value 2023 | 13.986839294434 | 1.000000000000 | 0.001045227051 | 13.986839294434 | 0.000074729324 | PASS |

6. **column geometry 계산**

| Edge | x overlap pt | overlap ratio ≥ .9 | left diff pt | right diff pt | min width pt | boundary ratio ≤ .1 | 결과 |
|---|---:|---:|---:|---:|---:|---:|---|
| period c2 → value c2 | 81.077926635742 | 1.000000000000 | 0.390365600586 | 0.141784667969 | 81.077926635742 | 0.004814696389 | PASS |
| period c3 → value c3 | 70.480590820312 | 0.996266870046 | 0.291534423828 | 0.264099121094 | 70.744689941406 | 0.004120937191 | PASS |
| period c4 → value c4 | 50.828704833984 | 0.996197766390 | 0.194000244141 | 0.216674804688 | 51.022705078125 | 0.004246634990 | PASS |

Raw source-span bbox 간 계산도 JSON의 source_span_geometry에 기록했다. Column predicate는 right-aligned 숫자/연도 text bbox가 아닌 **assigned cell bbox**에 적용된다. 수직으로 떨어진 header/value의 row FAIL 및 가로로 떨어진 metric/value의 column FAIL은 적용 대상이 아니며 chain 실패로 세지 않는다.

7. **chain edge별 판정표**

| Edge / native current rederivation | Row | Column | Ownership | 결과 |
|---|---|---|---|---|
| metric → unit `조 원` | PASS | N/A | unique same-row cell PASS | primitive PASS; frozen unit chunk FAIL |
| metric → 2022 value 43.4 | PASS | N/A | PASS | PASS |
| metric → 2023 value 6.6 | PASS | N/A | PASS | PASS |
| period 2022 → 43.4 | N/A | PASS | PASS | PASS |
| period 2023 → 6.6 | N/A | PASS | PASS | PASS |
| 2022 value ↔ 2023 value | PASS | N/A | same label/row/table PASS | graph comparison PASS (2 directions) |
| comparison → candidate → requirement | N/A | N/A | source coverage required | span_is_covered=False → candidates=0 → no_valid_candidate → HOLD |
| Paddle source 6.6 → cell r2c4 | not reached | not reached | **FAIL: zero qualifying cell** | token missing → primitive missing → graph pair unavailable |

8. **최초 failure predicate**

- **Paddle geometry 최초**: `structured_cells._cell_topology`, token assignment `overlap(cell_bbox, word_bbox) / max(1, area(word_bbox)) > .8`가 false. 따라서 `numbers=[]`, `len(numbers)!=1`에서 continue. `_association`의 row/column 검사에 도달하지 않는다. 분류 **I. SOURCE_CELL_COVERAGE_BELOW_MINIMUM**. E의 ambiguous owners 또는 F의 multiple owners는 아니다: qualifying owner가 0개다.
- **현재 row-association regression replay 전체**: current code로 native `조 원` primitive 재도출 및 graph 비교 2건은 PASS. `table_evidence.verified_table_candidates`의 `span_is_covered(...)` false가 최초 break. [31,34) unit 중 [31,32) `조`는 index_segments/chunk에 없고 `원` [33,34)만 있다. 분류 **I. SOURCE_CHUNK_UNIT_DEPENDENCY_MISSING**.
- **재도출 전 오래된 stored native facts**: unit=`원`/span [33,34)로 저장되어 `unit_validation.validate_unit`의 `unit_suffix_conflict`에서 먼저 탈락한다. 현재 함수는 literal `조 원`을 복원하지만 frozen chunks는 바뀌지 않는다. 이를 geometry 문제로 이름 붙이지 않는다.
- Target 외 다른 table row의 `row_band_not_complete_link` 거절은 요청 영업이익 chain의 최초 원인이 아니다.

9. **threshold 대비 observed delta**

Paddle cell membership: observed **0.754620698704**, required **> 0.800000000000**, delta **-0.045379301296**. Source area=207.952608835883, intersection=156.925342977047 pt².
OCR bbox는 cell 오른쪽을 3.282440185547 pt, 아래쪽을 0.657440185547 pt 벗어난다. Row/column ratio는 위 표 모두 PASS이며 실패 delta가 없다. 이것은 user 제시 row/column threshold가 아닌 **기존 별도 cell membership predicate**다. Threshold 변경 없음.

10. **topology와 geometry 관계**

Native chain: Paddle topology가 r2 영업이익/단위/값 및 c3=2022/c4=2023을 지지하고 geometry도 PASS. Paddle 6.6: HTML상 r2c4이나 recognized text bbox가 predicted cell 밖에 있어 **D**에 해당한다. 같은 topology의 geometry 표현 불일치라는 **A 후보**도 가능하지만 모델의 OCR/cell 경계 정확성은 추가 검증 없이 단정하지 않는다. Native topology 자체는 없음(C); raw text의 시각 관계는 명확하다.

11. **geometry가 변형되는 최초 단계**

Paddle raw pixel OCR region과 raw pixel cell이 이미 불일치한다. OCR region [1187,300,1235,339], cell [1071.9951782226562, 294.3969955444336, 1225.1513671875, 337.0274887084961].
Raw pixel ratio **0.754620362045** → PDF point ratio **0.754620698704**. decode_result/decode_tables는 동일 scale(x=0.333289792022343, y=0.333301232349699)를 적용하고 decode_page_result가 rotation=0 identity derotation을 fitz.Rect float32로 통과시킨다.
Max cell rounding delta 약 0.000014698482 pt. 저장된 2개 table 전체를 raw result에서 재도출해 float32 변환 후 **exact equality** 확인. Structured 단계 bbox clipping/padding/merged expansion/row-group union/column-group union 없음. 실제 mismatch는 scaling 이전 모델의 독립 OCR-region/cell-box 표현에서 이미 존재한다.

12. **parser artifact 여부**

Paddle의 text-region bbox와 cell_box_list 간 표현 불일치 후보는 확인했다. 모델 내부 bbox 생성 원인은 **확인할 수 없습니다**. 앱 decode/coordinate conversion/rounding이 원인이라는 증거는 없다. Native/OCR stream은 분리 처리하며 혼합 text bbox aggregation 때문에 발생한 사례도 아니다. Native의 별도 `조`+`원`에서 과거 unit suffix만 저장한 artifact와 frozen admission dependency 누락은 독립적인 원인이다.

13. **predicate 우회 시 false candidate 위험**

Pure arithmetic만 계산했고 후보 selection/threshold를 우회하지 않았다.

| Neighbor r/c4 | source 6.6 overlap ratio | target metric row PASS | header column PASS |
|---|---:|---|---|
| r1 / 258.9 | 0.000000000000 | False | True |
| r2 / 6.6 | 0.754620698704 | True | True |
| r3 / 15.5 | 0.040871100553 | False | True |

Cell membership 한 검사만 무시하고 row/topology/ownership을 유지하면 이 이웃들이 target row 후보가 되지는 않는다. Column만으로는 매출액 258.9/당기순이익 15.5도 PASS하므로 row ownership까지 무시하면 잘못된 숫자가 살아난다. 15.5 cell과 source 6.6은 4.0871% 겹치므로 임의 positive-overlap 매핑도 안전하지 않다. 그 밖의 table/fixture 전체 false candidate 부재는 **확인할 수 없습니다**.

14. **PASS fixture 비교**

현대차 PASS fixture의 source chain 3개 및 PASS `new-period-cashflow` 페이지의 승인된 table association 3개 비교. 후자의 세 association은 gold selected cashflow chain 그 자체가 아닌 같은 PASS 페이지의 승인된 geometry 표본이다. 현대차 gold/fixture 변경 없음.

| Fixture / metric / period | row overlap | baseline ratio | column overlap | boundary ratio |
|---|---:|---:|---:|---:|
| new-hyundai-mixed-pair / 영업이익률3) / 2021 | 1.000000000000 | 0.000000000000 | 1.000000000000 | 0.000000000000 |
| new-hyundai-mixed-pair / 영업이익률3) / 2022 | 1.000000000000 | 0.000000000000 | 1.000000000000 | 0.000000000000 |
| new-hyundai-mixed-pair / 영업이익률3) / 2023 | 1.000000000000 | 0.000000000000 | 1.000000000000 | 0.000000000000 |
| new-period-cashflow / 매출액 / 2028F | 0.891891992215 | 0.108108007785 | 0.980197867226 | 0.059406398323 |
| new-period-cashflow / 매출원가 / 2028F | 0.970588552116 | 0.058824242261 | 0.990099386855 | 0.029703652403 |
| new-period-cashflow / 매출총이익 / 2028F | 0.971428907777 | 0.057142184447 | 1.000000000000 | 0.039604265549 |

삼성 요청 cell의 row/column 수치는 정상 표본과 같이 PASS다. 특이점은 row/column ratio 분포가 아니라 Paddle 2023 source region의 cell membership이다. POSCO는 regression 1/1을 확인했으며 동일 primitive geometry 자료를 selected pack에서 제공하지 않아 POSCO ratio는 **확인할 수 없습니다**.

15. **production 변경 여부**

없음. 기존 production/test/evaluator/gold/fixture/계약 및 artifact 등 364개 파일 hash 전후 동일. 신규 diagnostic script/report/artifact만 추가. OCR/LLM/embedding 생성, DB write, migration, active revision 변경 없음. API/model 변경이 없어 계약 문서도 그대로 유지.

16. **전체 regression**

- 현대차 offline PASS: freeze된 15 cached outcome의 hash binding 및 strict/coverage proof 검증. Embedding/새 검색 호출 없이 기존 최종 PASS를 유지했다. 오래된 pre-admission frozen corpus의 현대차 HOLD replay는 별개 artifact로 보존한다.
- 기아 coverage=true / automatic_strict=false / 기존 manual review 유지. 삼성 coverage=false / strict=false / HOLD, SK HOLD.
- 개발 combined 12/12, POSCO compound 1/1, selected pack 20/20 exact equality, review-aware false-complete 0. Raw coverage=true/automatic_strict=false 1건(기아)은 그대로 분리 기록.
- `./scripts/check.sh`: backend 479 passed / 1 skipped, frontend 7 passed, lint/build PASS. Targeted index admission/annotation/query scope/shared context/ownership 133 passed. 기존 17 deprecation warnings. `git diff --check` PASS.

17. **DB/hash 상태**

Enforced READ ONLY REPEATABLE READ SELECT/rollback snapshot 전후 및 직전 offline-hybrid baseline 동일. Offline fixture IDs를 live DB IDs로 해석하지 않는다.

| Active table | Count | Before = after = prior SHA-256 |
|---|---:|---|
| documents | 10 | `90a528749fa287d8614fe5383fa6c8a37f67498e778206108d5796860565f8b4` |
| pages | 75 | `1cf7866151671415c87cc90b8a439c48969ebdc7a95611ba289fc041179cb575` |
| chunks | 231 | `bce2ec67ef0b99dca798891b76998fedc9cbbe969c01a749906619198033bf0e` |
| analysis_runs | 311 | `ce0bab08903d1fafb004361a493d67ff41ae332ca93563faf92715d5b70810fd` |
| page_extractions | 0 | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` |

18. **다음 구현 후보**

- 우선 native primitive의 **전체 literal composite unit dependency**가 admitted chunks에 포함되는지 검증하는 구조적 admission invariant를 검토한다. Source span `[31,34)`를 그대로 보존해야 하며 임의 수치/단위 보정은 하지 않는다.
- 별도 구현 범위에서 frozen unit metadata의 suffix-only 표현과 verified dependency admission 재생성을 검토한다. 삼성 geometry threshold 완화는 이 경로에 필요하지 않다.
- Paddle는 raw OCR region/cell mismatch를 별도 unresolved observation으로 기록하고, 독립 native source proof가 성공한 경우 이를 사용할지 검토한다. OCR bbox clipping 또는 topology만 믿는 우회는 제안하지 않는다.
- Production 적용/fixture regenerate/PASS 승격은 이번에 수행하지 않았다.

**필수 질문 답변**

| 질문 | 답변 |
|---|---|
| 최초 geometry failure predicate? | Paddle `_cell_topology`의 source→cell overlap/area > .8. Row/column failure는 요청 chain에서 재현되지 않음. |
| observed / threshold? | 0.754620698704 / >0.80, delta −0.045379301296. |
| source/native table 관계 명확? | 원본 PDF 시각/native words에서는 명확. Native table parser 결과 0개이므로 native cell topology는 확인할 수 없습니다. |
| structured geometry에서만 깨짐? | 아니오. Raw Paddle pixel 결과부터 OCR-region/cell-box가 불일치. Structured가 추가 변형하지 않음. |
| topology 지지? | Paddle HTML r2c4 및 r0c4=2023이 지지. Native word를 할당한 chain은 geometry도 통과. |
| threshold 완화 없는 구조적 방법? | 검증된 native composite unit 전체 span의 dependency admission 보존 후보가 있음. 이번에는 구현/승격하지 않음. |
| 현재 HOLD 정당? | 예. 현재 frozen chunks에 완전한 unit proof가 없고 Paddle 2023 primitive도 실패. 원문이 명확하다는 이유로 incomplete pack을 complete 처리할 수 없음. |
