# 로컬 실행·검증 가이드

README에서 옮긴 자세한 실행·검증 절차다. 요약은 [README](../README.md)의 빠른 실행을 본다.

## 프로젝트 구조

```text
stock-brief-ai/
├── frontend/              # Next.js 분석 화면
├── ocr-worker/            # PaddleOCR PP-StructureV3 CPU worker
├── backend/
│   ├── app/               # API, 검색, PDF/OCR, evidence 검증
│   └── tests/
├── db/                    # PostgreSQL / pgvector
├── evals/                 # 평가 fixture 및 결과
├── scripts/               # 평가 및 검증 스크립트
├── docs/                  # 아키텍처, 플랜, 실행 가이드, 날짜별 기록
├── docker-compose.yml
├── api-contract.md
├── acceptance.md
├── qa-rules.md
└── README.md
```

## 주요 모듈

### `evidence_requirements.py`

질문에 답하기 위해 필요한 근거 조건을 정의하고 실제 검색 결과가 이를 충족하는지 확인한다.

### `evidence_bundle.py`

서로 다른 페이지나 형태의 근거를 하나의 evidence bundle로 구성하고 coverage를 계산한다.

### `structured_cells.py`

표에서 추출한 셀을 행·열 및 주변 헤더와 연결해 구조화한다.

### `paddle_tables.py`

표 추출 결과를 처리하고 수치와 단위가 올바르게 연결됐는지 검증한다.

## 로컬 실행

요구 사항은 Docker와 Docker Compose다.

```bash
cp .env.example .env
docker compose up --build
```

- 웹: <http://localhost:3000>
- API health: <http://localhost:8001/health>
- API 문서: <http://localhost:8001/docs>
- PostgreSQL: `localhost:5432`

`.env`의 `FRONTEND_HOST_PORT`, `BACKEND_HOST_PORT`, `POSTGRES_HOST_PORT`로 호스트 포트를 바꿀 수 있다. backend 기본값은 기존 8000 서비스와 충돌하지 않도록 `8001`이다. `.env`는 Git에서 제외된다. PostgreSQL과 업로드 파일은 각각 named volume에 보존된다. 종료는 `docker compose down`으로 하며 모든 DB·업로드 데이터를 함께 제거하려는 경우에만 데이터 손실을 인지한 뒤 `docker compose down -v`를 사용한다.

임베딩과 기본 분석 생성은 맥 호스트 Ollama를 사용한다. Gemini를 쓸 때만 실제 키를 루트 `.env`의 `GEMINI_API_KEY`에 둔다.

```dotenv
EMBEDDING_PROVIDER=ollama
OLLAMA_BASE_URL=http://host.docker.internal:11434
EMBEDDING_MODEL=bge-m3
EMBEDDING_DIMENSIONS=1024
GENERATION_PROVIDER=ollama
GENERATION_MODEL=gemma3:4b
GENERATION_TEMPERATURE=0
OLLAMA_GENERATION_TIMEOUT_SECONDS=600
ANALYSIS_EXTERNAL_ENABLED=0
ANALYSIS_OLLAMA_FALLBACK_ENABLED=0
GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.7-flash
GEMINI_TIMEOUT_SECONDS=30
GEMINI_MAX_ATTEMPTS=2
GEMINI_RETRY_BASE_DELAY_SECONDS=1
DB_POOL_RECYCLE_SECONDS=300
```

기본 요청은 `execution_mode=LOCAL_ONLY`, `external_consent=false`이며 Ollama를 사용한다. 외부 모드는 `ANALYSIS_EXTERNAL_ENABLED=1`과 이번 요청의 명시적 boolean 동의를 모두 요구한다. `FALLBACK_ALLOWED`는 추가로 `ANALYSIS_OLLAMA_FALLBACK_ENABLED=1`을 요구한다. API 키와 기존 `ANALYSIS_LLM_PROVIDER`/`ANALYSIS_LLM_FALLBACK_PROVIDER`는 요청 모드를 바꾸지 않는다. 정책 설정은 동의를 대신하지 않는다.

Gemini는 HTTP429/500/502/503/504·네트워크·timeout만 application 최대2회(기본값) 재시도한다. SDK attempts1은 최초 요청을 포함한다. 외부 전용 모드는 소진 후 오류, fallback 허용 모드는 gemma3:4b를 한 번 호출한다. 키/인증/모델/안전/JSON/schema/citation 실패는 fallback으로 숨기지 않는다.

응답의 `execution`에는 요청 모드·동의·외부 요청 시도·최종 provider·fallback 여부가 기록된다. UI는 `/api/v1/analyses/stream`의 검색·생성·fallback·검증 상태와 검증 완료 결과를 표시한다. 미검증 모델 텍스트는 streaming하지 않는다. 외부 전송 범위는 질문·기업/발행 메타데이터·선택된 검증 근거 발췌/UUID/페이지/사실·지시문/schema다. PDF/이미지/embedding/전체 provenance는 전송하지 않는다. 재시도/native timing은 내부 trace에 남고 키·prompt·원문은 로그에 기록하지 않는다.

## Ollama 설치 전후 실행

Ollama 설치 전에도 다음 명령으로 서비스가 기동되며 PDF 적재와 BM25-only 검색을 사용할 수 있다.

```bash
docker compose up --build
```

벡터 검색을 사용하려면 macOS에 Ollama를 설치·실행한 뒤 호스트 터미널에서 다음을 실행한다. 기본 분석 생성은 로컬 Ollama를 사용한다.

```bash
ollama pull bge-m3
ollama list
docker compose up --build
```

로컬 분석 또는 승인된 로컬 fallback에는 `gemma3:4b` 모델이 필요하다.

backend 컨테이너는 `http://host.docker.internal:11434`로 맥 호스트 Ollama에 연결한다. 별도 Ollama 컨테이너는 생성하지 않는다.

Ollama 설치 전에는 UI와 적재·BM25 기능을 확인할 수 있지만 벡터 임베딩에는 `bge-m3`가 필요하다. 기본 분석 생성에는 `gemma3:4b`가 필요하다. Gemini API 키는 외부 모드를 쓸 때만 필요하다.

pgvector 활성화 확인:

```bash
docker compose exec postgres psql -U stock_brief -d stock_brief -c "SELECT extname FROM pg_extension WHERE extname = 'vector';"
```

## 마이그레이션

backend 컨테이너는 시작할 때 자동으로 `alembic upgrade head`를 실행한다. 수동 실행과 현재 revision 확인은 다음과 같다.

```bash
docker compose run --rm backend alembic upgrade head
docker compose run --rm backend alembic current
```

## 실제 PDF 적재 테스트

저작권과 이용 권한을 확인한 PDF를 저장소에 커밋하지 말고 API로 직접 전송한다.

```bash
curl -X POST http://localhost:8001/api/v1/documents \
  -F 'file=@/absolute/path/to/report.pdf;type=application/pdf' \
  -F 'company_name=기업명' \
  -F 'stock_code=종목코드' \
  -F 'document_type=broker_report' \
  -F 'issuer=발행기관' \
  -F 'published_at=2026-08-23'
```

DART 공시는 `document_type=dart_filing`을 사용한다. 최대 크기 기본값은 50 MiB이며 `.env`의 `MAX_UPLOAD_BYTES`로 조정한다. 로컬 Docker 밖에서 `backend/data/raw/`에 파일을 둘 수도 있지만 PDF와 생성 페이지 이미지는 `.gitignore` 대상이다. API 목록/상세/페이지 확인:

분석 출처 카드의 `원문 PDF N페이지 보기`는 `GET /api/v1/documents/{document_id}/file?page_number=N#page=N`을 새 탭으로 연다. endpoint는 해당 문서의 `data/raw` 내부 실제 PDF만 inline으로 제공하며, 존재하지 않는 문서·범위 밖 페이지·경로 이탈 파일은 `404` 또는 입력 검증 오류로 거부한다.

```bash
curl http://localhost:8001/api/v1/documents
curl http://localhost:8001/api/v1/documents/DOCUMENT_UUID
curl http://localhost:8001/api/v1/documents/DOCUMENT_UUID/pages/1
```

## 하이브리드 검색 수동 검증

다음 순서로 실제 사용 권한이 있는 문서를 검증한다.

1. 위 업로드 API로 PDF를 적재하고 응답의 `document_id`를 기록한다.
2. 호스트에서 `ollama pull bge-m3`와 `ollama list`를 실행하고 임베딩을 생성한다.

```bash
curl -X POST http://localhost:8001/api/v1/documents/DOCUMENT_UUID/embeddings
curl http://localhost:8001/api/v1/documents/DOCUMENT_UUID/embedding-status
```

3. 하이브리드 검색을 호출한다.

```bash
curl -X POST http://localhost:8001/api/v1/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"삼성전자 HBM 악재","top_k":5}'
```

4. 각 결과의 `document_name`, `published_at`, `publisher`, `document_type`, `page_number`, `quote`를 실제 PDF와 대조한다. 검색 결과가 없으면 `no_evidence`와 빈 배열이어야 하며 이를 생성형 문장으로 보완하지 않는다.

## 메타데이터 교정과 최종 분석 검증

업로드 응답의 `DOCUMENT_UUID`를 사용한다. Swagger(<http://localhost:8001/docs>)에서 `PATCH /api/v1/documents/{document_id}/metadata`를 열어 다음 실제 테스트 문서 메타데이터 예시를 적용할 수 있다.

```json
{
  "company_name": "삼성전자",
  "stock_code": "005930",
  "document_type": "broker_report",
  "issuer": "한화리서치",
  "published_at": "2025-07-09"
}
```

같은 요청을 curl로 호출하는 방법:

```bash
curl -X PATCH http://localhost:8001/api/v1/documents/DOCUMENT_UUID/metadata \
  -H 'Content-Type: application/json' \
  -d '{"company_name":"삼성전자","stock_code":"005930","document_type":"broker_report","issuer":"한화리서치","published_at":"2025-07-09"}'
```

그 뒤 임베딩을 만들고 분석 API 또는 브라우저를 사용한다.

```bash
curl -X POST http://localhost:8001/api/v1/documents/DOCUMENT_UUID/embeddings
curl -X POST http://localhost:8001/api/v1/analyses \
  -H 'Content-Type: application/json' \
  -d '{"document_id":"DOCUMENT_UUID","question":"삼성전자 HBM 악재","top_k":10}'
```

실제 수동 검증 순서는 다음과 같다.

1. 사용 권한이 있는 PDF를 업로드한다.
2. 기업명·6자리 종목코드·문서 유형·발행기관·발행일을 교정한다.
3. 문서 임베딩 생성 API를 호출한다.
4. 브라우저 <http://localhost:3000>에서 문서를 선택한다.
5. 기본 질문 또는 `삼성전자 HBM 악재`로 분석을 실행한다.
6. 모든 호재·악재의 파일명, 발행기관, 발행일, PDF 페이지와 DB 원문 인용문을 실제 PDF와 대조한다.

임베딩 미생성은 `409`, Gemini 키·인증·모델 설정 오류는 안전한 설정 오류로 반환한다. 근거가 부족하면 항목을 채우지 않고 부족 안내를 표시한다. 생성 결과, 실제 PDF와 API 키는 저장소에 커밋하지 않는다.

`OLLAMA_GENERATION_TIMEOUT_SECONDS`는 로컬 모델의 첫 생성과 연속 평가 부하를 고려한 제한이며 기본값은 600초다. 평가 CLI의 요청 제한은 이보다 30초 긴 630초다. 분석 오류는 연결 실패·Ollama HTTP 오류·응답 envelope 오류·모델 JSON 파싱/Schema 오류를 구분한다. HTTP 오류가 발생하면 backend 로그에 상태 코드와 최대 1,000자의 응답 일부가 기록되지만 프롬프트, 비밀값 또는 PDF 전체 원문은 기록하지 않는다.

`GENERATION_TEMPERATURE` 기본값은 `0`이다. 같은 모델·문서·질문으로 품질을 반복 비교할 때 출력 변동을 줄이기 위한 설정이며 Gemini와 Ollama 생성 설정에 동일하게 전달된다. 재현성 평가에서는 이 값을 유지한다.

Gemini 실제 호출 최소 확인(`.env`에 `ANALYSIS_EXTERNAL_ENABLED=1`과 `GEMINI_API_KEY` 필요):

```bash
docker compose up --build -d
curl -X POST http://localhost:8001/api/v1/analyses \
  -H 'Content-Type: application/json' \
  -d '{"document_id":"DOCUMENT_UUID","execution_mode":"EXTERNAL_WITH_CONSENT","external_consent":true}'
```

HTTP 200 응답의 `generation_model`이 `.env`의 `GEMINI_MODEL`과 일치하는지 확인한다. 기존 `analysis_status`, summary·positives·negatives·citations 계약은 그대로다. 오류 로그에는 provider·model·오류 유형만 남기며 키, 전체 프롬프트와 문서 전문은 기록하지 않는다.

분석 API는 사용자 질문 외에 호재·악재 관점의 한국어 보조 검색을 같은 문서 안에서 수행한다. 투자등급·면책 안내와 문맥 없는 숫자 표 조각은 제외하며, citation의 `quote`는 저장된 페이지의 연속 원문 발췌다. 문서 전체 후보 추출은 문장을 청크 경계 너머로 복원할 수 있으며, 이를 덮는 모든 `source_chunk_ids`와 오프셋을 검증한다. 전체 문서 후보는 검색 top-k 밖에서도 선택될 수 있고, 320자 제한은 일부 발췌 미리보기 함수에만 적용된다. `display_quote`는 원본을 바꾸지 않고 한글 단어 중간 줄바꿈과 단독 OCR 잡음만 정리한다. 표 중심 근거는 같은 페이지에서 지표·행·단위·기간·값을 모두 확인하고 값이 quote에도 존재할 때만 `table_facts` 핵심 수치 카드로 표시한다. 표 구조나 제목 OCR이 모호하면 값을 추측하지 않고 숫자 덩어리를 숨긴 채 원문 페이지 확인 안내를 반환한다. 한국어 질문의 영어 항목과 같은 chunk를 재사용한 후속 항목은 사용자 응답에서 제거한다.

일반 문장 citation은 완결 문장 1~2개만 선택하며 최대 길이를 맞추려고 문장이나 단어를 자르지 않는다. 검색 chunk는 문장·문단·검증된 표 행 evidence span으로 나누고, Analyst·이메일·연락처·핵심 OCR 잡음이 있는 span만 제외한다. 같은 chunk의 정상 span은 유지하며, 서로 겹치지 않는 긍정·부정 span은 각각 근거로 사용할 수 있다. 동일하거나 80% 이상 겹치는 span은 중복 표시하지 않는다. API는 `source_chunk_id`, `char_start`, `char_end`로 원문 범위를 보존한다. AMD·HBM·DRAM·NAND·Foundry/LS·CSP 같은 정상 용어는 유지한다. 카드 제목은 원문에서 확인되는 구체적인 사업·실적 원인을 포함해야 하며 주가 전망·단기 매력·저평가 또는 의미 없는 일반 제목은 서버 검증에서 제거한다. 핵심 요약은 최종 생존 카드 제목만 사용한다.

기본 호재·악재 요약처럼 특정 핵심어가 없는 범용 질문은 사용자 문구와 분리된 긍정·부정 보조 query를 실행하고 관점별 후보를 균형 있게 생성 모델에 전달한다. 유효 근거가 한 관점에 1개뿐이어도 citation과 함께 정상 결과로 반환하며, 두 관점 모두 직접 근거가 없으면 기존처럼 `확인할 수 없습니다`를 반환한다.

범용 질문에서 모델이 한쪽 polarity를 생략하더라도 해당 관점에 검증된 별도 evidence span 후보가 있으면 서버가 그 원문 범위를 연결한 중립적 리포트 해석 항목을 하나 복원한다. 후보가 없으면 항목을 만들지 않는다. 같은 원본 chunk라도 서로 다른 완결 문장 범위면 양쪽 관점에 사용할 수 있고, 같은 span 또는 대부분 겹치는 인용만 중복을 막는다. 인용 발췌는 DB의 연속 문자열만 사용하고 `be`처럼 의미 없는 짧은 OCR 단독 줄을 경계로 인접 문장 확장을 멈춘다. 표의 음수 수치를 근거로 쓰는 경우에는 같은 PDF 페이지의 연속 원문에서 표 제목, 기간 헤더와 영업이익 지표를 함께 복원할 수 있을 때만 표시한다. 검증된 카드가 있는데 모델 요약이 비어 있거나 금지 문체이면 서버는 검증된 항목 제목만 사용해 `보고서는 … 언급합니다` 형식의 중립 요약을 표시한다.

빈 호재·악재 영역은 관련 근거 자체가 없는 `no_evidence`와 후보가 있었지만 OCR·표 구조 때문에 안전하게 표시하지 못한 `extraction_limited`를 구분한다. 후자는 깨진 OCR 문자열이나 내부 제외 사유 대신 `표시 가능한 … 근거를 원문에서 신뢰성 있게 추출하지 못했습니다.` 안내와 해당 PDF 페이지 링크를 표시한다.

## 다중 문서 RAG 평가

버전 관리 가능한 fixture는 `evals/fixtures/*.json`에 둔다. fixture에는 document UUID 대신 원본 파일명, 기업명, 발행일과 문서 유형을 저장한다. 평가 실행 시 `GET /api/v1/documents` 결과에서 네 필드가 모두 일치하는 문서를 찾는다. 일치 문서가 없으면 해당 fixture는 실패가 아니라 `SKIP`이다.

현재 평가셋은 삼성전자 증권사 리포트 5개, 총 17개 case로 구성된다. 한화투자증권 2025-07-09 리포트의 기존 5개 case는 그대로 유지하며, 현대차증권 2026-06-29·2026-07-31 및 미래에셋증권 2026-08-10·2026-08-14 리포트에 각각 3개 case가 있다. 새 문서별 case는 실제 원문에서 확인한 긍정 요인, 위험·실적 부담, 문서에 근거가 없는 질문을 하나 이상 포함한다.

### Provider별 실제 기준선

서로 다른 provider 결과를 합산하지 않는다.

| 실행일 | Provider / model | 설정 | Pass | Fail | Skip | 비고 |
|---|---|---|---:|---:|---:|---|
| 2026-08-24 | Ollama / `gemma3:4b` | 로컬 Ollama | 14 | 3 | 0 | fallback provider 별도 기준선 |
| 2026-08-25 | Gemini / `gemini-3.7-flash` | fallback `none`, timeout 30초 | 5 | 12 | 0 | 통과 5건은 retrieval 근거 부족 사례로 생성 미호출. 생성 필요 12건은 provider request 오류 |
| 2026-11-26 | Ollama / `gemma3:4b` | `LOCAL_ONLY`, fallback 꺼짐 | 10 | 7 | 0 | 실패 7건 모두 검색 단계, citation 16/16 유효. dev 기준(`docs/plans/rag-보강.md` 6단계) |

Gemini 실패 12건은 evaluation의 `request_error`이며 retrieval/generation 선택 또는 output validation 실패로 통과 처리하지 않았다. 실제 실행에서 HTTP 503 6건, HTTP 504 5건, client timeout 1건이었다. 짧은 Interactions API 구조화 요청은 임시 120초 제한에서 성공했지만 전체 evidence 분석은 120초에도 timeout이었고, 후속 진단에서는 HTTP 429가 확인됐다. 따라서 이 기준선은 분석 품질 점수가 아니라 현재 quota·latency 조건에서의 provider 가용성 기준선이다. fixture 기대값은 변경하지 않았다.

기본 실행은 콘솔에 결과만 출력하며 파일을 만들지 않는다.

```bash
python3 scripts/evaluate.py
```

특정 fixture 또는 UUID를 명시할 수도 있다. UUID는 fixture에 저장하지 않는다.

```bash
python3 scripts/evaluate.py --fixtures evals/fixtures/samsung-electronics-2025-07-09.json \
  --document-id DOCUMENT_UUID

python3 scripts/evaluate.py \
  --document-id samsung-electronics-2025-07-09=DOCUMENT_UUID
```

결과 파일은 명시적으로 `--output`을 준 경우에만 생성된다. `evals/results/`는 Git에서 제외된다.

```bash
python3 scripts/evaluate.py --output evals/results/local-ollama.json
```

각 case는 분석 API 성공, 한국어 출력, 기대 polarity 항목, citation 연결, 기대 PDF 페이지, 주제 키워드, 투자등급·면책·문맥 없는 숫자/% 나열의 부재를 검사한다. `insufficient` case는 호재·악재와 citation을 억지로 만들지 않았을 때만 통과한다. 제목 완전 일치는 요구하지 않는다.

실패 시 콘솔의 `stage`는 원인을 다음처럼 분리한다.

- `retrieval_candidate_excluded`: 기대 페이지·주제의 관련 청크가 분석 후보에 없음
- `retrieval_wrong_perspective`: 관련 청크는 있지만 기대 polarity 후보로 분류되지 않음
- `generation_not_selected`: 올바른 후보가 모델에 전달됐지만 모델이 해당 chunk ID를 선택하지 않음
- `output_validation_removed`: 모델은 선택했지만 기존 안전·근거 검증을 통과하지 못함

진단 정보는 분석 실행 기록의 내부 trace에 저장되고 OpenAPI에서 숨긴 평가 전용 경로로만 CLI가 읽는다. 일반 분석 API 응답과 웹 UI에는 노출되지 않는다.

새 문서 fixture 템플릿:

```json
{
  "schema_version": 1,
  "document": {
    "filename": "원본 파일명.pdf",
    "company_name": "기업명",
    "published_at": "2026-08-24",
    "document_type": "broker_report"
  },
  "cases": [
    {
      "id": "unique-case-id",
      "question": "원문으로 확인할 질문",
      "expected_topic": "핵심어1|핵심어2",
      "expected_polarity": "positive",
      "expected_pages": [1],
      "notes": "PDF 원문을 직접 확인한 기대 근거와 판정 의도"
    }
  ]
}
```

추가 PDF의 등록 절차:

1. 사용 권한이 있는 PDF를 업로드하되 저장소에는 추가하지 않는다.
2. 메타데이터 PATCH API로 기업명·종목코드·문서 유형·발행기관·발행일을 교정한다.
3. 문서 임베딩 생성 API를 호출한다.
4. `GET /api/v1/documents`로 파일명·기업명·발행일·문서 유형을 확인한다.
5. PDF 원문 페이지를 직접 확인하고 위 템플릿으로 문서별 질문, polarity와 기대 페이지 fixture를 추가한다.
6. `python3 scripts/evaluate.py`로 현재 DB에 있는 모든 fixture 문서를 한 번에 평가한다. 아직 업로드하지 않은 문서는 `SKIP`으로 집계된다.

CI와 단위 테스트는 실제 Gemini API나 Ollama를 호출하지 않는다. fixture schema, 메타데이터 문서 매칭과 판정기는 고정된 fake 분석 응답으로 검증한다. 실제 품질 평가는 선택한 provider를 설정한 로컬 환경에서 위 CLI로 별도 수행한다.

긴 Ollama 생성 중에는 retrieval transaction을 먼저 종료해 DB 연결을 pool에 돌려준다. PostgreSQL engine은 `pool_pre_ping`을 사용하고 `DB_POOL_RECYCLE_SECONDS` 기본값 300초를 적용한다. 생성 완료 후 `analysis_runs` 저장에서 연결이 한 번 끊기면 현재 session을 rollback하고 새 session으로 같은 검증 결과만 한 번 다시 저장하며, Ollama 생성은 반복하지 않는다.

일반 검색 API는 HNSW 인덱스를 유지한다. 다중 query expansion을 연속 실행하는 분석 경로는 로컬 ARM Docker 환경에서 관찰된 pgvector HNSW backend-process 종료를 피하기 위해 선택 문서 범위의 exact cosine scan을 사용한다. 임베딩, cosine 거리, BM25 후보, 필터와 RRF 결합 규칙은 동일하다.

## 로컬 검증

Docker 밖에서 전체 검증을 실행하려면 Python 3.12+, Node.js 22+, backend 개발 의존성과 frontend 패키지가 필요하다.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements-dev.txt
npm --prefix frontend install
./scripts/check.sh
```

`scripts/check.sh`는 backend test, frontend 상태 test, frontend lint, frontend production build 순서로 실행된다.
