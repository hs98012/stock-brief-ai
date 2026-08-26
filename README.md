# Stock Brief AI

증권사 기업분석 리포트 PDF와 DART 공시 PDF를 바탕으로 기업의 핵심 내용과 긍정·부정 요인을 초보자에게 근거와 함께 설명하기 위한 독립형 포트폴리오 프로젝트다. 모든 핵심 주장은 원본 파일명, 발행일, PDF 페이지 번호, 근거 문장을 요구한다. 투자 권유, 매수·매도 추천 및 자동매매는 범위 밖이다.

현재 4차 단계는 PDF 적재, 맥 호스트 Ollama `bge-m3` 하이브리드 검색과 Gemini Flash 근거 기반 분석을 제공한다. 웹에서 문서를 선택하고 메타데이터를 교정한 뒤 핵심 요약과 최대 3개의 호재·악재를 출처 카드와 함께 확인할 수 있다. 채팅, 투자 판단과 자동매매는 포함하지 않는다.

## 구성

- `frontend/`: Next.js, TypeScript, Tailwind CSS 분석 화면과 상태 컴포넌트 테스트
- `backend/`: FastAPI, Alembic, PDF/OCR 적재, Ollama 임베딩, Gemini/Ollama 생성 provider, BM25·pgvector·RRF 검색과 근거 검증
- `db/`: PostgreSQL 16 및 pgvector
- `docker-compose.yml`: frontend, backend, postgres 로컬 구성
- `product.md`: MVP 화면과 사용자 흐름
- `acceptance.md`: 완료 및 품질 기준
- `api-contract.md`: 현재/예정 API와 evidence 응답 계약
- `qa-rules.md`: 인용·금융 표현·안전 검증 규칙
- `AGENTS.md`: 개발 원칙과 데이터 모델 계약

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

임베딩은 맥 호스트 Ollama를 유지하고 분석 생성만 Gemini Flash를 사용한다. 실제 키는 루트 `.env`의 `GEMINI_API_KEY`에만 둔다.

```dotenv
EMBEDDING_PROVIDER=ollama
OLLAMA_BASE_URL=http://host.docker.internal:11434
EMBEDDING_MODEL=bge-m3
EMBEDDING_DIMENSIONS=1024
GENERATION_PROVIDER=ollama
GENERATION_MODEL=gemma3:4b
GENERATION_TEMPERATURE=0
OLLAMA_GENERATION_TIMEOUT_SECONDS=600
ANALYSIS_LLM_PROVIDER=gemini
ANALYSIS_LLM_FALLBACK_PROVIDER=none
GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.7-flash
GEMINI_TIMEOUT_SECONDS=30
GEMINI_MAX_ATTEMPTS=2
GEMINI_RETRY_BASE_DELAY_SECONDS=1
DB_POOL_RECYCLE_SECONDS=300
```

`ANALYSIS_LLM_PROVIDER=gemini`가 기본이다. Gemini는 HTTP 429·503·504, 네트워크 연결 오류와 client timeout만 `GEMINI_MAX_ATTEMPTS` 횟수까지 재시도한다. 재시도 간격은 `GEMINI_RETRY_BASE_DELAY_SECONDS`를 시작값으로 하는 지수 백오프다. `ANALYSIS_LLM_FALLBACK_PROVIDER=none`이면 재시도 소진 후 오류를 반환한다. `ollama`로 설정하면 재시도 소진 뒤 기존 `gemma3:4b`를 정확히 한 번 호출한다. 키 누락, HTTP 401·403·404, 안전 차단, JSON/Schema/citation 검증 실패에는 재시도하거나 fallback하지 않는다.

분석 실행 기록에는 최종 provider/model과 fallback 사용 여부가 저장된다. 재시도 횟수, HTTP 상태, fallback 여부와 지연 시간은 내부 평가 trace 및 구조화 로그에만 남고 일반 분석 API 응답이나 UI에는 노출되지 않는다. 로그에는 API 키, 전체 프롬프트, PDF 원문을 기록하지 않는다.

## Ollama 설치 전후 실행

Ollama 설치 전에도 다음 명령으로 서비스가 기동되며 PDF 적재와 BM25-only 검색을 사용할 수 있다.

```bash
docker compose up --build
```

벡터 검색을 사용하려면 macOS에 Ollama를 설치·실행한 뒤 호스트 터미널에서 다음을 실행한다. 기본 분석 생성은 `.env`의 Gemini 설정을 사용한다.

```bash
ollama pull bge-m3
ollama list
docker compose up --build
```

`ANALYSIS_LLM_FALLBACK_PROVIDER=ollama`를 사용할 때만 `ollama pull gemma3:4b`를 추가로 실행한다.

backend 컨테이너는 `http://host.docker.internal:11434`로 맥 호스트 Ollama에 연결한다. 별도 Ollama 컨테이너는 생성하지 않는다.

Ollama 설치 전에는 UI와 적재·BM25 기능을 확인할 수 있지만 벡터 임베딩에는 `bge-m3`가 필요하다. 기본 분석 생성에는 Gemini API 키가 필요하며, `gemma3:4b`는 Ollama fallback을 명시적으로 켰을 때만 필요하다.

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

Gemini 실제 호출 최소 확인:

```bash
docker compose up --build -d
curl -X POST http://localhost:8001/api/v1/analyses \
  -H 'Content-Type: application/json' \
  -d '{"document_id":"DOCUMENT_UUID"}'
```

HTTP 200 응답의 `generation_model`이 `.env`의 `GEMINI_MODEL`과 일치하는지 확인한다. 기존 `analysis_status`, summary·positives·negatives·citations 계약은 그대로다. 오류 로그에는 provider·model·오류 유형만 남기며 키, 전체 프롬프트와 문서 전문은 기록하지 않는다.

분석 API는 사용자 질문 외에 호재·악재 관점의 한국어 보조 검색을 같은 문서 안에서 수행한다. 투자등급·면책 안내와 문맥 없는 숫자 표 조각은 제외하며, citation의 `quote`는 DB 청크에 실제 존재하는 최대 320자의 관련 원문 발췌다. `display_quote`는 원본을 바꾸지 않고 한글 단어 중간 줄바꿈과 단독 OCR 잡음만 정리한다. 표 중심 근거는 같은 페이지에서 지표·행·단위·기간·값을 모두 확인하고 값이 quote에도 존재할 때만 `table_facts` 핵심 수치 카드로 표시한다. 표 구조나 제목 OCR이 모호하면 값을 추측하지 않고 숫자 덩어리를 숨긴 채 원문 페이지 확인 안내를 반환한다. 한국어 질문의 영어 항목과 같은 chunk를 재사용한 후속 항목은 사용자 응답에서 제거한다.

기본 호재·악재 요약처럼 특정 핵심어가 없는 범용 질문은 사용자 문구와 분리된 긍정·부정 보조 query를 실행하고 관점별 후보를 균형 있게 생성 모델에 전달한다. 유효 근거가 한 관점에 1개뿐이어도 citation과 함께 정상 결과로 반환하며, 두 관점 모두 직접 근거가 없으면 기존처럼 `확인할 수 없습니다`를 반환한다.

범용 질문에서 모델이 한쪽 polarity를 생략하더라도 해당 관점에 검증된 별도 DB 후보가 있으면 서버가 원문 chunk ID를 그대로 연결한 중립적 리포트 해석 항목을 하나 복원한다. 후보가 없으면 항목을 만들지 않으며, 같은 청크를 호재·악재에 중복 사용하지 않는다. 인용 발췌는 DB의 연속 문자열만 사용하고 `be`처럼 의미 없는 짧은 OCR 단독 줄을 경계로 인접 문장 확장을 멈춘다. 표의 음수 수치를 근거로 쓰는 경우에는 같은 PDF 페이지의 연속 원문에서 표 제목, 기간 헤더와 영업이익 지표를 함께 복원할 수 있을 때만 표시한다. 검증된 카드가 있는데 모델 요약이 비어 있거나 금지 문체이면 서버는 검증된 항목 제목만 사용해 `보고서는 … 언급합니다` 형식의 중립 요약을 표시한다.

## 다중 문서 RAG 평가

버전 관리 가능한 fixture는 `evals/fixtures/*.json`에 둔다. fixture에는 document UUID 대신 원본 파일명, 기업명, 발행일과 문서 유형을 저장한다. 평가 실행 시 `GET /api/v1/documents` 결과에서 네 필드가 모두 일치하는 문서를 찾는다. 일치 문서가 없으면 해당 fixture는 실패가 아니라 `SKIP`이다.

현재 평가셋은 삼성전자 증권사 리포트 5개, 총 17개 case로 구성된다. 한화투자증권 2025-07-09 리포트의 기존 5개 case는 그대로 유지하며, 현대차증권 2026-06-29·2026-07-31 및 미래에셋증권 2026-08-10·2026-08-14 리포트에 각각 3개 case가 있다. 새 문서별 case는 실제 원문에서 확인한 긍정 요인, 위험·실적 부담, 문서에 근거가 없는 질문을 하나 이상 포함한다.

### Provider별 실제 기준선

서로 다른 provider 결과를 합산하지 않는다.

| 실행일 | Provider / model | 설정 | Pass | Fail | Skip | 비고 |
|---|---|---|---:|---:|---:|---|
| 2026-08-24 | Ollama / `gemma3:4b` | 로컬 Ollama | 14 | 3 | 0 | fallback provider 별도 기준선 |
| 2026-08-25 | Gemini / `gemini-3.7-flash` | fallback `none`, timeout 30초 | 5 | 12 | 0 | 통과 5건은 retrieval 근거 부족 사례로 생성 미호출. 생성 필요 12건은 provider request 오류 |

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

## 변경 파일 목록

- 루트: `.gitignore`, `.env.example`, `README.md`, `product.md`, `acceptance.md`, `api-contract.md`, `qa-rules.md`, `AGENTS.md`, `docker-compose.yml`
- backend 2차: Alembic 설정 및 최초 migration, SQLAlchemy 모델·DB session, 문서 API schema/service, PDF/OCR 파이프라인, 청킹·인용 복원 함수, 업로드 데이터 안내
- backend 3차: 1024차원 vector/HNSW 안전 migration, Ollama provider·상태 서비스, BM25 tokenizer, cosine 검색, RRF 및 검색 API
- backend 4차: nullable 종목코드·`analysis_runs` migration, 메타데이터 PATCH, Ollama JSON Schema 생성 provider, 문서 범위 검색·근거 허용 목록·citation 복원 분석 서비스와 API
- backend 테스트: 기존 회귀 테스트와 생성 HTTP mock, JSON Schema, 잘못된 근거 ID 거부, citation 없는 항목 제거, 근거 부족, 503, 메타데이터 검증
- frontend: 실제 FastAPI 문서 선택·메타데이터 수정·질문·분석 화면, 출처 카드, 로딩·성공·근거 부족·오류 컴포넌트 테스트
- DB/검증: `db/init.sql`, `scripts/check.sh`, `scripts/evaluate.py`, `evals/fixtures/`

## 검증 결과

2026-08-23 4차 로컬 검증 결과:

- backend pytest: 33개 통과
- frontend Vitest: 상태 렌더링 4개 통과
- frontend production build 및 ESLint: 통과
- 최종 `./scripts/check.sh`: 성공
- `npm audit`: 개발 의존성 설치 시 critical 1건이 보고되었으며 기능 검증 후 별도 의존성 점검이 필요하다. 자동 `--force` 수정은 적용하지 않았다.
- Docker backend 4차 이미지: `/health` HTTP 200, `{\"status\":\"ok\"}` 확인
- Docker frontend 이미지의 기존 기동 이력은 유지하며, 4차 분석 화면은 production build와 상태 컴포넌트 테스트로 검증
- PostgreSQL 16 컨테이너: healthcheck 정상, `vector` extension 활성화 확인
- Alembic: 실제 PostgreSQL에 `20260823_0004 (head)` 적용, nullable `documents.stock_code`와 `analysis_runs` 테이블 확인
- 안전 migration: 기존 non-null embedding 0개를 확인한 뒤 차원 변경; non-null이면 migration을 중단하는 테스트 통과
- Ollama: Docker backend에서 맥 호스트 Ollama의 `bge-m3` 감지 및 검색어 로컬 임베딩 요청 확인
- 유료 API 차단: backend 이미지에 OpenAI SDK가 설치되지 않았고 OpenAI 키 설정도 없음
- OCR 런타임: Docker 이미지에서 Poppler와 Tesseract 언어팩 `kor`, `eng` 확인
- `docker compose config`: 성공

1차 검증에서 확인된 기존 WordPress의 8000 포트 점유를 피하기 위해 backend 기본 호스트 포트를 8001로 변경했다.

## 다음 단계

1. 실제 사용 권한이 있는 한국어 문서 골든셋으로 검색 recall과 근거 충실도를 평가한다.
2. PostgreSQL에 분석 항목·citation을 정규화해 장기 보존할 필요가 있는지 검토한다.
3. `gemma3:4b` 구조화 출력의 실패율·금지 표현·문서 시점 구분을 별도 평가한다.
4. 현재 보고된 frontend 개발 의존성 취약점의 영향 범위를 확인하고 호환 가능한 버전으로 갱신한다.
