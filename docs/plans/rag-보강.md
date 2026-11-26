# RAG 면접 대비 보강 플랜

- 작성일: 2026-11-24
- 기준 커밋: `28061c6` (작업 트리에 미커밋 변경 다수 있음)
- 제약: 백엔드는 Python(FastAPI)을 유지한다. 실행하지 않은 테스트나 측정하지 않은 수치는 기록하지 않는다.
- 진행 규칙: 체크 안 된 첫 단계부터 진행한다. 단계를 끝내면 체크하고, 결정 사항과 측정 결과는 그 단계 아래 `기록:`에 적는다. `(마감 이후로 보류)` 표시가 있는 단계는 건너뛴다. 문서 순서대로 진행하며 번호 순서가 아니다.
- 목표(2026-11-25 추가): 12/6 지원 마감 전 검색 평가 신뢰도 향상과 면접 설명 정리.

---

## 0. 현재 구조 (코드 기준, 2026-11-24 확인)

전체 흐름: `POST /api/v1/documents` → 추출·청킹·저장 → `POST /api/v1/documents/{id}/embeddings` → `POST /api/v1/search` 또는 `POST /api/v1/analyses`

| 단계 | 위치 | 현재 동작 |
|---|---|---|
| 1. 문서 수집 | `backend/app/service.py:46` `ingest_document` | 확장자 `.pdf`, 크기 50MB 이하(`MAX_UPLOAD_BYTES`), `%PDF-` 서명을 검사한다. SHA-256으로 중복을 막고 원본을 `data/raw/{uuid}.pdf`에 저장한다. |
| 1-1. 텍스트 추출 | `backend/app/pdf_pipeline.py` `extract_pdf`, `fused_extraction.extract_page` | PyMuPDF native 텍스트에 Tesseract OCR(`kor+eng`, 300/200dpi, psm 6/3, 저신뢰 토큰은 psm 7로 재확인)을 결합한다. fact-fusion 결과는 `PageExtraction.provenance` / `table_facts`에 저장한다. |
| 2. 청킹 | `backend/app/chunking.py:11` `split_page`, `:41` `structured_spans` | 페이지 단위로 최대 1200자. 경계 우선순위는 `\n\n` > `\n` > `. ` > `다. ` > `요. ` > 공백이다. overlap은 없다. 원문을 바꾸지 않고 `char_start/char_end` 오프셋을 보존한다. fact-fusion 페이지는 승인된 `index_segments` 범위만 청크로 만든다. `section_title`은 항상 `None`이다. |
| 3. 임베딩 | `backend/app/embedding_service.py:20` `embed_document`, `embeddings.py` | 별도 API로 실행한다. Ollama `bge-m3`(1024차원)를 쓰며 배치는 100개다. 임베딩 입력은 `fused_index.retrieval_text`(청크 본문 + 표 fact 설명)여서 인용문과 검색 표현이 다르다. 청크마다 provider/model/dim을 기록하고, 이미 같은 설정으로 임베딩된 청크는 건너뛴다. |
| 4. 저장 | `backend/app/models.py`, `backend/alembic/versions/` (0001~0006) | PostgreSQL 16 + pgvector. 테이블은 `documents`, `pages`, `chunks`(vector 1024), `page_extractions`, `analysis_runs`이다. 테스트(SQLite)에서는 JSON으로 대체한다. 분석 경로는 `SET LOCAL enable_indexscan/bitmapscan = off`로 exact scan을 쓴다(`analysis_retrieval.py`의 주석에는 ARM HNSW 프로세스 종료 회피라고 되어 있다). |
| 5. 검색 | `backend/app/search.py:68` `hybrid_search`, `:76` `rank_rows`, `:54` `reciprocal_rank_fusion` | 필터링된 행 전체로 요청마다 메모리에서 `BM25Okapi`를 만든다. 토크나이저는 정규식(한글 연속, 영문, 숫자)이고 형태소 분석은 없다. pgvector cosine 결과 상위 `max(4k, 20)`개를 RRF(k=60)로 합친다. 그 뒤 행·지표·기간 조건이 검증된 표/수치 후보를 앞으로 올리고, 질문의 requirement가 있으면 evidence pack과 coverage를 판정한다. |
| 6. 답변 생성 | `backend/app/analysis_service.py:268` `analyze_document`, `analysis_retrieval.py:260` `collect_analysis_evidence`, `generation.py` | 질문, 질문+긍정어, 질문+부정어로 3번 검색해 후보 span을 고른다(품질 필터, 연도 일치, 중복·겹침 제거). JSON evidence packet 프롬프트(`_prompt`, :101)를 Ollama `gemma3:4b`, Gemini Flash, Fallback 중 하나로 생성한다. 생성 뒤에는 chunk_id 허용 목록, 어조·금지어, `grounded_card`, 원문 span 재검증을 거친다. 실패하면 `확인할 수 없습니다` 또는 `insufficient_evidence`로 끝난다. |
| 평가 | `backend/app/evaluation.py`, `scripts/evaluate.py`, `scripts/audit_retrieval.py`, `scripts/run_blind_evaluation.py`, `evals/*.json`, `holdout-v1/` | fixture 기반 케이스 평가(polarity·page·topic·금지 근거)와 sealed holdout 평가가 있다. |

### 이미 기록된 측정값 (출처 문서의 수치를 옮긴 것, 이 플랜에서 재측정하지 않음)

- `acceptance.md:104`: 생성 없이 고정 11질문/12근거의 recall@5가 6/12에서 7/12로 올랐다.
- `docs/sealed-holdout-v1-first-run-20261011.md`: 15문항 모두 HOLD, answerable 10개 중 충분한 근거 0개, False-complete 0, retrieval evidence recall@5 0/15. 같은 문서가 scorer 한계(value_status 필드 불일치, 다른 페이지의 scope proof)를 함께 적고 있다.

### 코드에서 보이는 면접 리스크 (측정 아님, 관찰)

- BM25를 요청마다 다시 만들어 문서 수가 늘면 비용이 선형으로 커진다. 지금은 단일 문서 범위 질의가 주 경로다.
- 한국어 토큰화에 조사 분리가 없어 `영업이익이`와 `영업이익`이 다른 토큰이 된다.
- 청크 overlap과 섹션 제목이 없다.
- 한 함수가 여러 일을 한다: `rank_rows` 약 120줄, `analyze_document` 약 200줄, `ocr_page` 약 100줄.
- 표준 retrieval 지표(hit@k, MRR)와 모드별(BM25 / vector / hybrid) 비교 결과가 한곳에 정리돼 있지 않다.
- 개발용 질문과 평가용 질문이 분리됐는지 문서로 확인되지 않는다(확인 안 됨).

---

## 1단계. 평가셋 목록화와 dev/test 분리 확정

- [x] `evals/*.json`, `evals/fixtures/`, `holdout-v1/`의 각 파일마다 용도, 질문 수, 생성 방법, 튜닝·디버깅에 쓰였는지를 표로 정리한다. 근거가 없는 항목은 "확인 안 됨"으로 적는다.
- [x] retrieval 평가용 dev셋(튜닝 허용)과 test셋(튜닝 금지)을 하나씩 지정하고 SHA-256을 기록한다.

**완료 조건**
- 이 문서 아래에 평가셋 표와 dev/test 지정, 해시가 기록되어 있다.
- test셋으로 지정한 파일이 튜닝에 쓰였다는 근거가 git 로그나 docs에 없음을 확인했거나, 쓰였다면 그 사실을 기록했다.

기록: (2026-11-24, 파일·docs·스크립트 참조만 확인했고 평가 실행은 하지 않음)

**git 추적 여부**: `evals/` 아래에서 git이 추적하는 파일은 `README.md`와 `fixtures/*.json` 5개뿐이다(커밋 `8367b65`). 나머지 평가 파일은 모두 미추적이라 git 로그로는 생성 시점과 사용 이력을 확인할 수 없다. 아래 "튜닝 사용"은 docs, acceptance, qa-rules, 스크립트 참조를 근거로 판단했다.

**질문/정답셋**

| 파일 | 문서 | 규모 | 만든 방법 | 튜닝·디버깅 사용 | 근거 |
|---|---|---|---|---|---|
| `evals/audit-cases.json` + `evals/pinned-gold.json` | 삼성전자(2025-07-09), LG, DB손해보험, POSCO홀딩스 | 11질문 / 12근거 단위 | 원본 PDF 시각 대조로 수동 작성(`audit-reviewed.json`의 method). pinned-gold의 purpose는 "prospectively fixed development-set" | **사용함** (개발셋) | `acceptance.md:104`의 recall@5 6→7/12 개선, `docs/e2e-improvement-checkpoint.md`의 "개발12/12" 회귀. 참조: `audit_retrieval.py`, `audit_rag.py`, `audit_shadow.py`, `verify_pinned_shadow.py`, `audit_unit_precision.py`, `verify_evidence_bundle.py` |
| `evals/fixtures/samsung-electronics-*.json` (5개) | 삼성전자 리포트 5개 | 17케이스(5+3+3+3+3) | 수동 작성. 생성 품질 평가용(polarity, page, topic). 작성 방법은 확인 안 됨 | 확인 안 됨. **단, 2025-07-09 fixture의 3문항(`second-quarter-miss`, `hbm-foundry-risk`, `carbon-reduction-insufficient`)은 audit-cases의 `old-miss`, `old-risk`, `old-none`과 질문 문장이 같다** | `README.md:216-250`의 `scripts/evaluate.py` 기준선 실행 기록(`README.md:227`) |
| `evals/holdout-cases.json` | 기아, SK하이닉스 | 2질문 | 확인 안 됨 | **사용함**. 이름은 holdout이지만 실패 진단에 쓰였다 | `sk-unit-association-reviewed-20261010.json`(case `holdout-sk-compound-01` 진단), `audit_bundle_holdout.py`, `audit_sk_unit_association.py` |
| `evals/primitive-graph-unseen-cases.json` | 삼성전자, 현대차 | 2질문 | 확인 안 됨 | **사용함** (회귀·테스트) | `backend/tests/test_row_association.py`, `audit_samsung_geometry.py`, `audit_unit_precision.py` |
| `evals/table-integrity-unseen-cases.json` | 확인 안 됨 | 2질문 | 확인 안 됨 | **사용함** | `audit_unseen_table.py`, `audit_unit_precision.py` |
| `evals/extraction-unseen-table-cases.json` | 확인 안 됨 | 3케이스 | 확인 안 됨 | **사용함** | `audit_unit_precision.py` |
| `evals/results/sealed-holdout-v1/` (`questions.json`, `gold.json`) | NAVER, 카카오, 셀트리온, 오리온, KT (5문서 29페이지) | 15질문(answerable 10, expected HOLD 5) / 15 fact | 저자가 원문을 검토해 봉인(2026-10-10). 독립 2차 검토는 NOT_PERFORMED | **최초 1회는 blind**(2026-10-10, 생성 없이 retrieval만). **그 뒤 실패 원인을 분석해 개발 피드백으로 썼다** | `docs/sealed-holdout-v1-failure-attribution-audit-20261011.md` 16항 "v1의 알려진 failure는 개발 피드백으로만 취급한다". 이어진 period/unit/scope binding 작업의 출발점이 이 분석이다(같은 문서 15항) |

**기록·판정 파일(질문셋이 아님)**: `audit-reviewed`, `retrieval-reviewed`, `shadow-reviewed`, `paddle-reviewed`, `pinned-*-reviewed*`, `ingestion-reviewed`, `metric-*`, `row-association-reviewed`, `shared-context-reviewed`, `unit-precision-reviewed`, `counts-reviewed-20261010`, `sk-unit-association-reviewed-20261010`, `blind-evaluation-v1-lock*`. 모두 위 질문셋을 실행한 결과를 사람이 검토한 기록이다.

**`holdout-v1/` 폴더 주의**: 폴더 이름과 달리 sealed holdout이 아니다. 들어 있는 PDF 5개(DB손해보험, POSCO홀딩스, 기아, LG, SK하이닉스) 중 3개는 `evals/audit-documents.json`에 `"blind_holdout": false`로 표시된 개발 문서다.

**dev/test 지정**

- **dev셋 (확정)**: `evals/audit-cases.json` (sha256 `50874005814a50fd48fbe0908dfadb72bfe15d356092dbe8872fbcfab36c5601`) + `evals/pinned-gold.json` (sha256 `bd6acaac1f8fb587e4e07bb38454f3aa1db5904770d34c2c205792eacfbe98e6`). 11질문 / 12근거 단위.
- **test셋 (지정 안 함, 아래 결정 참고)**: 지금 저장소에는 튜닝에 쓰이지 않았고 다시 실행해도 되는 셋이 없다.
  - sealed-holdout-v1 (manifest sha256 `e953979e5413db83d4355b205ddfacf6abdfbb8ceef4cfaa2e84d1a5f5527b57`, questions `a3f76125…`, gold `1c5ca16b…`. 오늘 다시 계산해 manifest와 일치함을 확인했다)은 두 가지 이유로 쓸 수 없다. 최초 실행 뒤 실패가 개발 피드백으로 쓰였고, `acceptance.md:211`, `:222`가 재실행과 재채점을 금지한다.
  - fixtures는 dev셋과 3문항이 겹치고 생성 평가용이라 retrieval 정답 단위가 없다.
  - `acceptance.md:152`에 "아직 보지 않은 문서 2개 이상으로 새 sealed holdout을 마련해야 한다"는 미완료 항목이 이미 있다.

**결정 (2026-11-24, 사용자)**: 당분간 dev셋만으로 진행한다. test셋은 지정하지 않는다.
- 이후 단계의 모든 수치는 "dev셋 기준"으로 표시하고, 일반화된 성능이라고 주장하지 않는다.
- 4단계와 6단계의 test셋 조건은 이 결정에 맞춰 고쳤다.
- 새 PDF로 holdout v2를 만들면 이 항목 아래에 추가하고, 그 뒤 측정부터 test 조건을 다시 적용한다.

## 2단계. 표준 retrieval 지표 측정 스크립트

- [x] 생성 없이 동작하는 읽기 전용 스크립트를 만든다(`scripts/audit_retrieval.py`를 참고). 케이스별로 정답 page/chunk 기준 hit@1/3/5, recall@5, MRR을 계산한다.
- [x] 지표 계산 함수의 pytest 단위 테스트를 먼저 작성한다(빈 결과, 정답 없음, 동순위).
- [x] 출력에 커밋, fixture 해시, 임베딩 모델, 실행 시각을 함께 남긴다.

**완료 조건**
- 지표 함수 테스트가 통과하고 `./scripts/check.sh`가 통과한다.
- dev셋으로 hybrid 모드를 실제로 한 번 실행했고, 그 수치와 실행 명령을 아래에 기록했다.

기록: (2026-11-24)

**만든 것**
- `backend/app/retrieval_metrics.py`: `unit_matches`, `first_match_rank`, `summarize`.
- `backend/tests/test_retrieval_metrics.py`: 12개 테스트. 빈 결과, 페이지 불일치, 동순위, cutoff 밖 순위, 빈 입력 0 나눗셈을 포함한다.
- `scripts/measure_retrieval.py`: 읽기 전용(`SET TRANSACTION READ ONLY`). exact scan으로 `audit_retrieval.py`와 같은 조건을 쓴다. 생성 모듈은 import하지 않는다. 출력에는 커밋, dirty 여부, cases/gold SHA-256, 임베딩 provider/model, top_k, 모드, 실행 시각을 남긴다.

**매칭 규칙**: 검색 결과가 gold 단위와 같은 페이지이고, 단위에 적힌 근거 조건을 모두 만족해야 일치로 본다.
- `literal_conditions`: 모든 문구가 quote에 있어야 한다(공백 무시).
- `table`: null이 아닌 필드가 모두 같은 table fact가 있거나, row_label과 value가 quote에 있어야 한다.
- `numeric`: 각 항목이 fact로 일치하거나 value가 quote에 있어야 한다.
- page만 보는 지표도 함께 출력한다.
- `verify_pinned_shadow.py`의 기존 판정(paddle proof와 bbox 검증 포함)과 규칙이 달라서, 기존 recall@5 7/12와 직접 비교하지 않는다.

**지표 정의**
- 대상: 답이 있는 9케이스, 12단위. 답이 없는 `old-none`, `db-none`은 제외한다.
- hit@k: 케이스의 첫 일치 순위가 k 이하인 비율.
- unit_recall@5: 단위별 일치 순위가 5 이하인 비율.
- MRR@5: 케이스별 1/순위의 평균. 5위 밖이면 0이다.

**검증**
- `pytest tests/test_retrieval_metrics.py`: 구현 전 import 오류로 실패, 구현 후 12 passed.
- `./scripts/check.sh` 통과: backend 734 passed, frontend 17 passed, lint, build.

**dev 측정 (hybrid, 1회 실행)**
- 실행 시각: 2026-11-24T14:20:39Z. 커밋 `28061c6`, 작업 트리 dirty.
- DB: 프로젝트 PostgreSQL 컨테이너 `stock-brief-ai-postgres-1`. 6주 동안 멈춰 있던 것을 `docker start`로 그대로 켰다(재생성 안 함, 볼륨 그대로). dev 문서 4개는 모두 `completed`이고 bge-m3로 임베딩되어 있었다. E2E DB(55433)에는 LG 문서만 있어서 쓰지 않았다.
- 원본 출력: `evals/results/retrieval-metrics-20261124/hybrid-dev.json`
- 실행 명령:
  ```bash
  DATABASE_URL="postgresql+psycopg://stock_brief:<docker-compose.yml 기본값>@localhost:5432/stock_brief" \
  OLLAMA_BASE_URL=http://localhost:11434 .venv/bin/python scripts/measure_retrieval.py \
    > evals/results/retrieval-metrics-20261124/hybrid-dev.json
  ```

| 지표 (dev셋 기준, 9케이스 / 12단위) | 근거 일치 | 페이지만 |
|---|---:|---:|
| hit@1 | 5/9 | 6/9 |
| hit@3 | 6/9 | 7/9 |
| hit@5 | 7/9 | 8/9 |
| unit_recall@5 | 8/12 | 11/12 |
| MRR@5 | 0.620 | 0.731 |

- 질의당 시간: 첫 질의(`old-miss`)만 2.27초이고 나머지 10개는 0.07~0.12초다. 첫 질의에는 모델 로딩이 섞였을 수 있지만 따로 확인하지 않았다.
- 11개 질의 모두 vector 검색을 사용했다(`vector_search_used=true`).

**근거 기준으로 놓친 단위 (4개)**

| 케이스 | 단위 | gold 페이지 | 관찰 |
|---|---|---|---|
| `lg-table` | CNS 지분가치 | 2 | top-5에 2페이지 결과가 아예 없다(페이지 기준으로도 실패). |
| `db-scan` | 2분기 순이익·컨센서스·상회율 | 1 | 1페이지 결과는 1위지만 quote 하나에 세 문구가 다 들어 있지 않다. |
| `lg-period` | 2026F 연간 전망 | 1 | 1페이지 결과는 5위지만 table fact나 quote가 조건을 채우지 못한다. |
| `posco-multi` | 철강 개선 이유 묶음 | 1 | 1페이지 결과는 3위지만 다섯 문구가 한 quote에 다 들어 있지 않다. |

**같이 발견한 것 (측정 아님)**: `audit-cases.json`의 `lg-fact` expected_pages는 `[1]`인데 `pinned-gold.json`의 같은 단위 page_number는 3이다. 이번 지표는 pinned-gold를 기준으로 계산했다.

**해석 한계**
- dev셋 9케이스, 12단위에서 1회 실행한 값이라 일반화된 성능이 아니다(1단계 결정).
- 매칭 규칙이 기존 `verify_pinned_shadow.py` 판정과 달라 기존 recall@5 7/12와 비교하지 않는다.
- 여러 문구를 요구하는 단위(`db-scan`, `posco-multi`)는 근거가 여러 청크에 나뉘면 이 규칙에서 실패한다. 청크 단위 매칭의 한계이며, 3단계 비교에서도 같은 규칙을 유지한다.

## 3단계. 검색 방식 비교 (ablation)

- [x] 같은 dev셋에서 BM25만, vector만, hybrid RRF, hybrid + 표/수치 후보 승격 4가지 모드를 측정한다. 모드 선택은 기존 기본 동작을 바꾸지 않는 옵션으로만 추가한다.
- [x] 모드별 지표와 질의당 지연 시간을 표로 남긴다.

**완료 조건**
- 4개 모드의 수치가 실제 실행 결과로 아래 표에 채워져 있다.
- 기본 검색 동작이 바뀌지 않았음을 기존 테스트(`test_hybrid_search.py` 등) 통과로 확인했다.

기록: (2026-11-24)

**코드 변경**
- `backend/app/search.py`: `hybrid_search`와 `rank_rows`에 `use_bm25: bool = True` 키워드를 추가했다. 평가 전용 스위치다. 기본값이 True라서 API와 분석 경로의 동작은 그대로다.
- `scripts/measure_retrieval.py`: `--mode`를 추가했다. 기본값은 2단계와 같은 `hybrid_rrf_with_promotion`이다.

| 모드 | 호출 옵션 |
|---|---|
| `bm25` | `rerank=False` + vector 비활성 provider. 기존 Ollama 불가 경로와 같고 embed를 호출하지 않는다. |
| `vector` | `rerank=False, use_bm25=False` |
| `hybrid_rrf` | `rerank=False` (BM25 + vector RRF k=60, 승격과 requirement 처리 없음) |
| `hybrid_rrf_with_promotion` | 기본값. `/api/v1/search`와 같은 경로 |

**테스트**
- `test_hybrid_search.py`에 3개를 추가했다. 기본 호출은 bm25_rank와 vector_rank가 모두 채워지고, `use_bm25=False`면 bm25_rank가 None이며, diagnostics 경로에서도 같다.
- 구현 전에는 새 테스트 2개가 `TypeError`로 실패했고 기본 동작 테스트는 통과했다. 구현 후 18 passed.
- 첫 `./scripts/check.sh`는 backend 736 passed, 1 failed였다. 실패한 `test_provider_consent.py::test_stream_all_modes_share_grounding_and_citations[EXTERNAL_WITH_CONSENT-False-gemini]`는 응답 JSON에 `'999'`가 없는지 검사하는데, 응답에 무작위 UUID가 들어 있다. 같은 파일을 6번 다시 돌려 6번 모두 통과했고 backend 전체도 737 passed였다. 원인은 UUID에 우연히 `999`가 포함된 기존 flaky 테스트로 추정하지만 재현은 하지 못했다. 이 테스트는 수정하지 않았다.
- 다시 실행한 `./scripts/check.sh`는 통과했다: backend 737 passed, frontend 17 passed, lint, build.

**측정 (dev셋 기준, 9케이스 / 12단위, 모드별 1회)**
- 실행 시각: 2026-11-24T14:22:48Z ~ 14:22:52Z. 커밋 `28061c6`, dirty. 모드를 순서대로 실행했고 check.sh는 그 뒤에 돌렸다.
- 원본 출력: `evals/results/retrieval-metrics-20261124/ablation-<mode>.json`
- 실행 명령: `.venv/bin/python scripts/measure_retrieval.py --mode <mode>` (환경변수는 2단계와 같음)

| 모드 | hit@1 | hit@3 | hit@5 | unit_recall@5 | MRR@5 | 페이지 hit@1 | 페이지 recall@5 | 페이지 MRR@5 | 질의 시간 중앙값 / 최대 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| bm25 | 6/9 | 6/9 | 6/9 | 7/12 | 0.667 | 8/9 | 11/12 | 0.889 | 0.015s / 0.148s |
| vector | 4/9 | 5/9 | 6/9 | 7/12 | 0.509 | 5/9 | 9/12 | 0.620 | 0.079s / 0.312s |
| hybrid_rrf | 4/9 | 5/9 | 6/9 | 7/12 | 0.509 | 6/9 | 11/12 | 0.731 | 0.089s / 0.158s |
| hybrid_rrf_with_promotion | 5/9 | 6/9 | 7/9 | 8/12 | 0.620 | 6/9 | 11/12 | 0.731 | 0.084s / 0.152s |

(hit@1~MRR@5의 앞 다섯 열은 근거 일치 기준이다.)

- `hybrid_rrf_with_promotion`의 결과는 2단계 측정(14:20:39Z)과 지표가 모두 같다. 같은 입력에서 2번 실행해 지표가 일치했다.
- 시간에는 질의 임베딩 호출(Ollama)이 들어 있다. bm25 모드는 임베딩을 하지 않는다.

**케이스별 차이 (근거 기준 첫 일치 순위)**

| 케이스 | bm25 | vector | hybrid_rrf | +promotion |
|---|---:|---:|---:|---:|
| `lg-period` | 1 | 4 | 3 | 3 |
| `posco-multi` | 없음 | 3 | 없음 | 1 |
| `posco-forecast` | 1 | 없음 | 4 | 4 |
| `old-miss`, `old-risk`, `lg-fact`, `db-table` | 1 | 1 | 1 | 1 |
| `lg-table`, `db-scan` | 없음 | 없음 | 없음 | 없음 |

**해석과 결정**
- 이 dev셋에서는 BM25 단독이 hit@1과 MRR@5가 가장 높았다. 차이는 `lg-period`, `posco-forecast` 두 케이스에서 나온다. vector 순위가 낮거나 없을 때 RRF가 BM25 1위를 아래로 밀어냈다.
- 표/수치 후보 승격은 `posco-multi` 한 케이스를 1위로 올려 hybrid_rrf보다 hit@5가 1 늘었다.
- 9케이스에서 한두 케이스 차이라 통계적으로 의미 있는 결론이 아니다. test셋이 없어서(1단계 결정) 일반화 여부는 확인 안 됨이다.
- **결정: 기본 검색 방식은 바꾸지 않는다.** RRF 가중치나 BM25 단독 전환 같은 조정은 dev셋 과적합 위험이 커서 test셋이 생긴 뒤에 다시 판단한다.
- 면접 설명 포인트: 한국어 금융 리포트에서는 정확한 수치와 기간 토큰(예: `2Q26`, `7,570억원`) 때문에 lexical 매칭이 강할 수 있다. vector는 의미가 비슷한 다른 기간·지표를 끌어올 수 있다. 이것은 이번 관찰에서 나온 가설이며 측정으로 확인하지 않았다.

## 4단계. 한국어 토큰화 개선 실험

- [x] BM25 토큰화 후보를 비교한다: 현재 정규식, 문자 bigram, 형태소 분석기(예: `kiwipiepy`, 순수 Python wheel 여부 확인). (형태소 분석기는 사용자 결정으로 제외, 아래 기록)
- [x] dev셋에서 좋아지고 기존 회귀 테스트가 통과할 때만 채택한다. test셋이 없으므로 일반화 효과는 "확인 안 됨"으로 기록한다(1단계 결정). 채택하지 않으면 이유를 기록한다.

**완료 조건**
- 후보별 dev 수치가 기록되어 있다. 채택한 경우 토크나이저 테스트가 추가되어 있다.
- 채택 여부와 근거가 기록되어 있다.

기록: (2026-11-24, 정규식과 문자 bigram만 측정. 형태소 분석기는 아직 측정하지 않음)

**코드 변경**
- `backend/app/search.py`: `char_bigram_tokenize`를 추가했다. 한글 연속 구간을 겹치는 2글자로 나누고, 영문과 숫자 토큰은 그대로 둔다. `hybrid_search`와 `rank_rows`에는 평가 전용 키워드 `bm25_tokenizer`를 추가했다. 기본값은 기존 `tokenize`라서 API와 분석 경로는 그대로다.
- `scripts/measure_retrieval.py`: `--tokenizer {regex,char_bigram}`를 추가했다(기본 regex).

**테스트**
- `test_hybrid_search.py`에 2개를 추가했다. 하나는 bigram 분할 결과를 확인한다. 다른 하나는 `영업이익이`가 들어간 청크를 질의 `영업이익`으로 찾는지 본다. 기본 토크나이저로는 결과가 없고 bigram으로는 bm25_rank 1이다.
- 구현 전 2개가 ImportError로 실패했고, 구현 후 20 passed.
- `./scripts/check.sh` 통과: backend 739 passed, frontend 17 passed, lint, build.

**측정 (dev셋 기준, 각 1회, 2026-11-24T14:29:15Z ~ 14:29:22Z)**
- 원본 출력: `evals/results/retrieval-metrics-20261124/tokenizer-<tokenizer>-<mode>.json`
- 실행 명령: `.venv/bin/python scripts/measure_retrieval.py --mode <mode> --tokenizer <tokenizer>`
- regex 대조군(`hybrid_rrf_with_promotion`)을 다시 측정했더니 지표가 2단계, 3단계와 같았다(같은 입력에서 3번째 일치).
- 대조군 측정의 첫 질의는 2.48초였다. Ollama 모델이 다시 로딩된 것으로 보이지만 확인하지 않았다. 중앙값은 0.082초다.
- vector 모드는 토크나이저와 관계없어 다시 측정하지 않았다.

| 모드 | 토크나이저 | hit@1 | hit@3 | hit@5 | unit_recall@5 | MRR@5 | 페이지 MRR@5 |
|---|---|---:|---:|---:|---:|---:|---:|
| bm25 | regex (3단계) | 6/9 | 6/9 | 6/9 | 7/12 | 0.667 | 0.889 |
| bm25 | char_bigram | 6/9 | 6/9 | 6/9 | 7/12 | 0.667 | 0.889 |
| hybrid_rrf | regex (3단계) | 4/9 | 5/9 | 6/9 | 7/12 | 0.509 | 0.731 |
| hybrid_rrf | char_bigram | 4/9 | 6/9 | 6/9 | 7/12 | 0.519 | 0.759 |
| hybrid_rrf_with_promotion | regex | 5/9 | 6/9 | 7/9 | 8/12 | 0.620 | 0.731 |
| hybrid_rrf_with_promotion | char_bigram | 5/9 | 7/9 | 7/9 | 8/12 | 0.630 | 0.759 |

- 근거 기준으로 바뀐 케이스는 `posco-forecast` 하나다. hybrid 두 모드에서 4위가 3위로 올랐다. bm25 단독은 케이스별 순위까지 regex와 같았다.

**결정: char_bigram은 채택하지 않는다.**
- 9케이스 중 1케이스가 한 단계 오른 것뿐이고 hit@5와 unit_recall@5는 같다. 개선이라고 볼 근거가 부족하다.
- bigram은 모든 질의의 BM25 토큰을 바꾼다. 짧은 한글 조각이 관계없는 청크와 겹쳐 오탐이 늘 수 있는데, 이 영향은 dev셋 9케이스로 확인할 수 없다. test셋도 없다(1단계 결정).
- `char_bigram_tokenize`와 `bm25_tokenizer` 옵션은 평가 전용으로 남긴다. 기본 검색에서는 쓰지 않는다.

**형태소 분석기 (`kiwipiepy`): 측정 안 함.** 현재 `.venv`(Python 3.14.2)에 설치되어 있지 않다. 설치하려면 PyPI 다운로드와 새 의존성 추가가 필요하다. backend Docker 이미지의 Python 버전과 wheel 제공 여부도 확인되지 않았다.

**결정 (2026-11-24, 사용자)**: 형태소 분석기는 측정하지 않고 4단계를 닫는다. 새 의존성은 추가하지 않는다. 형태소 분석기의 효과는 "확인 안 됨"이다. 면접에서는 조사 분리 문제가 있다는 것과 bigram 실험 결과, 형태소 분석기를 측정하지 않은 이유(의존성 추가 비용, dev셋 9케이스로는 판별력 부족)를 설명한다.

## 5단계. 청킹 파라미터 실험

- [x] `max_chars`(예: 600/1200)와 overlap 유무를 비교한다. 재처리와 재임베딩은 별도 DB나 shadow 경로에서만 하고 운영 DB 벡터는 바꾸지 않는다(AGENTS.md의 데이터 모델 계약).
- [x] 오프셋 보존(`page.final_text[char_start:char_end] == content`)이 유지되는지 테스트로 확인한다.

**완료 조건**
- 비교 수치가 기록되어 있거나, 비용 문제로 실행하지 않았다면 그 결정과 이유가 기록되어 있다.
- 기존 청크·벡터가 바뀌지 않았음을 확인했다.

기록: (2026-11-24)

**방법**
- dev 문서 4개는 모두 `page_extractions`가 없는 기존 업로드다. 그래서 저장된 `final_text`에 `split_page`만 다시 적용하면 된다(fact-fusion 페이지가 있으면 스크립트가 거부한다).
- `scripts/measure_chunking.py`는 DB를 읽기 전용으로만 연다. 메모리에서 다시 청킹하고, bge-m3로 새 청크를 임베딩한 뒤, `rank_rows(db=None)`의 exact cosine으로 순위를 매긴다. `shadow_revision.revision_rows`와 같은 SimpleNamespace 방식이다. 새 청크와 벡터는 DB에 저장하지 않는다. 별도 DB나 shadow 테이블도 만들지 않았다.
- `backend/app/chunking.py`의 `split_page`에 `overlap: int = 0`을 추가했다(평가 옵션). 다음 청크는 직전 청크의 마지막 `overlap`자 안에서 첫 공백 다음부터 시작한다. overlap은 `max_chars // 2`보다 작아야 한다. 기본값 0은 기존 출력과 같다.

**테스트 (`backend/tests/test_chunking.py`, 7개)**
- 검증 내용: overlap=0이 기존 출력과 같은지, 원문 오프셋이 보존되는지, 청크가 겹치고 단어 경계에서 시작하는지, 전체 텍스트를 덮는지, 잘못된 overlap을 거절하는지, 페이지 끝 공백, 같은 끝 위치 중복 방지.
- 처음 5개는 구현 전 실패, 구현 후 통과했다.
- **버그와 수정**: 처음 구현으로 overlap 측정을 돌렸더니 청크 수가 2,647개(1200/150)와 1,974개(600/100)였다. overlap 없이는 69개와 127개다. 페이지 끝이 공백이면 다음 시작이 한 글자씩만 전진했다. 이를 재현하는 테스트 2개를 추가했고(수정 전 실패) `_next_start`를 고쳐 통과시켰다. 잘못된 결과는 `evals/results/retrieval-metrics-20261124/invalid-overlap-bug/`로 옮겨 두었고 아래 표에는 쓰지 않았다.
- 수정 후 dev 문서 전체를 다시 청킹해 모든 span이 `final_text[char_start:char_end] == content`임을 확인했다. 청크 수는 1200/0=69, 600/0=127, 1200/150=76, 600/100=147이다.
- `./scripts/check.sh` 통과: backend 746 passed, frontend 17 passed, lint, build.

**대조군 검증**: 메모리에서 1200/0으로 다시 만든 결과가 3단계의 DB 기반 `hybrid_rrf`와 같았다. 청크 수가 같았고(10/21/11/27), 지표와 11개 질의의 순위·페이지 목록도 모두 같았다. 이 실험 경로는 DB 검색과 같은 결과를 낸다.

**측정 (dev셋 기준, 각 1회, 2026-11-24T14:34Z ~ 14:44Z)**
- 원본 출력: `evals/results/retrieval-metrics-20261124/chunking-<max_chars>-<overlap>-<mode>.json`
- 실행 명령: `.venv/bin/python scripts/measure_chunking.py --max-chars <n> --overlap <n> --mode <hybrid_rrf|hybrid_rrf_with_promotion>` (환경변수는 2단계와 같음)

| max_chars / overlap | 청크 수 | 모드 | hit@1 | hit@3 | hit@5 | unit_recall@5 | MRR@5 | 페이지 recall@5 | 페이지 MRR@5 |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1200 / 0 (현재) | 69 | hybrid_rrf | 4/9 | 5/9 | 6/9 | 7/12 | 0.509 | 11/12 | 0.731 |
| 1200 / 0 (현재) | 69 | +promotion | 5/9 | 6/9 | 7/9 | 8/12 | 0.620 | 11/12 | 0.731 |
| 600 / 0 | 127 | hybrid_rrf | 5/9 | 6/9 | 7/9 | 8/12 | 0.639 | 11/12 | 0.833 |
| 600 / 0 | 127 | +promotion | 6/9 | 7/9 | 7/9 | 8/12 | 0.722 | 11/12 | 0.833 |
| 1200 / 150 | 76 | hybrid_rrf | 4/9 | 6/9 | 7/9 | 8/12 | 0.541 | 11/12 | 0.726 |
| 1200 / 150 | 76 | +promotion | 5/9 | 6/9 | 7/9 | 8/12 | 0.615 | 11/12 | 0.726 |
| 600 / 100 | 147 | hybrid_rrf | 4/9 | 6/9 | 7/9 | 8/12 | 0.559 | 10/12 | 0.815 |
| 600 / 100 | 147 | +promotion | 5/9 | 7/9 | 7/9 | 8/12 | 0.648 | 10/12 | 0.815 |

**케이스별 차이 (+promotion, 근거 기준 첫 일치 순위)**

| 케이스 | 1200/0 | 600/0 | 1200/150 | 600/100 |
|---|---:|---:|---:|---:|
| `lg-period` | 3 | 2 | 3 | 3 |
| `posco-forecast` | 4 | 1 | 5 | 2 |
| `posco-multi` | 1 | 1 | 1 | 1 |
| `lg-table`, `db-scan` | 없음 | 없음 | 없음 | 없음 |
| 나머지 4케이스 | 1 | 1 | 1 | 1 |

**DB 무변경 확인**
- 모든 실험 세션은 `SET TRANSACTION READ ONLY`로 열었다.
- 실험 뒤 기본 측정을 다시 돌렸다(`after-step5-hybrid_rrf_with_promotion.json`, 14:44:23Z). 지표와 11개 질의의 retrieved chunk_id·순위·페이지가 2단계 첫 측정과 모두 같았다.
- 현재 `chunks` 테이블은 231행이고 md5(id, offset, content, embedding)는 `2ba2e96d49741d561b29e18dbd2178e0`이다. 실험 전에는 이 해시를 기록하지 않았으므로, 이 값은 이후 변경을 확인하는 기준선이다.

**해석과 결정**
- 이 dev셋에서는 600/0이 가장 좋았다(+promotion 기준 MRR@5 0.620 → 0.722, hit@1 5/9 → 6/9). 개선은 `posco-forecast`(4→1)와 `lg-period`(3→2) 두 케이스에서 나왔다.
- overlap은 1200과 600 모두에서 overlap 0보다 낫지 않았다. 600/100은 페이지 recall@5가 11/12에서 10/12로 떨어졌다.
- 놓치는 단위(`lg-table`, `db-scan`, `lg-period`의 2026F 단위, `posco-multi`의 문구 묶음)는 어떤 설정에서도 해결되지 않았다. 여러 문구가 한 청크에 다 들어 있어야 하는 단위는 청크 크기만으로 풀리지 않는다.
- **결정: 기본 청킹(1200/0)은 바꾸지 않는다.**
  - 이유 1: 9케이스 중 2케이스 차이다.
  - 이유 2: 청크 크기를 바꾸려면 모든 문서를 다시 청킹하고 다시 임베딩해야 한다. 그러면 citation 길이와 표시, 표 fact의 `source_chunk_ids`, fact-fusion 페이지의 `structured_spans`, 분석 근거 선택에도 영향이 가는데, 이번 실험은 검색 순위만 쟀다.
  - 이유 3: test셋이 없다(1단계 결정).
  - 600/0은 test셋이 생기면 다시 확인할 1순위 후보로 남긴다.

## 6단계. 답변 생성 근거 충실도 평가

- [x] 기존 `evaluation.py`의 `evaluate_case`와 `classify_failure_stage`로 `evals/fixtures/` 생성 평가를 한 번 실행한다(provider와 모델을 명시). fixtures는 dev셋과 3문항이 겹치고 튜닝 사용 여부가 확인 안 됐으므로 결과는 "dev 기준"으로 표시한다(1단계 결정).
- [x] citation 유효율, `insufficient` 케이스의 올바른 거절률, 실패 단계 분포(retrieval / selection / generation / validation)를 정리한다.

**완료 조건**
- 실행 ID, provider, 모델, 수치가 기록되어 있다. provider 오류(429/503 등)는 품질 실패와 구분해 기록했다.

기록:

- 2026-11-25 사용자 결정: 12/6 마감 이후로 보류. 9·10단계를 먼저 진행한다.
- 2026-11-26 사용자 결정: 보류를 풀고 지금 진행한다. provider는 Ollama `gemma3:4b`로 한다.

**추가한 것 (검색·생성·검증 코드는 바꾸지 않음)**
- `backend/app/generation_metrics.py`와 `backend/tests/test_generation_metrics.py`(13개 테스트)를 추가했다. 테스트를 먼저 쓰고 실패를 확인했다.
- `scripts/measure_generation.py`를 추가했다. 케이스 판정은 기존 `evaluate_case`를 그대로 쓴다. citation은 DB를 읽기 전용(`SET TRANSACTION READ ONLY`)으로 조회해 검증한다. 출력 폴더가 이미 있으면 실행하지 않는다. `--rescore RUN_DIR`은 저장된 응답으로 DB 검증만 다시 계산하고 API는 호출하지 않는다.
- citation 유효 조건: `source_chunk_ids`(없으면 `source_chunk_id`, 그것도 없으면 `chunk_id`)가 모두 해당 문서의 청크여야 한다. 청크 페이지가 citation 페이지와 같아야 하고, `quote`가 `page.final_text[char_start:char_end]`와 일치하며 `evidence_integrity.span_is_covered`를 통과해야 한다. 항목의 `evidence_chunk_ids`도 모두 citation에 연결돼야 한다.
- 실패 묶음: `retrieval_candidate_excluded`와 `retrieval_wrong_perspective`는 검색, `generation_not_selected`는 생성, `output_validation_removed`는 인용, `selected`인데 다른 검사에서 실패한 경우는 `judged_mismatch`로 둔다. `request_error` 중 HTTP 429/502/503/504와 timeout은 `provider_error`, 나머지는 `request_error`로 따로 센다.

**실행 (dev 기준, 1회)**
- 실행 ID `3ab763b5-9b58-468c-b574-e93fd887cba2`. commit `28061c6`, worktree_dirty=true.
- 응답에서 확인한 provider/model은 `ollama/gemma3:4b`이다. 요청은 `LOCAL_ONLY`, fallback은 꺼져 있었다.
- 실행 시각은 2026-11-26 03:40:14 ~ 03:45:04 UTC이다. 백엔드는 `.claude/launch.json`의 `rag-eval-backend-8001`로 띄웠고, 분석 17건과 trace 17건이 모두 200이었다.
- 결과 폴더는 `evals/results/generation-faithfulness-20261126/`이다. 실행 전후로 기존 `evals/results/`와 `test-v2/` 파일 715개의 SHA-256이 같음을 확인했다.

**측정 결과 (dev 기준, ollama/gemma3:4b)**

| 항목 | 값 |
|---|---|
| 케이스 판정 (`evaluate_case`) | pass 10 / fail 7 / skip 0 |
| citation 유효율 | 16/16 (citation이 있는 8케이스 모두 유효, 연결 안 된 evidence ID 0) |
| 근거 부족 케이스 올바른 거절 | 5/5. 다섯 건 모두 citation 0이고 `확인할 수 없습니다`가 노출됐다 |
| 답변 가능 케이스 잘못된 거절 | 4/12 |
| provider 오류 / 기타 요청 오류 | 0 / 0 |
| 실패 단계 분포 (7건) | 검색 7, 생성 0, 인용 0, judged_mismatch 0 |

- 검색 실패 7건은 두 종류로 나뉜다. trace 후보를 직접 확인한 결과다.
  - 4건(`2026-08-10` full-stack-positive, foundry-loss-negative / `2026-08-14` dram-hbm-pricing-positive, foundry-loss-negative)은 분석 후보가 0개였다. `insufficient_evidence`로 끝났고 생성 모델은 호출되지 않았다(selection 0). 이 4건이 위의 잘못된 거절 4건이다.
  - 3건(`2025-07-09` summary-positive, improvement-outlook / `2026-06-29` second-quarter-cost-burden)은 기대 페이지 1의 후보가 있었다. 하지만 후보 인용문에 fixture의 `expected_topic` 키워드가 없어서 분류기가 `retrieval_candidate_excluded`로 판정했다. second-quarter-cost-burden은 후보 1개가 positive 관점이라 기대한 negative 항목이 만들어지지 않았다. 앞의 두 건은 citation이 기대 페이지에 있었지만 topic 검사에서 실패했다.
- 한계: 실패 단계는 topic 키워드 일치에 의존한다. 그래서 키워드만 다른 경우에도 검색 실패로 셀 수 있다. 분류기는 고치지 않았다.
- 정정 기록: 처음 계산한 `report.json`/`summary.md`는 citation 유효율이 0/16이었다. 원인은 citation의 `chunk_id`를 DB 청크 ID로 본 것이다. 실제로는 파생 evidence span ID(uuid5)이고, DB 청크는 `source_chunk_ids`에 있다. 이 경우를 재현하는 테스트를 추가해 실패를 확인한 뒤 고쳤다. 같은 응답을 `--rescore`로 다시 계산해 `report-rescored.json`/`summary-rescored.md`에 저장했고, 생성은 다시 호출하지 않았다. 처음 파일은 그대로 두었다. 위 수치는 rescored 결과다.
- 참고(기록되지 않았던 이전 실행, 수치를 합산하지 않음):
  - `evals/results/generation-eval-20261124/`(Ollama): 7번째 케이스부터 백엔드에 연결되지 않아 pass 3 / fail 14로 끝까지 돌지 못했다.
  - `evals/results/rag-run-20261125/`: pass 10 / fail 7이고 실패한 케이스가 이번과 같다. 그 결과 파일에는 provider와 모델이 없어 "provider 확인 안 됨"이다.

## 7단계. 설명 가능한 코드 구조로 정리 (동작 변경 없음) (마감 이후로 보류)

- [ ] `rank_rows`를 후보 생성 → 융합 → 승격 → evidence pack → 결과 조립 단계 함수로 나눈다.
- [ ] `analyze_document`를 근거 수집 → 프롬프트 → 생성 → 검증 → citation 조립 → 저장으로 나눈다.
- [ ] 리팩터링 전후 테스트가 모두 통과하는지 확인하고, 2단계 스크립트의 dev 수치가 같은지 확인한다.

**완료 조건**
- `./scripts/check.sh`가 통과한다. 분리한 각 함수는 50줄 이하이다.
- 리팩터링 전후 dev 지표가 같다(실행 결과로 기록).
- API·데이터 모델은 바꾸지 않는다. 바뀌면 `api-contract.md`, `acceptance.md`, `qa-rules.md`를 갱신한다.

기록:

- 2026-11-25 사용자 결정: 12/6 마감 이후로 보류. 9·10단계를 먼저 진행한다.

## 9단계. 평가셋 확대와 dev/test 분리

- [x] **재사용 조사**: `sealed-holdout-v1`(questions/gold와 PDF 5개)과 `holdout-v1/` PDF 5개 각각에 대해 dev 겹침, 튜닝·디버깅 사용 근거, acceptance 금지 조항을 파일 경로와 줄 번호로 기록한다. 판정은 `재사용 가능`, `불가`, `확인 안 됨` 중 하나로 적는다. 사전 근거: 1단계 표, `acceptance.md`의 sealed v1 재실행·재채점 금지, `docs/sealed-holdout-v1-failure-attribution-audit-20261011.md` 16항.
- [x] **불가로 판정하면 (사용자 결정 2026-11-25)**: 사용자가 아직 수집하지 않은 실제 증권사 리포트 PDF 2개 이상을 제공한다. 가짜 PDF를 만들거나 임의로 다운로드하지 않는다. 기존 문서와 SHA-256이 겹치지 않는지 확인한다.
  - 2026-11-25 사용자 결정 변경: 사용자가 Claude에게 직접 받아 오라고 요청했다("너가 해줘"). 로그인이 필요 없는 네이버페이 증권 리서치(종목분석)에서 실제 발간 리포트 4개를 받아 `test-v2/`에 넣었다. 커밋하지 않았다.

  | 파일 | 회사(코드) | 증권사 | 발간일 | 쪽 | SHA-256 앞 16자리 |
  |---|---|---|---|---|---|
  | `20261125_CJ제일제당 (097950)_하나증권.pdf` | CJ제일제당(097950) | 하나증권 | 2026-11-25 | 4 | `2fa66cb2778841d2` |
  | `20261125_한세실업 (105630)_유진투자증권.pdf` | 한세실업(105630) | 유진투자증권 | 2026-11-25 | 6 | `827057d955459ab9` |
  | `20261125_솔브레인 (357780)_교보증권.pdf` | 솔브레인(357780) | 교보증권 | 2026-11-25 | 4 | `4dc8faad00e8156b` |
  | `20261125_이수페타시스 (007660)_DS투자증권.pdf` | 이수페타시스(007660) | DS투자증권 | 2026-11-25 | 4 | `42d377f08f587293` |

  - 확인한 것: 기존 10개 PDF(`holdout-v1/` 5개, `sealed-holdout-v1/documents/` 5개), `evals/*.json`에 적힌 SHA-256, 저장소의 다른 모든 PDF와 해시가 겹치지 않는다. 네 회사 이름은 `backend`, `scripts`, `evals`, `docs`에서 검색되지 않는다. PyMuPDF로 모든 쪽에 원문 텍스트가 있고 `find_tables()`가 표를 찾는 것을 확인했다(실적 추정표, 재무제표 포함).
- [x] **질문 유형 표시**: dev(기존 11질문)와 test 질문 모두에 `query_type`을 붙인다. 값은 `exact_numeric_period`(정확 수치·기간 질문)와 `semantic`(의미 풀이 질문) 둘이다.
  - 판정 기준: 질문이 특정 수치, 단위, 기간 토큰의 값을 요구하면 `exact_numeric_period`, 이유나 위험, 설명을 요구하면 `semantic`이다. 둘 다면 주된 요구를 기준으로 하고 그 이유를 적는다.
  - 기존 dev 파일(`audit-cases.json`)은 해시가 고정돼 있으므로 고치지 않는다. 유형은 별도 파일 `evals/query-types-dev.json`에 둔다.
- [x] **정답 근거 초안과 승인 절차**:
  1. Claude가 `evals/drafts/<set>-draft.json`에 초안을 만든다. 케이스마다 질문, 유형, 문서 SHA-256, 페이지, 근거 문구(literal_conditions / table / numeric, `pinned-gold.json` 형식), `status: "draft"`를 넣는다.
  2. 사용자가 PDF 원문 해당 페이지와 문구·수치·단위·기간을 대조한다. 케이스별로 `approved` 또는 `rejected`와 메모를 남긴다. 승인 기록에는 검토자, 날짜, 대조한 페이지가 들어간다.
  3. `approved` 케이스만 평가 파일(`evals/test-v2-cases.json`, `evals/test-v2-gold.json`)로 옮긴다. 이 파일들의 SHA-256을 계산해 이 문서에 기록하면 봉인된다. 봉인 뒤에는 수정하지 않는다. 오류를 찾으면 새 버전으로 만들고 그 사실을 기록한다.
  4. 승인 대기 중이거나 반려된 케이스는 어떤 수치에도 넣지 않는다.
- [x] **test셋 사용 규칙**: 봉인 뒤 10단계 마지막 측정 전까지 test셋으로 검색을 실행하지 않는다. test 문서의 업로드와 임베딩(측정에 필요)은 봉인 전에 해도 되며, 실행한 시각을 기록한다.

**완료 조건**
- 재사용 조사 판정과 근거(파일:줄)가 기록되어 있다.
- 모든 dev·test 질문에 유형이 있고 유형별 개수가 기록되어 있다.
- test셋은 사용자 승인 케이스만으로 봉인됐고 SHA-256이 기록되어 있다. 승인·반려 건수도 함께 적었다.
- 목표 규모는 test 2문서 이상, 답 있는 케이스 8개 이상(두 유형 모두 포함)이다. 채우지 못하면 실제 규모와 이유를 적는다.

기록: (2026-11-25, 파일·docs·코드 참조만 확인. 검색이나 평가는 실행하지 않음)

**재사용 조사: 모든 후보가 `불가`**

| 후보 | 판정 | 근거 |
|---|---|---|
| sealed-holdout-v1 questions/gold 재실행 | 불가 | `acceptance.md:211` "Sealed holdout v1 재실행·재채점 없이", `:222` "재실행·재채점·Gold 변경은 금지", `:237`, `:248`. 첫 실행 뒤 실패가 개발 피드백으로 쓰였다(`docs/sealed-holdout-v1-failure-attribution-audit-20261011.md:107`, 16항). |
| sealed-holdout-v1 PDF 5개 + 새 질문 | 불가 | 실패 귀속 감사에서 이 문서들의 페이지, 표, scope, 기간 문제를 질문별로 분석했다(같은 문서 `:16`, `:18`, `:46`, `:50`, `:70`~`:72`). 그 결과가 period/unit/scope binding 개발의 출발점이 되었다(`:97`, 15항). 같은 문서 `:107`은 새 holdout이 문서 SHA와 기업이 겹치지 않아야 한다고 적는다. 코드와 테스트에서 회사명 문자열은 찾지 못했지만(`grep -w`로 `backend/app`, `backend/tests`, `scripts` 확인), 문서 내용이 개발 판단에 쓰였으므로 불가로 본다. |
| `holdout-v1/` DB손해보험, POSCO홀딩스, LG | 불가 | SHA-256이 `evals/audit-documents.json`의 dev 문서(`blind_holdout: false`)와 일치한다(앞 16자리 `b4448fe38a9dda16`, `a21946429a6980e2`, `3489541bb393c167`). |
| `holdout-v1/` 기아, SK하이닉스 | 불가 | `evals/holdout-cases.json`의 `pdf_sha256`과 일치한다(`c0ca0d99eaea7405`, `90672edb08c701b7`). 실패 진단에 쓰였다: `scripts/audit_sk_unit_association.py`, `docs/sk-unit-association-audit-20261010.md`, `evals/sk-unit-association-reviewed-20261010.json`(1단계 표). |

**결론**: 사용자 결정(2026-11-25)에 따라 아직 수집하지 않은 실제 증권사 리포트 PDF 2개 이상이 필요하다. `acceptance.md:152`의 미완료 항목(새 sealed holdout 마련)과 같은 요구다. 사용자가 PDF를 제공하기 전까지 test셋 작업은 멈춘다.
- 새 PDF 조건: 위 10개 문서와 SHA-256이 겹치지 않을 것, 가능하면 기업도 겹치지 않을 것(`:107`), 실제 발행 리포트일 것.

**dev 질문 유형 (Claude 제안, 사용자 확인 전)**
- 파일: `evals/query-types-dev.json`. 유형 판정 기준과 케이스별 이유를 담았다. `audit-cases.json`은 수정하지 않았고 sha256 `50874005…`는 그대로다. 11개 case_id가 `audit-cases.json`과 순서까지 같은지 스크립트로 확인했다.
- 답 있는 9케이스: `exact_numeric_period` 5개(`lg-period`, `lg-table`, `db-scan`, `db-table`, `posco-forecast`), `semantic` 4개(`old-miss`, `old-risk`, `lg-fact`, `posco-multi`).
- 답 없는 2케이스(`old-none`, `db-none`)는 `exact_numeric_period`로 표시했지만 retrieval 지표에서는 제외한다.
- 판단이 갈리는 케이스: `lg-fact`(기간 토큰이 있지만 근거 설명 요구라 semantic), `posco-multi`(이유와 값을 함께 요구하는 복합 질문, 이유를 먼저 요구해서 semantic).
- 유형별 분모가 4와 5라서 10단계 유형별 비교는 한 케이스가 20~25%p를 움직인다. 해석할 때 이 한계를 함께 적는다.

**test-v2 초안 (2026-11-25, 사용자 승인 전, 검색 실행 안 함)**
- 파일: `evals/drafts/test-v2-draft.json`. 4문서 13케이스, 모두 답 있음. `semantic` 6개(`cj-bio`, `sb-growth`, `sb-tp-cut`, `isu-margin`, `isu-bottleneck`, `hs-shock`), `exact_numeric_period` 7개(`cj-domestic`, `cj-2028-op`, `sb-4q-op`, `isu-backlog`, `isu-4q-op`, `hs-3q-op`, `hs-2027-op`). 케이스마다 근거 단위는 1개다.
- 작성 방법: PyMuPDF native 텍스트를 읽고 질문과 근거 문구를 만들었다. 근거 형식은 `pinned-gold.json`과 같다(literal_conditions 또는 table).
- 자동 확인: 문서 SHA-256 4개가 일치한다. 모든 근거 문구와 표 값(15개)이 공백 제거 기준으로 지정 페이지의 native 텍스트에 있고, 다른 페이지에는 없다. 이 확인은 원문 대조 승인을 대신하지 않는다.
- 작성 원칙:
  - 여러 문구가 한 청크에 다 들어 있어야 하는 단위는 2단계에서 매칭 한계가 확인됐다. 그래서 문구를 1~2개로 줄이고, 같은 문단 안의 문구만 골랐다.
  - 같은 값이 여러 페이지에 있는 사실은 피했다. 예를 들어 CJ제일제당 2027F 영업이익은 1쪽과 3쪽에 모두 있어서 3쪽에만 있는 2028F를 골랐다.
  - 원문에서 앞뒤가 맞지 않아 보이는 곳은 질문에 쓰지 않았다: CJ제일제당 1쪽 "연결 영업이익은 7천원 내외", 솔브레인 2쪽 "26F EPS"와 비고 "2027년 추정 EPS", 한세실업 1쪽 영업이익 추정치 하향인데 표시가 ▲인 것.
- 리뷰 때 볼 점:
  - `isu-4q-op`는 1쪽 본문 "영업이익 1,111억원"을 근거로 삼았다. 2쪽 표에도 같은 값이 다른 단위(`111`, 십억원)로 있지만 gold는 1쪽만 인정한다.
  - DB 저장 텍스트(`final_text`)는 OCR 결합 결과라 native 텍스트와 다를 수 있다. 업로드 뒤 문구 존재 여부를 다시 확인해야 한다. 이 확인은 검색이 아니라 텍스트 대조만 한다.

**test-v2 승인과 봉인 (2026-11-26)**
- 승인 방법: Claude가 PDF 뷰어로 문서별 원문을 열었다. 사용자(hs98012)가 채팅 질문 카드에서 케이스별 근거 문구, 페이지, 단위, 기간을 보고 승인 또는 반려를 골랐다. 결과는 초안의 `review`에 기록했다(reviewer, reviewed_at, checked_pages, method, note).
- 결과: **승인 13, 반려 0.** 조건부 이해를 note에 남긴 케이스는 3개다.
  - `isu-bottleneck`: 원인 문구만 gold다.
  - `isu-4q-op`: 1쪽만 인정한다.
  - `hs-2027-op`: 2쪽 73.9만 인정한다.
- 규모: 4문서, 답 있는 13케이스, 13단위. `exact_numeric_period` 7개, `semantic` 6개. 완료 조건의 목표 규모(2문서 이상, 8케이스 이상, 두 유형 포함)를 채웠다.
- 봉인 파일 (2026-11-26, 이후 수정 금지):
  - `evals/test-v2-cases.json` sha256 `3ea9fbec403dcbe14eafcfe570681facf79d8a4abb4aa8f46d5c1e91f84f8138`
  - `evals/test-v2-gold.json` sha256 `78509eb676c607f2e96af147032a89dc1b3f4ba147c9e447a0855a1c4f37f1b8`
  - 승인 기록이 담긴 `evals/drafts/test-v2-draft.json` sha256 `0b8c3e5532fdc6a1183dcd06d2c9bc7b8ad0682f1eed027fda68b71b9eb8d594`
- 형식: cases는 `measure_retrieval.py`가 읽는 필드(`id`, `company_name`, `published_at`, `question`)에 `query_type`, `filename`, `pdf_sha256`, `expected_pages`를 더했다. gold는 `{"units": [...]}`이며 `pinned-gold.json`과 같은 매칭 필드를 쓴다.
- 이 시점까지 test-v2로 검색을 실행한 적이 없다. test 문서 4개는 아직 DB에 업로드하지 않았다.

**dev 유형 확정 (2026-11-26, 사용자)**: 제안한 라벨을 그대로 유지한다(답 있는 9케이스 중 `exact_numeric_period` 5개, `semantic` 4개). `evals/query-types-dev.json`의 status를 `confirmed_by_user`로 바꿨고 sha256은 `0e7658490daf76a344919b4529fb17a01522deb130ec3c1caad1fec0824905de`이다.

**9단계 완료 (2026-11-26)**: 완료 조건 4개를 모두 채웠다. test셋 사용 규칙은 10단계 마지막 측정 전까지 계속 적용한다.

## 10단계. 재측정과 개선 1개

- [x] dev셋에서 4개 모드(`bm25`, `vector`, `hybrid_rrf`, `hybrid_rrf_with_promotion`)를 다시 측정한다. 전체 수치와 `query_type`별 수치(hit@1/3/5, unit_recall@5, MRR@5)를 표로 남긴다. `scripts/measure_retrieval.py`에 `--query-types <file>` 옵션을 추가하고 `backend/app/retrieval_metrics.py`의 `summarize`를 유형별로 재사용한다. 유형별 집계 함수는 테스트를 먼저 쓴다.
- [x] **개선 후보는 하나만 고른다**: (a) RRF 가중치 옵션(`backend/app/search.py`의 `reciprocal_rank_fusion`에 BM25/vector 가중치 키워드 추가, 기본값은 현재 동작) 또는 (b) 리랭커.
  - 측정 전에 선택 기준을 이 문서에 적는다. 예: dev MRR@5가 오르고 어느 유형에서도 hit@5가 떨어지지 않을 것.
  - 리랭커가 새 의존성이나 모델 다운로드를 요구하면 4단계 선례대로 사용자 승인을 먼저 받는다.
- [x] 고른 개선은 기본값을 바꾸지 않는 옵션으로만 추가한다. 기본 동작이 그대로인지는 기존 `test_hybrid_search.py` 통과로 확인한다. dev에서 가중치 등 설정값을 몇 개 시도했는지 모두 기록한다(과적합 위험 공개).
- [x] **test셋은 마지막에 한 번만 측정**한다. 대상은 기준선(`hybrid_rrf_with_promotion`)과 고른 개선 설정 두 개뿐이다. 결과를 본 뒤에는 설정을 바꾸지 않고, test 결과로 다시 튜닝하지 않는다.
- 5단계의 600/0 청킹 후보는 이번 개선 1개에 넣지 않는다(재임베딩 비용).

**완료 조건**
- dev 4모드 × 유형별 표가 실제 실행 결과로 채워져 있다(커밋, 해시, 실행 시각, 명령 포함).
- 측정 전에 적은 선택 기준, 선택 결과, 시도한 설정 수가 기록되어 있다.
- 기준선과 개선 설정의 test 1회 측정 결과가 기록되어 있고, 채택 여부와 이유, 케이스 수가 적다는 한계가 함께 적혀 있다.
- `./scripts/check.sh`가 통과한다.

기록: (2026-11-26, 진행 중)

**코드 변경 (유형별 집계)**
- `backend/app/retrieval_metrics.py`: `summarize_by_group(case_ranks, unit_ranks, groups)`를 추가했다. 기존 `summarize`를 라벨별로 다시 쓴다. 측정한 케이스에 라벨이 없으면 `ValueError`를 낸다.
- `backend/tests/test_retrieval_metrics.py`에 3개를 추가했다(라벨별 분리, 측정하지 않은 라벨 무시, 라벨 누락 거절). 구현 전 ImportError로 실패했고 구현 후 15 passed.
- `scripts/measure_retrieval.py`: `--query-types <file>` 옵션을 추가했다. 파일의 `dev_cases_sha256`이 현재 `audit-cases.json`과 다르면 실행을 멈춘다. 출력에는 `query_types_sha256`, `metrics_by_query_type_evidence`, `metrics_by_query_type_page_only`가 추가된다. 옵션이 없으면 기존 출력과 같다.
- `./scripts/check.sh` 통과: backend 749 passed, frontend 17 passed, lint, build.

**DB 준비**: 사용자가 Docker Desktop을 켰다. 멈춰 있던 `stock-brief-ai-postgres-1`을 `docker start`로 그대로 켰다(재생성·볼륨 변경 없음). `chunks`는 231행으로 5단계와 같다.
- 5단계의 md5 기준값(`2ba2e96d…`)은 계산식이 기록되지 않아 재현하지 못했다. 대신 아래 측정에서 4개 모드 모두 11개 질의의 retrieved chunk_id·순위·페이지가 3단계 결과와 완전히 같았다. 이것으로 검색 동작이 바뀌지 않았다고 판단한다.
- 새 기준선은 계산식과 함께 남긴다: `select md5(string_agg(id::text||char_start||char_end||content||coalesce(embedding::text,''), '|' order by id)) from chunks` = `6fbdf6c48d58785c7ce283abc5168239`.

**dev 측정 (4모드 × 유형별, 각 1회)**
- 실행 시각: 2026-11-25T15:17:04Z ~ 15:17:11Z(KST 11-26 00:17). 커밋 `28061c6`, dirty. cases sha `50874005…`, gold sha `bd6acaac…`, query_types sha `0e765849…`.
- 원본 출력: `evals/results/retrieval-metrics-20261126/dev-bytype-<mode>.json`
- 실행 명령: `.venv/bin/python scripts/measure_retrieval.py --mode <mode> --query-types evals/query-types-dev.json` (환경변수는 2단계와 같음)
- 전체 지표는 4모드 모두 3단계 표와 같다(같은 입력에서 재현).

| 모드 | 유형 | hit@1 | hit@3 | hit@5 | unit_recall@5 | MRR@5 | 페이지 MRR@5 |
|---|---|---:|---:|---:|---:|---:|---:|
| bm25 | exact (5케이스/7단위) | 3/5 | 3/5 | 3/5 | 4/7 | 0.600 | 0.800 |
| bm25 | semantic (4케이스/5단위) | 3/4 | 3/4 | 3/4 | 3/5 | 0.750 | 1.000 |
| vector | exact | 1/5 | 1/5 | 2/5 | 3/7 | 0.250 | 0.317 |
| vector | semantic | 3/4 | 4/4 | 4/4 | 4/5 | 0.833 | 1.000 |
| hybrid_rrf | exact | 1/5 | 2/5 | 3/5 | 4/7 | 0.317 | 0.517 |
| hybrid_rrf | semantic | 3/4 | 3/4 | 3/4 | 3/5 | 0.750 | 1.000 |
| hybrid_rrf_with_promotion | exact | 1/5 | 2/5 | 3/5 | 4/7 | 0.317 | 0.517 |
| hybrid_rrf_with_promotion | semantic | 4/4 | 4/4 | 4/4 | 4/5 | 1.000 | 1.000 |

(hit@1~MRR@5는 근거 일치 기준이다.)

- 질의 시간 중앙값/최대: bm25 0.010s/0.068s, vector 0.078s/0.144s, hybrid_rrf 0.093s/0.146s, +promotion 0.086s/1.927s. 최대값은 처음 실행한 모드(+promotion)의 첫 질의다.

**관찰 (dev 9케이스, 일반화 아님)**
- exact 질문에서는 BM25가 가장 좋았다(MRR@5 0.600). vector는 0.250, hybrid는 0.317이다. 차이는 `lg-period`(bm25 1위, hybrid 3위)와 `posco-forecast`(bm25 1위, vector 없음, hybrid 4위)에서 나온다. vector 순위가 낮으면 RRF가 BM25 1위를 끌어내린다.
- semantic 질문에서는 vector(0.833)와 +promotion(1.000)이 BM25(0.750)보다 좋았다. `posco-multi`는 bm25가 놓치고 vector 3위, +promotion 1위다.
- 유형별 분모가 4와 5라서 한 케이스가 hit 비율을 20~25%p 움직인다.

**개선 후보 선택 (2026-11-26, 사용자 승인, 후보 측정 전에 기록)**
- 후보: (a) RRF 가중치 옵션. 리랭커는 고르지 않는다. 이유는 두 가지다.
  - 위 관찰의 문제(vector 순위가 낮을 때 RRF가 BM25 1위를 희석)를 직접 겨냥한다.
  - 리랭커는 새 의존성 또는 모델 다운로드, 지연 측정이 필요해 마감 전 비용이 크다.
- 구현 원칙: BM25 가중치를 키워드 옵션으로만 추가하고 기본값(1:1)은 바꾸지 않는다. vector 가중치는 1로 고정한다. 적용 모드는 `hybrid_rrf_with_promotion`(기본 경로)이다.
- 시도할 설정(미리 고정): BM25 가중치 1.5, 2.0, 3.0. 이 3개 외에는 dev에서 시도하지 않는다.
- 채택 기준(근거 일치 지표):
  1. dev 전체 MRR@5가 기준선 0.620보다 높아야 한다.
  2. 유형별 hit@5가 떨어지지 않아야 한다(exact 3/5 이상, semantic 4/4).
  3. 기준을 만족하는 설정이 여럿이면 MRR@5가 가장 높은 것을 고르고, 같으면 더 작은 가중치를 고른다.
  4. 만족하는 설정이 없으면 채택하지 않고, test셋은 기준선만 측정한다.
- test셋 측정은 이 선택 뒤 한 번만 한다. 대상은 기준선과 선택한 설정이다.

**코드 변경 (RRF 가중치 옵션)**
- `backend/app/search.py`: `reciprocal_rank_fusion`에 키워드 `bm25_weight`(기본 1.0)를 추가했다. BM25 항만 곱한다. 0 이하이면 `ValueError`를 낸다. `hybrid_search`와 `rank_rows`는 이 값을 그대로 전달한다. 기본값이면 기존 동작과 같다.
- `scripts/measure_retrieval.py`: `--bm25-weight`(기본 1.0)를 추가했다. 출력 provenance에 `bm25_weight`가 들어간다.
- `test_hybrid_search.py`에 5개를 추가했다(BM25 항만 스케일, 기본값 동치, 0과 음수 거절, hybrid_search 전달). 구현 전 5개 실패, 구현 후 25 passed. 모의 교체 테스트(`test_blind_evaluation_adapter.py`)도 통과했다.
- `./scripts/check.sh` 통과: backend 754 passed, frontend 17 passed, lint, build.

**dev 측정 (`hybrid_rrf_with_promotion`, 각 1회, 2026-11-25T15:20:54Z ~ 15:21:00Z)**
- 원본 출력: `evals/results/retrieval-metrics-20261126/dev-rrfw-<weight>.json`
- 실행 명령: `.venv/bin/python scripts/measure_retrieval.py --mode hybrid_rrf_with_promotion --bm25-weight <w> --query-types evals/query-types-dev.json`
- 대조군 1.0은 11개 질의의 retrieved 목록이 위 기준선 측정과 완전히 같았다.
- dev에서 시도한 설정은 미리 정한 3개(1.5, 2.0, 3.0)뿐이다. 대조군 1.0은 선택 후보가 아니다.

| BM25 가중치 | hit@1 | hit@3 | hit@5 | unit_recall@5 | MRR@5 | exact hit@5 / MRR@5 | semantic hit@5 / MRR@5 | 페이지 MRR@5 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1.0 (기준선) | 5/9 | 6/9 | 7/9 | 8/12 | 0.620 | 3/5 / 0.317 | 4/4 / 1.000 | 0.731 |
| 1.5 | 5/9 | 7/9 | 7/9 | 8/12 | 0.648 | 3/5 / 0.367 | 4/4 / 1.000 | 0.759 |
| 2.0 | 7/9 | 7/9 | 7/9 | 8/12 | 0.778 | 3/5 / 0.600 | 4/4 / 1.000 | 0.889 |
| 3.0 | 7/9 | 7/9 | 7/9 | 8/12 | 0.778 | 3/5 / 0.600 | 4/4 / 1.000 | 0.889 |

- 바뀐 케이스는 exact 두 개다. `lg-period`는 3위에서 2위(1.5), 1위(2.0, 3.0)로, `posco-forecast`는 4위에서 3위(1.5), 1위(2.0, 3.0)로 올랐다. semantic 4케이스는 모든 가중치에서 1위를 유지했다. `lg-table`, `db-scan`은 여전히 5위 안에 없다.
- 질의 시간 중앙값은 0.079~0.099초로 기준선과 비슷하다.

**선택 결과 (미리 정한 기준 적용)**
- 1.5, 2.0, 3.0 모두 기준 1(MRR@5 > 0.620)과 기준 2(exact hit@5 3/5, semantic 4/4 유지)를 만족한다.
- MRR@5가 가장 높은 것은 2.0과 3.0(0.778)이고 같으므로 기준 3에 따라 **BM25 가중치 2.0**을 고른다.
- 이 개선은 두 케이스(`lg-period`, `posco-forecast`)에서만 나왔다. dev에서 고른 값이라 test 결과 전에는 개선이라고 주장하지 않는다. 기본값은 아직 바꾸지 않았다.

**test 문서 업로드 (2026-11-25T15:26:52Z ~ 16:18:11Z, 검색 실행 안 함)**
- 방법: `scripts/ingest_test_v2.py`를 새로 만들었다. 초안의 문서 메타데이터와 SHA-256을 확인한 뒤, API와 같은 `ingest_document`, `embed_document`를 현재 작업 트리 코드로 호스트에서 호출한다. 검색은 하지 않는다.
  - backend 컨테이너 이미지는 7주 전 빌드라 현재 코드가 아니어서 쓰지 않았다.
  - Paddle 구조 분석은 프로젝트의 `stock-brief-ai-ocr-worker-1`을 `docker start`로 그대로 켜서 사용했다(재빌드 없음, health: PP-StructureV3, korean_PP-OCRv5_mobile_rec, cpu).
  - 호스트 Tesseract에는 `kor` 언어 데이터가 없다. 4문서 18쪽 모두 `text_source=native`이고 `ocr_error`는 0건이라 Tesseract는 쓰이지 않았다.
- 실행 명령: `DATABASE_URL=… OLLAMA_BASE_URL=http://localhost:11434 PADDLE_STRUCTURE_URL=http://127.0.0.1:8090 .venv/bin/python scripts/ingest_test_v2.py`
- 원본 로그: `evals/results/retrieval-metrics-20261126/ingest-test-v2.jsonl`(stderr 비어 있음)
- 결과: 4문서 모두 `status=completed`, `embedding_status=completed`, 임베딩 실패 0건.

| 문서 | document_id | 쪽 | 청크 | 처리 시간 |
|---|---|---:|---:|---|
| CJ제일제당 | `22ecac33-0065-4da1-8896-1778a8630ce0` | 4 | 308 | 약 8분 |
| 솔브레인 | `d5096a24-b53c-4964-9b21-870818b332fb` | 4 | 50 | 약 7.5분 |
| 이수페타시스 | `15497e82-ca8a-477a-8c97-741b99634c68` | 4 | 858 | 약 20분 |
| 한세실업 | `3f7a19db-9b42-4360-b7e2-3bc9d03fd3b8` | 6 | 717 | 약 16분 |

- 같은 DB에 들어갔고 평가 문서 표시 컬럼은 없다. 측정은 케이스마다 `document_id` 필터로 해당 문서만 검색하므로 dev와 섞이지 않는다. 필터 없는 전체 검색에는 test 문서가 포함된다.
- **사용자 결정 (2026-11-26)**: test 문서 4개는 삭제하지 않고 DB에 그대로 둔다.
- **dev와 다른 점**: dev 4문서는 `page_extractions`가 없는 기존 업로드라 1200자 청킹(문서당 10~27개)이다. test 문서는 현재 코드의 fact-fusion 경로를 거쳐 승인된 `index_segments`만 청크가 되므로 청크가 훨씬 많고 짧다. 따라서 dev와 test의 수치 차이에는 검색 설정뿐 아니라 추출·청킹 경로 차이가 섞인다.

**gold 텍스트 대조 (검색 아님, 읽기 전용)**: 15개 문구·값 중 11개가 저장된 `final_text`와 같은 페이지의 청크 본문에 모두 있다. 나머지 4개는 다음과 같다.
- `sb-growth`: 저장된 `final_text`에 문구가 없다. 현재 추출이 1쪽 본문에 오른쪽 사이드바 값을 끼워 넣었다(예: "웨이퍼 투입량 52주 최고가(보통주) 501,000 원 증가와"). native 텍스트에는 문구가 있었다. 추출 단계의 읽기 순서 문제다.
- `hs-shock`: 두 문구가 페이지에는 있지만 한 청크에 같이 들어 있지 않다(청크가 짧다). 단위가 한 quote에 두 문구를 모두 요구하므로 이 청킹에서는 근거 일치가 불가능하다.
- `cj-2028-op`, `sb-4q-op`: 값이 페이지에는 있지만 어떤 청크 본문에도 없다. 표 단위라 검색 결과에 붙은 table fact로는 일치할 수 있다.
- 봉인 규칙에 따라 gold는 고치지 않는다. 이 4개는 측정에서 그대로 실패할 수 있으며, 결과를 해석할 때 이 사실을 함께 적는다.

**dev 재확인 (test 업로드 뒤, 2026-11-25T16:20:08Z)**: 기본 모드의 dev 11개 질의 retrieved 목록과 지표가 업로드 전 측정과 같았다(`dev-after-test-upload.json`).

**test 측정 (사용자 결정: 봉인 gold 그대로 실행, 1회)**
- 실행 시각: 1.0은 2026-11-25T16:20:21Z, 2.0은 16:24:30Z. 커밋 `28061c6`, dirty. cases sha `3ea9fbec…`, gold sha `78509eb6…`(봉인 값과 일치). 13개 질의 모두 vector 검색을 사용했다.
- 원본 출력: `evals/results/retrieval-metrics-20261126/test-v2-rrfw-<1.0|2.0>.json`
- 실행 명령: `.venv/bin/python scripts/measure_retrieval.py --mode hybrid_rrf_with_promotion --bm25-weight <w> --cases evals/test-v2-cases.json --gold evals/test-v2-gold.json`. 유형은 cases 파일의 `query_type`을 쓴다. 측정 스크립트에 `--cases`/`--gold`를 추가했고 기본값은 dev 파일이다.
- test로 시도한 설정은 이 2개뿐이고 각 1회만 실행했다.

| BM25 가중치 | 유형 | hit@1 | hit@3 | hit@5 | unit_recall@5 | MRR@5 | 페이지 hit@5 | 페이지 MRR@5 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1.0 | 전체 (13) | 1/13 | 6/13 | 7/13 | 7/13 | 0.237 | 12/13 | 0.731 |
| 2.0 | 전체 (13) | 2/13 | 5/13 | 7/13 | 7/13 | 0.282 | 12/13 | 0.710 |
| 1.0 | exact (7) | 1/7 | 3/7 | 4/7 | 4/7 | 0.298 | 6/7 | 0.595 |
| 2.0 | exact (7) | 2/7 | 3/7 | 4/7 | 4/7 | 0.393 | 6/7 | 0.576 |
| 1.0 | semantic (6) | 0/6 | 3/6 | 3/6 | 3/6 | 0.167 | 6/6 | 0.889 |
| 2.0 | semantic (6) | 0/6 | 2/6 | 3/6 | 3/6 | 0.153 | 6/6 | 0.867 |

(hit@1~MRR@5는 근거 일치 기준이다.)

- 케이스별 근거 순위(1.0 → 2.0):
  - 오른 케이스: `isu-backlog` 2→1, `isu-4q-op` 3→2.
  - 내려간 케이스: `cj-bio` 3→4.
  - 같은 케이스: `cj-domestic` 4, `isu-margin` 3, `isu-bottleneck` 3, `hs-2027-op` 1.
  - 두 설정 모두 5위 안에 없는 케이스: `cj-2028-op`, `sb-growth`, `sb-tp-cut`, `sb-4q-op`, `hs-3q-op`, `hs-shock`.
  - 페이지 기준으로는 `hs-3q-op`, `hs-shock`이 3위에서 5위로 내려갔다.
- 질의 시간: 중앙값 약 24초, 최대 약 30초(두 설정 비슷). dev 문서(0.1초 안팎)보다 훨씬 느리다. test 문서의 청크가 많아 요청마다 하는 BM25 재구성과 표·수치 후보 검증 비용이 커진 것으로 추정하지만, 프로파일링은 하지 않았다.

**채택 판단 (미리 정한 기준을 test에 그대로 적용)**
- 기준 1(MRR@5 상승): 0.237 → 0.282로 만족한다.
- 기준 2(유형별 hit@5 유지): exact 4/7 → 4/7, semantic 3/6 → 3/6으로 만족한다.
- 그러나 효과는 작고 섞여 있다. 오른 케이스 2개, 내려간 케이스 1개다. 전체 hit@3(6→5), semantic MRR@5(0.167→0.153), 페이지 MRR@5(0.731→0.710)는 떨어졌다. 13케이스에서 이 정도 차이는 우연과 구별할 수 없다.
- **결정**: BM25 가중치 2.0은 test에서도 사전 기준을 통과했다. 하지만 효과가 작아 기본값(1.0)은 바꾸지 않는다. `bm25_weight` 옵션과 권장 후보값 2.0만 기록으로 남긴다. 기본값 변경은 계획에 없던 일이며, 더 큰 평가셋이 생기면 다시 판단한다.
- 면접 설명 포인트:
  - dev에서 큰 개선(MRR 0.620 → 0.778)으로 보이던 것이 test에서는 0.237 → 0.282로 작아졌다. 9케이스 dev에서 고른 설정의 과적합 위험을 test 분리로 확인한 사례다.
  - test에서 페이지 hit@5는 12/13인데 근거 hit@5는 7/13이다. 맞는 페이지는 찾지만 근거 문장이 한 청크에 온전히 들어 있지 않다. 위 gold 텍스트 대조에서 본 추출·청킹 문제(사이드바 끼어듦, 짧은 청크)와 같은 방향이다.
- 한계: test 13케이스, 1회 측정이다. dev와 test는 업로드 경로(기존 1200자 청킹과 fact-fusion)가 달라 dev↔test 수치를 직접 비교해 일반화를 주장하지 않는다. 같은 test 안에서 1.0과 2.0을 비교한 것만 공정한 비교다.

**10단계 완료 (2026-11-26)**: 완료 조건 4개를 모두 채웠다. `./scripts/check.sh` 통과(backend 754 passed, frontend 17 passed, lint, build). API와 데이터 모델은 바꾸지 않았다(평가 전용 키워드 옵션만 추가). 그래서 `api-contract.md`, `acceptance.md`, `qa-rules.md`는 갱신하지 않았다.

## 11단계. BM25 인덱스 재사용 (시간이 남을 때만) (종료: 병목 아님, 미구현)

- [x] (미구현으로 종료, 아래 기록) `hybrid_search`/`rank_rows`가 요청마다 `BM25Okapi`를 새로 만드는 부분을 문서(또는 필터 조합) 단위 캐시로 바꾼다. 무효화 기준은 청크 집합(document_id + 청크 수/해시)이다. 검색 결과는 바뀌지 않아야 한다.
- [x] (캐시 미구현이라 전후 측정 없음, 병목 프로파일만 기록) 변경 전후 질의 지연을 같은 조건에서 측정한다(중앙값/최대, 첫 질의 분리). dev 지표와 질의별 순위가 같은지 확인한다.

**완료 조건**
- 캐시 적중·무효화 테스트가 있고 `./scripts/check.sh`가 통과한다.
- 전후 지연 수치와 dev 순위 동일 여부가 실행 결과로 기록되어 있다. 실행하지 못했으면 "시간 부족으로 미실행"이라고 적는다.

기록: (2026-11-26, 시작 전 중단. 사용자 요청으로 다음 세션에 이어서 진행)

**현재 상태**
- 코드 변경 없음. 측정 결과 없음.
- 첫 작업으로 test 질의 1개(`hs-3q-op`, 한세실업 717청크)를 cProfile로 프로파일링하려 했으나, 실행 중 사용자가 중단했다. 결과를 보지 않았고 기록할 수치도 없다. 남은 프로세스가 없음을 확인했다.

**다음 세션에서 할 일 (순서대로)**
1. 병목 확인: 지연의 대부분이 BM25 재구성인지 먼저 프로파일링으로 확인한다. 10단계 test에서 질의당 약 24초가 걸렸는데 원인은 확인되지 않았다(추정 후보: BM25 재구성, 표·수치 후보 검증 `verified_table_candidates`/`verified_numeric_candidates`, 행 조회). BM25가 병목이 아니면 캐시만으로 지연이 줄지 않으므로, 그 사실을 기록하고 범위를 사용자와 다시 정한다.
2. 프로파일링 대상 문서:
   - dev 문서는 질의당 0.1초 안팎이라 병목이 드러나지 않는다. 그래서 test 문서로 지연만 잰다.
   - 이는 검색 순위 튜닝이 아니며, 순위 설정은 10단계 결정에서 바꾸지 않는다.
   - test 문서로 측정을 다시 실행한다는 점은 사용자 확인을 받고 진행한다.
3. 캐시 테스트를 먼저 쓴다(적중, 청크 집합 변경 시 무효화). 그다음 구현한다.
4. 변경 전후 지연을 같은 조건으로 측정한다(중앙값/최대, 첫 질의 분리). dev와 test의 질의별 retrieved 목록이 같은지 확인한다.
5. `./scripts/check.sh` 통과 후 기록한다.

**참고**
- 프로파일링 스크립트는 세션 scratchpad에 있었다. 2026-11-26에 `scripts/profile_one.py`로 옮겼다. 9단계의 `check_gold_text.py`는 scratchpad가 정리돼 남아 있지 않아 옮기지 못했다.
- DB(`stock-brief-ai-postgres-1`)와 OCR worker(`stock-brief-ai-ocr-worker-1`)는 켜 둔 상태다. 다음 세션에서 꺼져 있으면 사용자에게 Docker Desktop 실행을 요청하고 `docker start`로 그대로 켠다.

**재개 (2026-11-26)**
- 사용자가 Docker Desktop을 켰다. `stock-brief-ai-postgres-1`을 `docker start`로 그대로 켰다. 검색에는 OCR worker가 필요 없어 켜지 않았다.
- dev 4문서 청크 fingerprint(위 10단계 기록의 계산식)는 231행, `6fbdf6c48d58785c7ce283abc5168239`로 기준값과 같다.
- 사용자 승인: 지연 측정에 test 문서를 쓴다. 순위 설정은 바꾸지 않는다.

**병목 확인 (cProfile, 읽기 전용, `hs-3q-op` 1회, 기본 설정)**
- 스크립트: `scripts/profile_one.py`(2026-11-26 scratchpad에서 옮김, 실행: `python scripts/profile_one.py <저장소 경로> <case id>`). `hybrid_search` 한 번을 cProfile로 감싼다. 프로파일러 오버헤드 때문에 전체 시간이 10단계 측정(약 24초)보다 길다.
- 전체 49.5~50.8초 중 `table_evidence.verified_table_candidates`가 47.1~47.2초(약 95%)다. 그 아래 대부분은 `extraction_provenance.validated_stored_facts`(46.7초)다. 이 함수는 저장된 표 fact를 요청마다 provenance에서 다시 유도하고 검증한다(`structured_cells.extract_cell_facts` 30.6초, `scope_binding.enrich` 17.8초 등).
- BM25 관련 비용: `rank_bm25` 생성과 `get_scores`는 프로파일 표에서 0.001초 단위 아래였다. 토큰화 0.002초, `retrieval_text` 0.019초다. 질의 임베딩 0.081초, `verified_numeric_candidates` 0.619초다.
- 원인: `verification_cache.memoized`는 요청 단위 캐시다(`request_verified`). 그래서 같은 문서를 다시 질의해도 매번 다시 검증한다. 주석에는 "Reuse a fingerprint inside one request only"라고 되어 있어, 요청마다 다시 검증하는 것이 의도된 설계로 보인다.
- **결론**: 이 경로에서 BM25 재구성은 병목이 아니다. BM25 인덱스를 캐시해도 줄어드는 시간은 질의당 수 밀리초 수준으로 예상된다(캐시를 구현해 재지는 않았다). 원래 계획(BM25 캐시)대로는 지연 개선 효과가 없다.

**결정 (2026-11-26, 사용자)**: 11단계는 BM25 캐시를 구현하지 않고 종료한다. 실제 병목인 표 fact 재검증을 요청 사이에서 캐시하는 일은 "요청마다 재검증" 설계를 바꾸고 운영 동작에도 영향이 있다. 그래서 마감 이후 별도 설계 과제로 남긴다. 완료 조건 중 캐시 테스트와 전후 지연 수치는 미구현이라 없다. 대신 병목 프로파일을 기록했다.

## 8단계. 면접용 아키텍처 문서

9·10단계 수치가 기록된 뒤 마지막에 진행한다(11단계는 진행했으면 포함한다).

- [x] `docs/architecture.md`를 작성한다: 파이프라인 다이어그램, 설계 결정(RRF k=60, exact scan, bge-m3, 검색 표현과 인용 분리, fail-closed 거절, dev/test 분리와 사람 승인 gold, 질문 유형별 비교), 알려진 한계.
- [x] 문서에 나오는 모든 수치는 이 플랜의 `기록:` 항목이나 기존 docs의 실행 기록과 연결한다.

**완료 조건**
- 출처 없는 수치가 문서에 없다.
- README에서 `docs/architecture.md`로 링크한다.

기록: (2026-11-26)

- `docs/architecture.md`를 작성했다. 내용은 Mermaid 파이프라인 다이어그램, 단계별 위치 표, 설계 결정 9개(이유와 대가), 평가(평가셋, 모드 비교, RRF 가중치 dev/test, 지연, 채택하지 않은 실험), 알려진 한계, 마감 이후 과제다.
- 수치 출처: 문서의 모든 수치 옆에 출처 단계를 괄호로 적었다. 문서에 쓴 수치 27개를 이 플랜에서 grep으로 찾아 모두 있음을 확인했다. sealed holdout v1 수치는 이 플랜 0단계가 옮겨 적은 `docs/sealed-holdout-v1-first-run-20261011.md`에서 왔다.
- README의 `## 구성` 목록에 `docs/architecture.md` 링크를 추가했다.
- `./scripts/check.sh` 통과: backend 754 passed, frontend 17 passed, lint, build.
- Mermaid 렌더링은 확인하지 않았다(GitHub 등 Mermaid를 지원하는 뷰어에서만 그림으로 보인다).

## 12단계. 검색 실패 진단 (코드 변경 없음)

6단계에서 검색 실패로 분류된 7건의 원인을 확인한다. 진단만 하고 검색·분류기 코드는 바꾸지 않는다.

- [x] 2026-08-10/08-14 질문 4건이 분석 후보 0개가 된 원인을 찾는다. 원시 검색 결과 수, 필터 조건, 청크·임베딩 적재 여부, 필터 단계별로 남는 개수를 확인한다.
- [x] topic 키워드 때문에 검색 실패로 분류된 3건이 실제로 맞는 근거를 찾았는지 인용문과 기대 페이지를 대조한다.

기록: (2026-11-26)

- 방법: scratchpad의 읽기 전용 스크립트(`SET TRANSACTION READ ONLY`, 마지막에 rollback)로 운영 로컬 DB(`localhost:5432`)에서 `collect_analysis_evidence`의 단계를 재현했다. 질의 임베딩은 Ollama `bge-m3`. 재현한 packet은 4건 모두 0개로 6단계 trace(`candidates: []`)와 같다. 저장소 파일은 이 기록 말고는 바꾸지 않았다.
- 구조 확인: 분석 후보는 `hybrid_search` 결과가 아니라 `document_candidates`(문서 전체 페이지를 문장 단위로 나눈 것)에서 나온다. 검색 결과는 정렬 점수로만 쓰인다. `hybrid_search`에는 점수 임계값이 없고 top_k 자르기만 있으며, 재순위(표·수치 승격)는 순서만 바꾼다.

**적재 상태**

| 문서 | 페이지 | 청크 | 임베딩 | 모델 | 임베딩 오류 |
|---|---|---|---|---|---|
| 2026-08-10 (`339509a7`) | 7 (OCR 6, native 1) | 28 | 28 | ollama/bge-m3/1024 | 0 |
| 2026-08-14 (`8fcb63b3`) | 9 (OCR 9) | 35 | 35 | ollama/bge-m3/1024 | 0 |

**단계별 남은 개수 (후보 0개 4건)**

| 케이스 | requirement | 검색 결과(질의 3개) | 기대 페이지 첫 순위(질의 0) | document_candidates | 품질 valid | positive/negative | focus 통과 | packet |
|---|---|---|---|---|---|---|---|---|
| 08-10 full-stack-positive | no_factual | 20/20/20 | p1 1위 | 38 | 35 | 2 | 0 | 0 |
| 08-10 foundry-loss-negative | no_factual | 20/20/20 | p1 1위 | 38 | 35 | 2 | 0 | 0 |
| 08-14 dram-hbm-pricing-positive | no_factual | 20/20/20 | p1 2위 | 51 | 40 | 4 | 0 | 0 |
| 08-14 foundry-loss-negative | no_factual | 20/20/20 | p3 8위 | 51 | 40 | 4 | 0 | 0 |

- 연도 검사(`missing_requested_years`)는 4건 모두 통과했다. 표 구조 경로(`structured`)는 두 문서 모두 `table_evidence`가 있는 span이 0개라 0이다.
- 결론: 검색이나 적재 문제가 아니다. 기대 근거 문장은 후보에 있다. 빠지는 곳은 `analysis_retrieval.py`의 두 필터다. (1) 관점 필터는 `analysis_perspective`가 positive/negative인 것만 남긴다. (2) focus-term 필터는 질문 토큰 중 하나가 인용문에 그대로 있어야 통과시킨다.
- 케이스별 원인:
  - 08-10 full-stack-positive: 기대 문장("…풀스택 제조 역량이다.", "…메모리+로직 결합 제품…턴키로 공급…기대 요인이다.")은 valid이지만 `economic_facts`가 fact를 찾지 못해 관점이 neutral이다. 그래서 관점 필터에서 빠진다. positive/negative로 남은 2개(p1 수주잔고 문장, p4 영업이익 표 행)에는 focus 단어가 없다.
  - 08-10 foundry-loss-negative: 기대 문장("비록 파운드리 사업은 대규모 투자 금액과…적자상태를 지속하고…")이 2단 레이아웃 OCR에서 옆 칸의 숫자·라벨(`seer) 90008`, `Bea enue 750`, `52주최저가`)과 섞였다. 그래서 `ocr_noise`로 제외됐고 관점도 ambiguous다(적자 지속 negative와 점유율 확대 positive가 함께 있음).
  - 08-14 dram-hbm-pricing-positive: 기대 문장("28년까지 DRAM 수급이 타이트할 것으로 추정되며, HBM 가격 인상 효과를 주도로 DRAM ASPS 상승세를…")은 valid이다. 하지만 `가격 인상`이 ambiguous/forecast fact로 판정돼 관점이 ambiguous가 되고, 관점 필터에서 빠진다.
  - 08-14 foundry-loss-negative: 기대 근거인 p3 `Foundry/LS` 행 2개(영업이익, 영업이익률)는 valid이고 negative라서 관점 필터를 통과한다. 하지만 required focus `[lsi, 부담, 부문, 수익성, 적자, 파운드리]` 중 어느 것도 인용문에 없다(원문 표기는 `Foundry/LS`). 그래서 focus 필터에서 빠진다.
  - focus 토큰에 조사·어미가 남는 경우도 확인했다: `실적에`, `주는`, `설명돼`, `보유한`, `전망이나`.
- 보조 관찰: `analysis_service`는 `retrieval_diagnostics`(`candidate_count`, `valid_count`)를 계산하지만 `_evaluation_trace`에 저장하지 않는다. 그래서 trace에는 빈 배열만 남는다. 이번 재현에서는 4건 모두 `candidate_count` 38/38/51/51, `valid_count` 0이었다.

**topic 키워드 실패 3건 대조**

| 케이스 | 기대(페이지 / topic) | 실제 인용(페이지) | 판정 |
|---|---|---|---|
| 2025-07-09 summary-positive | p1 / `하반기 개선\|밸류 갭 축소\|악재 해소` | p1 "3Q25 컨벤셔널 디램 가격 상승으로 인한 이익 개선이 극대화될 것으로 예상…", p1 "파운드리에서도 가동률 상승에 따라 점진적 적자 축소가 진행될 것으로 판단" | 맞는 근거. fixture notes의 조건("1페이지 기업 직접 연결 긍정 요인 최소 하나")을 충족한다. 키워드만 달라서 실패했다. 원문 "악재를 해소하고"도 공백 제거 후 `악재해소`와 일치하지 않는다 |
| 2025-07-09 improvement-outlook | p1 / `하반기 개선\|실적 모멘텀\|적자 축소` | p1 "3Q25 컨벤셔널 디램 가격 상승으로 인한 이익 개선이 극대화될 것으로 예상…" | 부분적으로 맞다. 같은 페이지의 하반기 이익 개선 전망이다. 더 직접적인 문장 "하반기 개선될 실적 모멘텀…"(neutral)과 "…적자 축소가 진행될 것으로 판단"(positive, focus `개선/전망이나/하반기` 불일치)은 위의 두 필터에서 빠졌다 |
| 2026-06-29 second-quarter-cost-burden | p1 negative / `성과급 충당금\|예상을 하회\|영업이익 전망` | positive 항목 1개만 있다. p1 "Micron의 실적과 Guidance를 감안할 때 영업이익률은 80%를 상회…수익성 급상승으로 귀결" | 실제 실패. negative 항목이 없고 인용은 타사 수익성이다. 기대 문장 2개("…성과급 충당금을 2분기에 모두 반영…12.2% 하회하는 81.3조원…", "…2026년 영업이익 전망을 기존 대비 3.9% 하향")는 valid이고 focus도 통과하지만 관점이 neutral이라 관점 필터에서 빠졌다 |

- 분류기 문제: `classify_failure_stage`는 trace 후보 인용문에 topic 키워드가 없으면 단계를 `retrieval_candidate_excluded`로 둔다. summary-positive는 후보·생성·검증 선택이 모두 기대 페이지의 맞는 근거였는데도 검색 실패로 셌다. 후보가 0개인 4건도 원인이 검색이 아니라 분석 필터인데 같은 단계로 묶인다.
- 정리(케이스별 주원인): 관점 필터 3건(08-10 full-stack, 08-14 dram, 06-29 cost-burden), focus 필터 1건(08-14 foundry), OCR 레이아웃 혼입 1건(08-10 foundry), 분류기 오분류 1건(summary-positive, 근거는 맞음), 부분 성공 1건(improvement-outlook, 근거는 맞지만 더 직접적인 문장은 관점·focus 필터에서 빠짐). 7건 중 검색(hybrid_search)이나 적재가 원인인 경우는 없다.
- 수정안(미실행, 사용자 결정 필요): 아래 순서로 제안한다. 이 fixture들은 6단계 "dev 기준"이므로 규칙을 이 문장들에 맞추면 dev 과적합이 된다. 개선 효과는 test셋에서 따로 확인해야 한다.
  1. trace에 `retrieval_diagnostics`와 필터별 탈락 사유를 남긴다(평가 전용, 동작 불변).
  2. 분류기에 `analysis_filter_excluded`(perspective/focus/quality) 단계를 추가하고 topic 키워드 검사와 단계 판정을 분리한다. topic 판정은 키워드 대신 승인된 gold 페이지·문장 범위로 하는 방식을 검토한다.
  3. focus 필터를 hard filter에서 정렬 가산점으로 낮추거나, 토큰의 조사·어미 처리와 영문·한글 별칭(파운드리↔Foundry, LSI↔LS)을 보강한다.
  4. 관점 필터: neutral/ambiguous라도 focus가 일치하는 문장은 packet에 넣고, 관점은 생성 결과를 기존 evidence 검증으로 확인하게 한다. 또는 `economic_facts` 규칙(가격 인상→ASP 상승, 충당금 반영·하회, 적자상태 지속)을 테스트와 함께 보강한다.
  5. OCR 2단 레이아웃 혼입은 수집 단계(열 분리) 과제로 따로 둔다.

**수정안 1·2 실행 (2026-11-26, 사용자 결정: 진단 개선만 먼저, 필터 동작은 바꾸지 않음)**
- 테스트를 먼저 추가하고 실패를 확인했다(새 테스트 10개 실패, 기존 85개 통과). 그 뒤 구현해 통과시켰다.
- 1번 trace 보강: `collect_analysis_evidence`는 diagnostics dict를 받았을 때만 다음을 기록한다.
  - `filter_exclusions`: span마다 `page_number`, `filter`(`quality`/`perspective`/`focus`), `reason`. 인용문은 넣지 않는다.
  - `filter_counts`, `required_focus_terms`
  - `early_exit`: `requirement_unsupported`, `requirement_unmatched`, `coverage_incomplete`, `missing_years`, `compound_pack_incomplete` 중 하나
- `analysis_service`는 이 값을 JSON으로 저장할 수 있게 바꿔 `_evaluation_trace.retrieval_diagnostics`에 넣는다. 집합은 정렬된 목록으로 바꾼다. 같은 입력에서 diagnostics를 넘길 때와 넘기지 않을 때 packet이 같은지 테스트로 확인했다.
- 2번 분류기: 단계 판정에서 topic 키워드를 뺐고, 기대 페이지와 관점만 본다. topic은 `evaluate_case`의 `topic` 검사에만 남는다.
  - 기대 페이지 후보가 없고 trace에 기대 페이지의 필터 제외나 `early_exit`가 있으면 `analysis_filter_excluded`로 판정하고 `filter_reasons`를 붙인다. 결과 묶음은 `analysis_filter`이다.
  - 진단 기록이 없는 trace는 기존처럼 `retrieval_candidate_excluded`로 판정한다.
  - 참고값으로 `topic_in_expected_page_candidates`를 남긴다.
- `scripts/measure_generation.py --rescore`는 이제 저장된 응답과 trace를 현재 `evaluate_case`로 다시 판정한다. fixture SHA-256이 `run.json`과 다르면 실행하지 않는다. 출력 이름은 `--rescore-name`으로 정하며(기본 `rescored`), 기존 파일은 덮어쓰지 않는다.

**6단계 저장 응답 재채점 (API·생성 재호출 없음)**
- 실행: `--rescore evals/results/generation-faithfulness-20261126 --rescore-name reclassified`, 2026-11-26T05:19:39Z. 기준 커밋 `52fbf2b`에 작업 트리 변경이 있는 상태였다. 출력은 `report-reclassified.json`/`summary-reclassified.md`이다. 같은 폴더의 기존 파일 8개는 SHA-256이 실행 전과 같다.

| 묶음 | 6단계 (rescored) | 재채점 (reclassified) |
|---|---|---|
| passed | 10 | 10 |
| retrieval | 7 | 5 |
| judged_mismatch | 0 | 2 |
| analysis_filter | 0 | 0 |

- 바뀐 케이스: 07-09 summary-positive와 improvement-outlook이 `retrieval_candidate_excluded`에서 `selected`로 바뀌었다. 실패 항목은 `topic`만 남아 `judged_mismatch`로 묶인다.
- 06-29 second-quarter-cost-burden은 `retrieval_wrong_perspective`로 바뀌었다. 기대 페이지 후보는 positive 1개뿐이다.
- 08-10·08-14 4건은 `retrieval_candidate_excluded` 그대로다. 6단계 trace에는 `retrieval_diagnostics`가 없어서(이번 변경 전에 저장됨) 필터 원인을 trace만으로 판정할 수 없다. 이 4건을 `analysis_filter_excluded`로 보려면 분석을 다시 실행해야 한다(생성 호출 포함). 이번에는 실행하지 않았다.
- pass/fail 판정, citation 유효율 16/16, 거절 지표(5/5, 잘못된 거절 4/12)는 6단계와 같다.
- `./scripts/check.sh` 통과 (2026-11-26): backend 779 passed, frontend 17 passed, lint, build.
