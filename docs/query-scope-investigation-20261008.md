# Live DB 무결성 및 현대차 canonical collision 조사 — 2026-10-08

## 1. Live DB hash 검증 결과 — 확인된 사실

사용자가 Docker를 켜고 나머지 서비스 기동을 승인한 후 기존 컨테이너만 시작했다. PostgreSQL 기존 PG_VERSION은 16이었다. `scripts/hash_active_tables.py`의 REPEATABLE READ / READ ONLY 트랜잭션으로 SELECT하고 rollback했다.

| 테이블 | 행 수 | SHA-256 (기동 전 baseline = PostgreSQL 기동 후 = 전체 서비스 기동 후) |
|---|---:|---|
| documents | 10 | `90a528749fa287d8614fe5383fa6c8a37f67498e778206108d5796860565f8b4` |
| pages | 75 | `1cf7866151671415c87cc90b8a439c48969ebdc7a95611ba289fc041179cb575` |
| chunks | 231 | `bce2ec67ef0b99dca798891b76998fedc9cbbe969c01a749906619198033bf0e` |
| analysis_runs | 311 | `ce0bab08903d1fafb004361a493d67ff41ae332ca93563faf92715d5b70810fd` |
| page_extractions | 0 | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` |

기동 시 PostgreSQL의 로그/WAL 및 OCR 모델 초기화 같은 런타임 활동은 발생할 수 있다. backend 원래 entrypoint는 `alembic upgrade head`를 실행하므로, 기존 컨테이너의 `/app/entrypoint.sh`를 기동 순간에만 uvicorn 명령으로 대체하고 즉시 원복했다. 저장소 entrypoint와 application source는 변경하지 않았다. 문서 처리·임베딩·생성 endpoint 요청, migration 실행, DB mutation은 하지 않았다.

backend, postgres, ocr-worker는 running/healthy를 확인했다. frontend는 running을 확인했으며 compose healthcheck는 없다.

## 2. Baseline 일치 여부 — 확인된 사실

`evals/results/paddle/shared-context-active-after-20261007.json`과 아래 두 결과의 5개 테이블 count/hash가 모두 동일하다.

- `evals/results/paddle/scope-investigation-live-20261008.json`
- `evals/results/paddle/scope-investigation-live-after-20261008.json`

검증 범위는 위 5개 테이블의 row JSON이다. DB 전체 테이블, schema, 파일 시스템, WAL의 동일성을 뜻하지 않는다. 현대차 PDF hash를 documents에서 READ ONLY 조회한 결과 0건이었다.

## 3. Collision candidate 비교 — 확인된 사실

Query: `표의 연결 기준 2022년과 2023년 영업이익률을 비교해줘.`

문서: `hyundai-sustainability-2024.pdf`, PDF SHA-256 `5a195c926ebcf638352ce90f90e2ffe9e454fa2de1fe8712055dcd5e4a925dd0`, physical page 97. Fixture document UUID `f18d3994-59ea-5ed5-ac53-6c170588b686`, page UUID `8973201a-08a1-59c6-a02f-aed7fd79c956`는 hash/page 기반 offline identity다. live DB PK가 아니다.

동일 native table index 1, table ID `2291360b61bd9ac726bf62ff`, bbox `[592.5204,130.7465,1116.8510,458.4894]`. row/column은 구조화 셀의 0 기반 index다. native tables는 2개, paddle tables는 0개다. annotation의 실제 `collision_spans` 전체는 아래 두 label이며, 기간별 값은 각각 해당 row의 값이다.

| Candidate | Raw label → canonical | Row / label column | Source scope | 2021 / 2022 / 2023 (%) | Context ID / metric ownership ID |
|---|---|---|---|---|---|
| 연결 | 영업이익률3) → 영업이익률 | 17 / 2 | native, 수익성지표 (연결 기준) | 5.6 / 6.9 / 9.3 | `a5d310833ef4cb375ed99772` / `e57298f7178d0603a4ea3a10` |
| 별도 | 영업이익률 → 영업이익률 | 19 / 2 | native, 수익성지표 (별도 기준) | 1.2 / 4.3 / 8.5 | `a405b86482c5e3b4d58e33d2` / `440b6c67984dd0cc2ea0af05` |

값 column은 2021=4, 2022=5, 2023=6이며 단위 column=3이다. 연결 raw span은 `[1341,1348)`, 별도는 `[1398,1403)`이다. 연결 label cell bbox `[683.1497,396.1272,773.8582,411.7178]`, 별도 `[683.1497,427.3083,773.8582,442.8989]`.

연결 candidate는 기존 annotation proof에 2022/2023 value facts가 있다. 별도 candidate는 canonical collision에 참여한 raw row다. 원문 값이 있다는 이유만으로 approved value chain 또는 coverage complete라고 판정하지 않았다. 순이익률3)/순이익률은 각 context의 다른 member이며 영업이익률 collision candidate는 아니다.

## 4. 연결/별도 원문 근거 — 확인된 사실과 한계

저장된 native 원문 관측의 병합 셀 column 1에 다음 literal이 존재한다.

- row 17–18 문맥: `수익성지표`, `(연결`, `기준)`. bbox `[634.9607,396.1272,683.1497,427.3083]`; source spans `[1335,1340)`, `[1363,1366)`, `[1367,1370)`.
- row 19–20 문맥: `수익성지표`, `(별도`, `기준)`. bbox `[634.9607,427.3083,683.1497,458.4894]`; spans `[1392,1397)`, `[1418,1421)`, `[1422,1425)`.

기존 context membership validator를 저장된 literal span/geometry에 적용한 결과 두 문맥 모두 approved/shared_metric_context_verified다. 연결 문맥은 영업이익률3), 순이익률3)에만 속하고, 별도 문맥은 영업이익률, 순이익률에만 속한다. 각 member의 row box와 ownership은 독립적이다.

column header는 연도이며 scope를 구분하지 않는다. `table_title`은 null이다. 페이지 상위 literal은 `지표 및 데이터`, `판매/재무`로 연결/별도를 단독 구분하지 않는다. `3)` footnote는 HMMR 처분 자산집단/중단영업 분류에 따른 비교 기간 금액 재작성 설명이며, 연결/별도 selector 자체의 근거는 병합 row context다.

원본 PDF 파일은 조사한 로컬 경로에서 확보하지 못했다. 이번 근거는 hash에 묶인 기존 관측 JSON의 original native PDF words/bbox/cells다. PDF를 다시 열어 시각적으로 검증한 결과는 **확인할 수 없습니다**. OCR·PDF 재처리·외부 다운로드는 실행하지 않았다.

## 5. 현재 데이터 모델에서 이용 가능한 증거 — 확인된 사실

- Native table cells에 scope literal과 context bbox, row/column 및 연도/단위/값 셀이 보존돼 있다.
- 기존 연결 facts의 `metric_context_ownership.context_membership`에 context_spans, context_id, members의 metric_span/row_bbox/metric_ownership_id가 보존돼 있다.
- 별도 문맥의 literal/geometry도 보존돼 있으며 기존 membership validator만으로 관계를 확인할 수 있다. 이 계산 결과는 조사 artifact에만 기록했다. 원본 observation의 승인된 value fact로 승격하지 않았다.
- `metric_identity`는 raw label/span과 검증된 footnote/canonical을 보존한다. `metric_identity()`는 같은 표의 canonical label 전체에 대해 collision을 계산하며 scope 구분을 입력받지 않는다.
- Query parser `table_requirements()`는 metric 이전 prefix를 마지막 날짜 뒤로 잘라낸다. 해당 query의 두 requirement는 entity=null이고 별도 consolidation scope 필드도 없다. 따라서 `연결 기준` 요구가 scope selector 입력으로 보존되지 않는다.
- 현대차 fixture는 document_unseen challenge다. Live documents 조회 0건 및 active page_extractions 0건으로, 이 근거를 live DB에 이미 저장된 구조화 scope라고 주장할 수 없다. 보존 여부는 offline artifacts와 현재 query-time metadata의 범위에서 확인했다.

## 6. Query scope selector 일반화 가능성 — 설계 판단 / 미구현

일반화 가능성이 있다. 명시적 query scope를 metric/entity와 독립적으로 보존하고, source로 검증된 context membership에 결합한 후, 해당 scope 안의 canonical 후보가 유일한지 확인하는 방향이다. 특정 회사명·값·row index를 selector 조건으로 사용하지 않아도 된다.

단, 지금의 annotation validator는 global collision이면 거부한다. Query에서 candidate만 필터링해도 이 거부가 사라지지 않으므로 단순 필터 하나로 HOLD를 해제할 수 있다고 단정할 수 없다. 향후 scope-aware authorization을 pack 재검증까지 일관되게 전달하는 별도 계약이 필요하다. Annotation proof/원본 raw identity 및 primitive geometry/unit/row ownership의 유효성은 계속 독립적으로 검증해야 한다.

scope 누락/충돌/여러 소유자/보존되지 않은 근거에서는 HOLD를 유지해야 한다. 연결/별도는 재무 범위이며 부문·지역·사업체 entity와 혼동하지 않아야 한다. scope와 footnote는 서로 다른 증거다.

## 7. 향후 구현 파일과 예상 범위 — 제안만, 변경 없음

1. `backend/app/evidence_requirements.py`: query scope의 literal span/정규화와 모호성 상태 보존; entity/기간/metric과 분리.
2. 신규 `backend/app/query_scope.py` 등 작은 모듈: 검증된 source context membership을 입력으로 명시적 scope match/unique candidate 판정과 audit reason 반환. 회사별 hardcoding 제외.
3. `backend/app/metric_annotations.py`: 현재 전역 collision을 우회하지 않으면서 scope별 authorization을 표현하는 계약 검토. 이번 조사에서는 annotation 로직을 변경하지 않았다.
4. `backend/app/table_evidence.py`, `primitive_graph.py`, `evidence_bundle.py`: 동일 scope 증명 전달 및 pack 재검증; cross-scope comparison 방지. geometry/shared ownership/unit 승인 규칙은 유지.
5. 대응 tests/evals: 명시 연결·별도, scope 미지정, 잘못된/충돌 scope, rejected raw competitor, 같은 scope 내 collision, 누락/변조 context, 기간별 scope 불일치와 기존 정상 coverage를 검증.
6. API/모델 계약이 바뀌면 `api-contract.md`, `acceptance.md`, `qa-rules.md` 함께 갱신. persisted scope 필드를 추가해야 하는지는 후속 설계에서 판단하며 현 조사로 migration 필요를 확정하지 않는다.

## 8. 남은 위험과 HOLD 해제 조건

현대차 HOLD 유지. 근거 부족으로 scope를 추측해서 선택하지 않았다. 현재는 source scope 구분 증거가 있지만 selector/authorization 계약은 미구현이다.

해제 조건은 명시 query scope 보존, source와 hash에 묶인 고유 membership 증명, 해당 scope 내 canonical 유일성, 요구된 2022/2023 primitive/value/unit/ownership 승인, 동일 scope 내 비교 및 evidence pack 재검증 통과다. 기존 정상 coverage 및 삼성전자 false-complete=0, SK하이닉스 HOLD 등 회귀를 확인해야 한다. 원본 PDF 접근이 가능해지면 페이지/병합 경계와 source hash를 직접 확인할 수 있다.

이번 작업은 새 조사 문서·증거 JSON·READ ONLY hash 출력만 만들었다. selector·production source·기존 eval 판정은 변경하지 않았으며 회귀 테스트를 새로 실행하지 않았다. 이전 418 passed / 1 skipped 결과는 이전 구현 단계 결과다.

상세 span/bbox/ownership과 입력 artifact hash: `evals/results/paddle/scope-investigation-evidence-20261008.json`.
