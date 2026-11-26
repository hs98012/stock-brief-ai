# 현대차 frozen coverage READ ONLY 조사 — 2026-10-08

최초 실패 계층은 **1. chunk construction 문제**, 최초 break point는 **B. CHUNK_MISSING**다. 저장된 `index_segments`가 연결 context·metric row·해당 unit/value·annotation proof를 admission하지 않아 frozen chunk에 들어가지 않았다. Ranking/cutoff나 pack/requirement 계산에 도달한 증거가 사라진 사례가 아니다.

## 1. 변경 파일 또는 diagnostic 파일

- `scripts/audit_hyundai_coverage.py`: 저장된 observation/rank를 재생하고 새 diagnostic JSON만 기록한다.
- `evals/results/paddle/hyundai-coverage-audit-20261008.json`: bbox/ID/offset 원정밀도, 16 chunk, requirement checks, 누락 spans.
- 이 보고서와 `hyundai-coverage-verification-20261008.json`: 검사·회귀·DB/code hash 비교.
- 기존 사용자 변경을 보존했다. Production/API/model/contract 변경은 없다.

## 2. Coverage pipeline

- Offline case: `new-hyundai-mixed-pair`, physical page **97**. Query: `표의 연결 기준 2022년과 2023년 영업이익률을 비교해줘.`.
- PDF identity hash: `5a195c926ebcf638352ce90f90e2ffe9e454fa2de1fe8712055dcd5e4a925dd0`. **원본 PDF를 직접 확인하지 않았다.** 원본 PDF 시각 상태는 확인할 수 없습니다.
- Stored page text hash: `59b4236b31d734cf6fc5611ebf2689fdfec6e3c2c56708e59893fee2ccda578a`.
- Offline document ID `f18d3994-59ea-5ed5-ac53-6c170588b686`, page ID `8973201a-08a1-59c6-a02f-aed7fd79c956`. Live DB의 document/page ID로 해석하지 않는다.
- source span → 저장된 `selected_words`의 exact quote/offset/bbox → native table index 1의 cell topology → 메모리에서 재도출한 structured primitive/ownership → comparison chain: 모두 검증된다.
- 저장된 native table, extracted span, structured cell은 서로 다른 증거 층이다. Native words/table은 이전 observation에 저장된 자료이며 이번에 PDF를 다시 파싱하지 않았다.
- frozen chunk → 기존 `index_segments`만 `structured_spans()`에 전달한다. Chunk UUID는 `uuid5(page_id, "start:end")`; page/document ID와 exact source offset/content를 유지하며 frozen rank trace의 16 ID/범위와 모두 일치한다.
- frozen retrieval candidate → `searchable()`은 chunk 시작 범위 안의 `paragraph` 또는 `fact_quote`를 요구한다. 16 chunk 중 2개만 searchable; 두 period chunk는 `fact_span`만 있어 제외된다.
- ranked candidate → 저장 BM25/vector rank로 RRF를 재구성한다. 실제 후보는 재무성과 두 chunk이며 필요한 comparison은 source-span coverage 검사에서 table candidate admission이 거부된다.
- selected pack → `[]`; evidence requirement → `structured_1`, `structured_2` 모두 `no_valid_candidate`; coverage → `false && false = false`.

## 3. Evidence provenance matrix

아래 bbox는 저장된 native word의 PDF point 좌표이며 표시만 소수 둘째 자리로 줄였다. JSON에는 원정밀도가 있다. 모든 항목의 source span은 존재하고 exact slice가 일치한다.

| Evidence | Page | Source span / bbox | Stored cell 위치 | Context / owner | Primitive ID |
|---|---:|---|---|---|---|
| 연결 | 97 | [1335,1340) `수익성지표` / [640.78, 400.92, 675.02, 410.63]<br>[1363,1366) `(연결` / [640.78, 411.92, 657.05, 421.63]<br>[1367,1370) `기준)` / [658.85, 411.92, 675.12, 421.63] | T1/r17/c1 | C / O | P22/P23 |
| 영업이익률 | 97 | [1341,1348) `영업이익률3)` / [688.97, 398.17, 727.04, 408.34] | T1/r17/c2 | C / O | P22/P23 |
| % | 97 | [1349,1350) `%` / [792.0, 398.63, 798.23, 408.34] | T1/r17/c3 | C / O | P22/P23 |
| 2022 | 97 | [718,722) `2022` / [906.61, 134.89, 921.75, 143.48] | T1/r0/c5 | C / O | P22 |
| 6.9 | 97 | [1355,1358) `6.9` / [929.99, 399.07, 940.95, 408.78] | T1/r17/c5 | C / O | P22 |
| 2023 | 97 | [723,727) `2023` / [971.78, 134.89, 986.97, 143.48] | T1/r0/c6 | C / O | P23 |
| 9.3 | 97 | [1359,1362) `9.3` / [995.19, 399.07, 1006.15, 408.78] | T1/r17/c6 | C / O | P23 |

C (context): `a5d310833ef4cb375ed99772`; O (owner): `e57298f7178d0603a4ea3a10`.
P22: `672b193483cb66144875bf39`; P23: `75f73004255faf87a002facb`.
Table proof ID: `2291360b61bd9ac726bf62ff`; row proof ID: `d3153329701704ac7aeaa87d`; row-group proof ID: `b200ec8a8f92ce3e9eab8fd3`.
Native raw cells에 별도 UUID 필드는 없다. 위 `T/r/c`는 저장된 cell 위치 키이며, context/owner/primitive proof ID와 구별한다.

| Evidence | 포함 chunk ID / chunk-local span | Frozen trace | Retrieval pool / rank | Selected pack | Source requirement 인정 / pack 인정 | 최종 bit |
|---|---|---|---|---|---|---|
| 연결 | 없음 / 해당 없음 | 없음 | 없음 / rank 없음 | 없음 | true / 미도달(false) | false |
| 영업이익률 | 없음 / 해당 없음 | 없음 | 없음 / rank 없음 | 없음 | true / 미도달(false) | false |
| % | 없음 / 해당 없음 | 없음 | 없음 / rank 없음 | 없음 | true / 미도달(false) | false |
| 2022 | `93349e03-6865-5051-a85e-4c76d81209c8` / [0, 4] | 있음 | 없음 / rank 없음 | 없음 | true / 미도달(false) | false |
| 6.9 | 없음 / 해당 없음 | 없음 | 없음 / rank 없음 | 없음 | true / 미도달(false) | false |
| 2023 | `6eb054f3-e22d-53dd-8508-1690ebe829a7` / [0, 4] | 있음 | 없음 / rank 없음 | 없음 | true / 미도달(false) | false |
| 9.3 | 없음 / 해당 없음 | 없음 | 없음 / rank 없음 | 없음 | true / 미도달(false) | false |

`Frozen trace`는 모든 frozen chunk의 진단 목록이다. 검색 가능 후보 목록과 동일하지 않다. Period가 trace에 있는 사실을 retrieval pool 포함으로 계산하지 않았다.

## 4. 각 evidence의 최초 break point

| Evidence | 최초 break | 구체 이유 |
|---|---|---|
| 연결 | B. CHUNK_MISSING | 해당 source span이 index_segments에 없고 frozen chunk와 겹치지 않음 |
| 영업이익률 | B. CHUNK_MISSING | 해당 source span이 index_segments에 없고 frozen chunk와 겹치지 않음 |
| % | B. CHUNK_MISSING | 해당 source span이 index_segments에 없고 frozen chunk와 겹치지 않음 |
| 2022 | C. FROZEN_CANDIDATE_MISSING | chunk는 있으나 fact_span 전용으로 searchable=false; BM25/vector/RRF 후보 없음 |
| 6.9 | B. CHUNK_MISSING | 해당 source span이 index_segments에 없고 frozen chunk와 겹치지 않음 |
| 2023 | C. FROZEN_CANDIDATE_MISSING | chunk는 있으나 fact_span 전용으로 searchable=false; BM25/vector/RRF 후보 없음 |
| 9.3 | B. CHUNK_MISSING | 해당 source span이 index_segments에 없고 frozen chunk와 겹치지 않음 |

Metric annotation marker `[1346,1348)` 및 definition 21개 word span `[1445,1547)`도 B다. 전체 definition 문장이 단일 span이라는 의미는 아니며 word별 원문 span을 검사했다.
기존 전체 replay taxonomy `evidence_selection`/selector reason `no_valid_candidate`는 결과 단계다. 이번 A–G 분류로 최초 원인 B를 좁혔다. Period의 C는 B와 별개로 관찰된 downstream admission 제한이며 전체 최초 원인은 B다.

## 5. 최초 실패 계층

**1. chunk construction 문제** — 구체적으로 frozen index admission 범위 누락이다. `source span → admitted index_segments → chunk` 사이에서 누락된다. Max-length split, RRF score, top-k cutoff가 최초 원인이 아니다.
기존 artifact에는 target row rejection 기록이 없다(`unresolved_cell_observations=[]`, `rejected_candidates=[]`). 따라서 과거 extraction 내부의 정확한 거절 분기는 확인할 수 없습니다. 이번에 확정한 것은 저장된 admission 범위의 누락이다.

## 6. Chunk 존재 여부

- 저장된 primitive/fact는 6개(재무성과 2021/2022/2023 × native/paddle)이며, 현재 메모리 cell 재도출은 45개다. 재도출해 검증한 영업이익률 chain이 저장된 frozen index로 자동 편입되지는 않는다.
- native scope merged cell의 저장 text `수익성지표\n(연결 기준)`과 selected-word context 3 spans는 보존돼 있다. Chunk에는 세 span 모두 없다.
- metric `[1341,1348)`, unit `[1349,1350)`, 6.9 `[1355,1358)`, 9.3 `[1359,1362)`는 chunk overlap가 0이다. Boundary가 중간에서 잘라낸 것이 아니라 해당 범위가 admission되지 않았다.
- 2022/2023는 각각 `[718,722)`, `[723,727)`의 별도 chunk다. 두 value는 chunk가 없어 동일 chunk 또는 source-linked chunk pair로 구성할 수 없다. Source primitive graph에서만 연결된다.
- 모든 evidence는 physical page 97에 있다. Page/table split에 의해 다른 page로 이동한 흔적은 없다.
- 16 chunk 모두 exact page slice와 char_start/end가 일치한다. Chunk 자체에는 page/document/offset/content만 있고 cell/context/owner ID는 page extraction에서 재도출한다. 이를 metadata 손실로 오인하지 않는다.

## 7. Frozen candidate 포함 여부

모든 frozen chunk 및 admission kind/rank를 아래에 기록한다. Source 단어가 같더라도 다른 unit/value/table/offset의 chunk는 대체 evidence로 인정하지 않는다. 필요한 native scope/metric/value/annotation을 담은 대체 chunk는 없다.

| Chunk ID | Page span | Quote | searchable | BM25 rank | Vector rank | RRF rank / score |
|---|---|---|---|---:|---:|---|
| `5b55a697-be28-5cbf-811b-3f2bc433ee7c` | [713, 717] | `2021` | false | — | — | — / 0.0000000000 |
| `93349e03-6865-5051-a85e-4c76d81209c8` | [718, 722] | `2022` | false | — | — | — / 0.0000000000 |
| `6eb054f3-e22d-53dd-8508-1690ebe829a7` | [723, 727] | `2023` | false | — | — | — / 0.0000000000 |
| `23756f82-63fb-52a2-875d-2e7aca627623` | [739, 740] | `원` | false | — | — | — / 0.0000000000 |
| `86670c2a-af2f-5631-983c-eb6a64902cae` | [741, 748] | `233,946` | false | — | — | — / 0.0000000000 |
| `80c67452-89d1-509a-9893-788a5b4f0ebf` | [749, 756] | `255,742` | false | — | — | — / 0.0000000000 |
| `3664c0f8-fd8c-54b5-a1d0-cf38dead0182` | [757, 764] | `282,463` | false | — | — | — / 0.0000000000 |
| `8516aa0f-4ef3-5961-b391-a63bdcd65e83` | [1116, 1120] | `재무성과` | true | 2 | 1 | 2 / 0.0325224749 |
| `7443184c-285a-58cf-b5ad-8d58c48762f3` | [2171, 2175] | `2021` | false | — | — | — / 0.0000000000 |
| `e69d095f-963d-54cc-befc-1d5b26d46ac4` | [2176, 2180] | `2022` | false | — | — | — / 0.0000000000 |
| `dd5c3da3-5fcb-5c02-ab0a-5bb9adffe9df` | [2181, 2185] | `2023` | false | — | — | — / 0.0000000000 |
| `ca5001a3-48ed-51a0-acee-bbbfde9cec30` | [2194, 2197] | `십억원` | false | — | — | — / 0.0000000000 |
| `eb495ebd-4a29-5621-b47b-218a699e4f1f` | [2198, 2205] | `233,946` | false | — | — | — / 0.0000000000 |
| `3ecbecd3-ff6d-5d9d-be69-d833219ff45e` | [2206, 2213] | `255,742` | false | — | — | — / 0.0000000000 |
| `da443bd6-bb39-50a4-b787-45c0bf5f82b8` | [2214, 2221] | `282,463` | false | — | — | — / 0.0000000000 |
| `68d82f87-f70c-5875-ac59-0ccb895ecdd7` | [2560, 2564] | `재무성과` | true | 1 | 2 | 1 / 0.0325224749 |

## 8. Ranking/cutoff 상태

- BM25/vector candidate cutoff=20, RRF k=60, presentation top_k=5, pack limit=5. 변경하지 않았다.
- Actual RRF pool은 2개로 cutoff 안에 모두 있다. 필요한 chunk가 cutoff 밖에 있는 사례가 아니다.
- BM25 raw score 및 vector raw cosine score는 frozen diagnostic에 저장되지 않아 확인할 수 없습니다. 새 embedding/검색을 실행하지 않았다. 위 RRF score만 frozen rank로 정확히 재구성했다. Rank 없는 chunk의 0은 RRF 기여가 없다는 뜻이며 BM25 score=0 또는 vector distance=0을 뜻하지 않는다.
- Period chunk는 `searchable=false`여서 ranking에 들어가기 전 제외된다. 따라서 `RANKED_OUT`으로 분류하지 않는다.

## 9. Selected pack 포함 여부

- pack `[]`, verified table candidates=0, selector proof candidate trace `[]`. RRF 두 후보는 selector row pool까지 오지만 영업이익률 fact가 붙어 있지 않다.
- 각 requirement의 options=0; 선택 점수 `(1, -global_rank)`를 받을 proof가 없다. Scope/metric/period coverage gain을 계산할 유효 옵션이 없으므로 선택 gain=0이다. 별도의 scope/metric/period 가중치 모델은 이 selector에 없다.
- 경쟁하는 유효 영업이익률 candidate 없음. 중복 제거·pack size·cutoff 때문에 빠진 것이 아니다. 반대 scope 값도 selected pack에 없다.

## 10. Requirement recognition 여부

| Requirement | Type | Expected canonical / scope | Period → comparison | Source value (fixture) | Source match / annotation / graph / pack-span validation |
|---|---|---|---|---|---|
| structured_1 | table | 영업이익률 / consolidated | 2022 → 2023 | 6.9 → 9.3 (%) | true / true / true / true |
| structured_2 | table | 영업이익률 / consolidated | 2023 → 2022 | 9.3 → 6.9 (%) | true / true / true / true |

Query requirement는 특정 숫자 6.9/9.3을 hardcode하지 않는다. `numeric_value_required=true`, `unit_family=ratio`, `unit=null`이며 표의 검증된 literal value/unit을 인정한다. 위 expected value는 fixture 확인값이다.
Source primitive P22/P23, scope context C, ownership O 및 annotation definition/marker proof는 JSON에 보존한다. `reporting_scope`, `metric_annotation`, `canonical_metric`, `metric`, `entity`, `period`, `unit`, `unit_surface`, `value`, `metric_row`, `metric_chain`, `comparison` checks는 두 방향 모두 true다.
`_fact_spans()`는 source proof 유효성을 확인하지만 chunk coverage와 같지 않다. Source match=true를 pack coverage=true로 계산하지 않는다. Pack에 chain이 있는 상태가 아니므로 F/G로 분류하지 않는다.

## 11. Coverage bit 계산 결과

- structured_1: `matched=false`, `evidence_id=null`, `reason=no_valid_candidate`, `checks=[]`.
- structured_2: 동일. Requirement에 연결된 selected item이 없으므로 각 bit=false.
- `_pack_for_document()`의 `bool(coverage) and all(matched)` 결과 false. Source chain=true, candidate=0, pack=[]인 결과와 일치한다. Accounting mismatch는 없다.
- 표의 7개 evidence bit는 별도 production bit 7개가 아니다. 두 requirement의 최종 bit를 해당 evidence에 투영한 audit 상태다.

## 12. 현대차 HOLD의 정확한 원인

연결 영업이익률 row를 증명하는 native spans는 observation에 있지만, frozen index가 admission한 spans에는 없다. 현재 query-time primitive/annotation/scope 검증의 성공은 frozen chunks를 확장하지 않는다. `verified_table_candidates()`가 모든 source/annotation span의 chunk coverage를 요구하므로 두 비교 fact 모두 후보 admission에서 거부되고 pack이 비어 HOLD다.

## 13. Production code 변경 여부

없음. OCR/chunk/search/RRF/threshold/selector/requirement 로직을 변경하지 않았다. OCR·embedding 생성·LLM 호출·DB mutation·migration은 수행하지 않았다. DB 조회는 별도의 READ ONLY hash 검증으로 한정했다. 기존 함수를 이용한 메모리 fixture 재도출/검증과 frozen-rank replay만 수행했다. 모든 기존 backend/app·alembic·frontend/app source 및 주요 계약 파일의 작업 전후 SHA-256은 같다.

## 14. DB/hash 상태

Live DB는 offline fixture와 별개다. READ ONLY / REPEATABLE READ transaction SELECT 후 rollback으로 조사 전후를 비교했다. 두 snapshot은 기존 query-scope baseline과도 동일하다. 현대차가 live DB에 없다는 사실은 이번 failure 판단에 사용하지 않았다.

| Table | Count | SHA-256 (before=after=prior) |
|---|---:|---|
| documents | 10 | `90a528749fa287d8614fe5383fa6c8a37f67498e778206108d5796860565f8b4` |
| pages | 75 | `1cf7866151671415c87cc90b8a439c48969ebdc7a95611ba289fc041179cb575` |
| chunks | 231 | `bce2ec67ef0b99dca798891b76998fedc9cbbe969c01a749906619198033bf0e` |
| analysis_runs | 311 | `ce0bab08903d1fafb004361a493d67ff41ae332ca93563faf92715d5b70810fd` |
| page_extractions | 0 | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` |

위 검증은 다섯 table의 canonical row JSON/count에 한정된다. DB 전체 파일/WAL 동일성 검증은 아니다.

## 15. Regression 상태

검증 JSON 참조. `./scripts/check.sh`: backend **464 passed / 1 skipped**, frontend **7 passed**, lint 및 production build 통과. 기존 17 deprecation warnings 유지.
Offline frozen-rank 전체 replay 완료: 개발 combined 12/12, POSCO fixed 1/1, 삼성 false-complete 0, SK HOLD, 기아 automatic strict=false/manual strict review 유지. Selected pack 20/20건이 직전 query-scope baseline과 exact JSON equality다. Classic-only recall은 기존 11/12다. Active control 두 건은 immutable baseline 재생이며 live retrieval 결과가 아니다.

## 16. 다음 구현 후보

별도 구현 작업에서 verified structured primitive의 scope/metric/unit/value 및 canonical annotation dependency spans를 index admission과 어떻게 연결할지 검토한다. 먼저 필요한 모든 span에 대해 chunk coverage invariant를 검증하는 작은 fixture부터 설계한다. Period의 fact_span-only searchable 제한은 source-linked dependency로 처리할지 검토 대상이다. Frozen fixture 재생성과 production 적용은 승인된 별도 작업 범위에서 수행한다. 이번 조사에서는 수정하지 않았다.

## 필수 질문 답변

| 질문 | 답변 |
|---|---|
| 연결 evidence는 frozen chunk 안에 존재하는가? | 아니오. Native context source만 존재. |
| 영업이익률 evidence는 존재하는가? | Source에는 영업이익률3) 및 canonical proof가 존재. Frozen chunk에는 없음. |
| 2022/6.9는 동일 또는 연결 가능한 chunk evidence로 존재하는가? | 아니오. 2022 chunk만 있으며 6.9 chunk 없음. Source primitive graph는 연결됨. |
| 2023/9.3도 존재하는가? | Chunk pair로는 없음. 2023 chunk만 있으며 9.3 chunk 없음. Source chain은 존재. |
| 필요한 evidence가 retrieval candidate에 모두 들어오는가? | 아니오. Period도 searchable=false로 pool에서 제외. |
| selected pack까지 모두 도달하는가? | 아니오. Pack=[]. |
| pack에 있는데 coverage만 false인가? | 아니오. 후보/pack evidence 자체가 없음. |
| coverage failure의 최초 원인은 정확히 어느 단계인가? | B. CHUNK_MISSING, source span → frozen admission → chunk의 admission 범위 누락. 최우선 계층: 1. chunk construction 문제. |
