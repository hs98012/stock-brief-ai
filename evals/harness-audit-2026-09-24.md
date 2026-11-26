# Paddle shadow harness 감사 — 2026-09-24

**판정: 핵심 provenance FAIL.** 이 감사에서 evidence-bundle 검색, UI, 생성 경로, 활성 데이터는 변경하지 않았다. 고정 12개는 이미 개발에 사용한 **개발 세트**이며 일반화 성능이 아니다.

| 항목 | 판정 | 실제 확인 결과 |
|---|---|---|
| Paddle 실행 출처·빌드 식별 | **FAIL** | 11개 성공 중 2개는 `unchanged_active_control`(삼성전자)이고 9개만 Paddle shadow다. 9개 fact의 `source=paddle_structure`, 물리 페이지, span/bbox는 검증됐다. v2의 21페이지 raw Paddle 결과가 v1과 동일하고 fallback 0페이지다. 그러나 v2는 `reused_paddle_version`으로 v1 관측을 재생했고, artifact/provenance에는 당시 worker image digest, 의존성 lock hash, PaddlePaddle 버전, 모델 파일 hash가 없다. 현재 worker의 버전·이미지를 과거 실행과 결부할 수 없다. |
| 검색 조건 | PASS(구현상 동등) | 활성·shadow 모두 Ollama `bge-m3` 1024차원, 공통 `rank_rows`, BM25+cosine+RRF(k=60), 후보 20/top-5, 동일 질문 텍스트, vector 사용 12/12. 활성은 PostgreSQL exact cosine(`enable_indexscan/bitmapscan=off`), shadow는 Python exact cosine이며 입력 corpus만 별도 revision이다. |
| 평가 입력·재현성 | PASS(개발 세트 한정) | 아래 입력/PDF hash를 고정해 기존 ready revision을 읽기 전용으로 2회 재검색했다. 원본 v2 및 두 재실행의 12개 active/shadow top-5 ID·page·quote·table/numeric evidence가 모두 동일했다. 원시 JSON 자체의 SHA 차이는 실행 시간 등 비검색 필드 때문이다. |
| 누수 | PASS(정적 검사 범위) | `backend/app`, migration, `ocr-worker`에서 대상 기업명·정답 수치·질문 ID의 분기 및 `evals/audit-cases.json` import가 발견되지 않았다. fixture import는 `scripts/` 감사 CLI에만 있다. |
| 미사용 holdout | **미완료** | `holdout-v1`에 기존 세 기업 외 기아·SK하이닉스 PDF 2개가 있다. 현재 고정 12개와 별개이고 사전 질문·gold가 아직 없으므로 이번 감사에서 성능을 채점하지 않았다. |

현재 실행 worker: PaddlePaddle **3.2.2**, PaddleOCR **3.3.2**, PaddleX **3.3.13**, image ID `sha256:ac162546f842374976fe7071de74c89a968101ba1ea5bd2cc367cd7013d43f38`. `ocr-worker/requirements.txt` SHA-256 `d88654cd286f56a686ecfc928ef385ddb423ba1f472175993807e973a32b7b2d`는 최상위 요구사항 hash일 뿐 transitive dependency/model lock이 아니다. 이 식별자들은 **현재 컨테이너**의 증거이며 과거 v1/v2 artifact에 기록되지 않았다.

입력 SHA-256: `audit-cases.json` `50874005814a50fd48fbe0908dfadb72bfe15d356092dbe8872fbcfab36c5601`; `paddle-reviewed.json` `fc90e90fc5e7e3b586300a31aa8c151d1e0288e5045ac8005e82dd995a8aa27b`; `audit-documents.json` `b164ea279d309991ccd3c7e2cdf4e9c07d6011d22597d065cb4be81416a4f2de`. 세 개발 PDF SHA-256은 각각 DB `b4448fe38a9dda167b9a65caa5c53bb82151487495bb47a6f7bab8ee994c8266`, POSCO `a21946429a6980e28e88ac8b4289b8789d57e912fdc20360f5d246d31395e364`, LG `3489541bb393c16772ba3ed5d31c3f34a035ba36a472eabc884fa6ad60209808`; 실행 전후 동일했다. 미사용 PDF는 기아 `c0ca0d99eaea7405dfa64a3b15aa89dfee1fe231bc67f1fa1cb72746c04a7344`, SK하이닉스 `90672edb08c701b7b827f21823079d4e4239f27260ebf774c4e4d8ad61ccacd1`.

활성 DB 정렬 JSON hash는 두 재실행 전후 모두 동일했다: `documents=90a528749fa287d8614fe5383fa6c8a37f67498e778206108d5796860565f8b4`, `pages=1cf7866151671415c87cc90b8a439c48969ebdc7a95611ba289fc041179cb575`, `chunks=bce2ec67ef0b99dca798891b76998fedc9cbbe969c01a749906619198033bf0e`(벡터 포함). `analysis_runs`, `page_extractions`, 이전 shadow hash도 동일하다. 재실행 원시 결과는 Git 제외 `evals/results/paddle/harness-repeat-{1,2}.json`에 있다.

남은 개발 질문의 원시 검색 근거: POSCO **p1** 원인 문단은 `char[622:934]`, “철강 부문 영업이익은 … 판가 상승 … 성수기 판매량 증가 …”가 한 문단에 있으나 BM25 45위/vector 5위/RRF **15위**여서 top-5 밖이다. POSCO **p2** 표 사실은 top-5 **1위**이며 행 `-철강` span `[1286:1289]`, 지표 `영업이익` `[1232:1236]`, 기간 `2Q26F` `[449:454]`, 단위 `(십억원)` `[2092:2097]`, 값 `424` `[1316:1319]`가 같은 물리 페이지 bbox에 연결된다. 따라서 남은 문제는 OCR 추출이 아니라 복합 질문의 근거 검색/packing이다. 현행 `compound_evidence_coverage@5`는 미구현·미측정이며, 기존 전역 top-5로는 이 질문의 두 근거를 함께 덮지 못한다.

최소 수정안: (1) 새 shadow 실행 **전에** worker image ID, Paddle/PaddleOCR/PaddleX 버전, 모델 파일 및 원본 PDF hash를 run manifest로 고정하고 각 페이지 raw 관측 SHA와 연결한다. 과거 artifact에 현재 image ID를 소급 기입하지 않는다. (2) verifier에서 active 대조군과 worker 유래 성공을 분리하고, 모든 worker 근거에 source/span/bbox/run manifest 일치를 fail-closed로 검사한다. (3) 기아·SK하이닉스의 질문과 물리 페이지 gold를 코드 변경 전에 고정한다. 이 무결성 게이트가 통과한 뒤에만 일반화된 evidence-bundle retrieval을 구현·평가한다.
