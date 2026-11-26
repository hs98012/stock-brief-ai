# API contract

## PP-StructureV3 신규 적재

공개 API 필드와 `text_source` enum은 유지한다. 새 file hash의 복잡 페이지는 내부 CPU worker의 PP-StructureV3 결과를 우선 사용한다. `page_extractions.provenance`에 `paddle_structure`, `paddle_tables`, `paddle_model`, `primary_engine`, 실패 시 `paddle_error`가 추가된다. 표·수치 출처는 `paddle_structure`이며 물리 페이지, 원문 문자 범위와 PDF point bbox를 함께 보존한다. 기존 페이지와 shadow revision은 자동 교체하지 않는다. 새 DB migration은 없다.

## 공통 규칙

- Base URL: 로컬 기본값 `http://localhost:8001` (`BACKEND_HOST_PORT`로 변경 가능)
- 콘텐츠 형식: `application/json; charset=utf-8`
- 날짜: `YYYY-MM-DD`, 시간: UTC ISO 8601
- 페이지 번호는 사용자가 PDF 뷰어에서 보는 **1부터 시작하는 PDF 페이지 번호**다.
- 핵심 답변 항목은 `evidence`가 비어 있으면 API 응답에 포함하지 않는다. 근거 부족 시 항목 대신 `확인할 수 없습니다` 상태를 반환한다.
- 오류 응답은 FastAPI 표준 `{"detail": "메시지"}` 형식을 사용한다.

## 구현됨: 상태 확인

`GET /health`

응답 `200`:

```json
{"status": "ok"}
```

## 구현됨: 문서 등록

`POST /api/v1/documents` (`multipart/form-data`)

필드: `file`, `company_name`, `stock_code`, `document_type` (`broker_report` 또는 `dart_filing`), `issuer`, `published_at`.

필드는 `file`, `company_name`, `stock_code`, `document_type`, `issuer`, `published_at`이다. `document_type`은 `broker_report` 또는 `dart_filing`이다. 동기 적재 성공 `200` 예시:

```json
{"document_id":"uuid","status":"completed","page_count":12,"duplicate":false}
```

동일 SHA-256 파일은 다시 적재하지 않고 기존 ID와 `duplicate: true`를 반환한다. 확장자가 PDF가 아니면 `415`, 제한 초과는 `413`, PDF 서명 누락·손상 문서는 `400`, 메타데이터 검증 실패는 `422`다. 문서 상태는 `processing`, `completed`, `completed_with_errors`, `failed` 중 하나다.

## 구현됨: 문서 조회

- `GET /api/v1/documents`: 생성 시각 역순으로 `{ "items": [...] }`를 반환한다.
- `GET /api/v1/documents/{document_id}`: 메타데이터, 상태, 오류 사유와 페이지 수를 반환한다.
- `GET /api/v1/documents/{document_id}/file?page_number={page}`: 영속 볼륨의 해당 문서 원본 PDF만 `application/pdf`, `Content-Disposition: inline`으로 반환한다. `page_number`는 1 이상이며 문서 페이지 수 이하여야 한다. 브라우저 링크는 `#page={page}` fragment를 함께 사용한다. 저장 경로가 허용된 `data/raw` 밖을 가리키거나 PDF가 없거나 서명이 잘못되면 파일 내용을 노출하지 않고 `404`를 반환한다.
- `GET /api/v1/documents/{document_id}/pages/{page_number}`: `document_id`, 1부터 시작하는 `page_number`, `final_text`, `text_source`, 페이지 단위 `ocr_error`를 반환한다.

없는 문서·페이지는 `404`, 1보다 작은 페이지 번호는 `422`다. 저장 경로와 SHA-256은 내부 정보이므로 조회 응답에 노출하지 않는다.

### 문서 메타데이터 수정

`PATCH /api/v1/documents/{document_id}/metadata`

수정 가능 필드는 `company_name`, `stock_code`, `document_type`, `issuer`, `published_at`뿐이다. `stock_code`는 6자리 숫자 또는 `null`이며 나머지 필드는 null일 수 없다. 원본 파일, 파일 해시, 페이지, 청크, 임베딩과 적재 상태는 수정할 수 없다. 성공 시 수정된 문서 상세를 반환하고, 잘못된 날짜·종목코드·허용되지 않은 필드는 `422`, 없는 문서는 `404`다.

## 구현됨: 임베딩 생성과 상태

`POST /api/v1/documents/{document_id}/embeddings`

아직 현재 provider/model/dimensions 조합으로 처리되지 않은 청크를 Ollama `/api/embed`로 배치 임베딩한다. 기본 조합은 `ollama` / `bge-m3` / 1024이며 동일 조합의 기존 청크는 건너뛴다.

```json
{
  "document_id": "uuid",
  "embedding_status": "completed",
  "embedding_provider": "ollama",
  "embedding_model": "bge-m3",
  "embedding_dimensions": 1024,
  "processed_chunk_count": 10,
  "skipped_chunk_count": 2,
  "failed_chunk_count": 0
}
```

Ollama 서버에 연결할 수 없거나 `bge-m3` 모델이 없거나 차원이 맞지 않으면 `ollama pull bge-m3` 및 설정 확인 방법을 포함한 `503`을 반환한다. 애플리케이션은 모델을 자동 다운로드하지 않으며 OpenAI 또는 유료 외부 API를 호출하지 않는다. 문서가 없으면 `404`다. 처리 상태는 `not_started`, `processing`, `completed`, `failed`다.

`GET /api/v1/documents/{document_id}/embedding-status`는 상태, provider, 모델, 차원, 완료 시각, 실패 사유·실패 청크 ID와 전체/완료/실패 청크 수를 반환한다.

## 구현됨: 하이브리드 검색

`POST /api/v1/search`

요청:

```json
{
  "query": "삼성전자 HBM 악재",
  "top_k": 5,
  "ticker": "005930",
  "company_name": null,
  "document_type": "broker_report",
  "publisher": null,
  "published_from": "2026-01-01",
  "published_to": "2026-12-31"
}
```

`query`는 필수이며 `top_k` 기본값은 5, 범위는 1~20이다. 나머지는 모두 선택 필터다. 필터는 BM25·vector 후보 검색 전에 적용한다. Ollama를 사용할 수 없으면 vector 후보를 생략하고 BM25 결과 및 미사용 사유를 반환한다.

응답:

```json
{
  "query": "삼성전자 HBM 악재",
  "status": "evidence_found",
  "applied_filters": {"ticker": "005930"},
  "vector_search_used": true,
  "vector_search_unavailable_reason": null,
  "results": [{
    "rank": 1,
    "rrf_score": 0.0325,
    "bm25_rank": 1,
    "vector_rank": 2,
    "chunk_id": "uuid",
    "document_id": "uuid",
    "document_name": "원본.pdf",
    "company_name": "기업명",
    "ticker": "005930",
    "publisher": "발행기관",
    "published_at": "2026-08-23",
    "document_type": "broker_report",
    "page_number": 1,
    "section_title": null,
    "quote": "페이지 final_text에서 그대로 복원한 원문"
  }]
}
```

`bm25_rank`와 `vector_rank`는 해당 검색에 후보가 없으면 `null`이다. Ollama 장애 시 `vector_search_used`는 `false`이고 `vector_search_unavailable_reason`에 서버 실행 및 `ollama pull bge-m3` 안내를 표시한다. 결과가 없으면 `status: no_evidence`, `results: []`를 반환한다. 이 API는 생성형 답변이나 투자 판단을 반환하지 않는다.

## 구현됨: 근거 기반 문서 분석

`POST /api/v1/analyses`

요청:

```json
{
  "document_id": "uuid",
  "question": "이 보고서를 읽고 주식 초보자 관점에서 호재와 악재를 각각 최대 3개까지 요약해줘.",
  "top_k": 10
}
```

`question`은 선택이며 위 문장이 기본값이다. `top_k` 기본값은 10, 범위는 1~15다. 서버는 `document_id` 범위에서만 BM25와 vector 후보를 RRF로 결합한다. 선택된 Gemini 또는 Ollama 생성 provider에는 질문, 문서 메타데이터와 `chunk_id`, 페이지, 섹션, 원문 텍스트로 구성된 evidence packet만 전달한다.

분석용 retrieval은 사용자 질문과 호재·악재 보조 질의를 각각 같은 문서 범위에서 실행해 후보를 합친다. 투자등급·면책 등 일반 안내와 문맥 없는 숫자 표 조각을 제외하고, `quote`에는 DB 원문에 실제 존재하는 관련 evidence span을 반환한다. 같은 chunk의 서로 겹치지 않는 span은 양쪽 관점에 사용할 수 있다. 한국어 질문에서 한국어가 아닌 제목·설명은 노출하지 않는다.

응답 예시의 문자열은 형식 설명용이며 실제 분석 내용을 하드코딩하지 않는다.

```json
{
  "analysis_status": "completed",
  "generation_model": "gemini-3.7-flash",
  "generated_at": "ISO-8601 UTC",
  "summary": "검색 근거에 한정한 요약",
  "positives": [{
    "title": "항목 제목",
    "reason": "쉬운 이유",
    "evidence_chunk_ids": ["uuid"],
    "interpretation_label": "증권사 리포트 해석"
  }],
  "negatives": [],
  "citations": [{
    "chunk_id": "uuid",
    "filename": "원본.pdf",
    "company_name": "기업명",
    "published_at": "YYYY-MM-DD",
    "issuer": "발행기관",
    "document_type": "broker_report",
    "page_number": 1,
    "quote": "DB에서 그대로 복원한 원문",
    "display_kind": "text 또는 table",
    "citation_type": "text 또는 table",
    "display_quote": "화면 표시 전용 줄바꿈 정규화 발췌 또는 null",
    "table_labels": [],
    "display_note": null,
    "table_facts": {
      "table_title": null,
      "metric": "원문에서 확인한 지표",
      "row_label": "원문에서 확인한 행",
      "unit": "원문 단위",
      "values": [{"period": "원문 기간", "value": "원문 수치"}],
      "interpretation": "표시 수치만 출처 귀속 방식으로 설명하거나 null"
    }
  }],
  "positive_empty_state": null,
  "negative_empty_state": {
    "reason": "no_evidence",
    "message": "확인된 악재 근거가 없습니다.",
    "page_number": null
  },
  "insufficient_evidence_note": "근거가 부족해 추가 항목을 제시하지 않았습니다.",
  "disclaimer": "투자 권유나 매수·매도·보유 추천이 아니라는 안내"
}
```

빈 polarity의 `reason`은 관련 근거가 검색·검증되지 않은 `no_evidence` 또는 관련 후보가 OCR·표 구조 품질 검증을 통과하지 못한 `extraction_limited`다. 후자는 깨진 원문이나 내부 제외 사유를 노출하지 않고 확인 가능한 `page_number`와 원문 PDF 링크용 정보만 제공한다.

`quote`는 DB 원문 연속 문자열이며 변경하지 않는다. `display_quote`는 한글 단어 중간 줄바꿈과 의미 없는 단독 OCR 줄만 제거한 화면 표시용 값이다. 검증된 `table_facts`가 있으면 `citation_type: table`, 표로 판단되지만 구조가 불완전하면 `table_fallback`, 일반 완결 문장이면 `text`다. 같은 DB 페이지에서 지표·행·단위·기간 헤더·수치 위치를 모두 대조하고 해당 수치가 citation quote에도 존재할 때만 `table_facts`를 반환한다. 표 제목은 OCR 결과에서 정확히 확인될 때만 포함하며 추정해 보정하지 않는다. 구조가 모호하면 `table_facts`는 `null`이고 `display_note`로 원문 PDF 페이지 확인을 안내한다.

일반 문장 quote는 완결 문장 1~2개만 선택하며 글자 수를 맞추기 위해 단어나 문장을 중간 절단하지 않는다. 이메일·Analyst 연락처·면책 문구는 표시 발췌에서 제거하고, 핵심 사실을 훼손하는 OCR 토큰이 있으면 후보와 최종 카드를 제외한다. 제목은 구체적인 사업·실적·제품·수요·가격·생산·수익성 주제와 원문 사실을 함께 포함해야 하며 주가 예측·단기 매력·저평가 및 일반적인 `위험 요인` 제목은 허용하지 않는다.

분석 citation은 문장·문단 또는 검증된 표 행 evidence span을 가리킨다. `source_chunk_id`, `char_start`, `char_end`는 원본 chunk와 `pages.final_text`의 문자 범위를 보존한다. 같은 원본 chunk에서도 서로 겹치지 않는 span은 각각의 호재·악재 근거가 될 수 있지만, 동일하거나 80% 이상 겹치는 span은 중복 노출하지 않는다.

모델 출력은 provider의 JSON Schema와 서버의 Pydantic Schema로 이중 검증한다. 앞뒤 공백과 JSON 코드블록은 제거한 뒤 역직렬화하지만 임의 분석 결과를 만들지 않는다. 검색 후보에 없는 chunk ID가 하나라도 있거나 JSON 파싱에 실패하면 결과를 노출하지 않고 `502`를 반환하며 실패 사유를 기록한다. citation 없는 호재·악재는 제거한다. Gemini HTTP 429·503·504, timeout과 네트워크 오류만 최대 `GEMINI_MAX_ATTEMPTS`회 지수 백오프로 재시도한다. 재시도 소진 뒤 fallback 설정이 `ollama`일 때만 Ollama를 한 번 호출한다. 키 누락, HTTP 401·403·404, 안전 차단, JSON/Schema/citation 오류에는 재시도하거나 fallback하지 않는다. 요청·응답 필드는 provider 변경과 무관하게 유지되며, 최종 provider/model과 fallback 여부는 내부 분석 기록에만 저장된다.

## 2026-09-22 근거 신뢰도 보강

공개 API/DB 필드는 변경하지 않는다. 분석 인용은 문서·페이지·청크 FK, 물리적 페이지 번호, 원문 오프셋·문자열과 source_chunk_ids의 연속 범위까지 검증한다. 비공백 문자가 청크로 덮이지 않거나 원문이 바뀐 후보는 채택하지 않으며, 생성 후 검증 실패는 502로 처리하고 run을 failed로 남긴다. 근거 없는 전체 분석의 summary는 정확히 `확인할 수 없습니다`다. 요청에 명시된 연도(YYYY, 2Q26, FY26 등)를 후보 원문에서 확인할 수 없으면 생성 전에 보류한다. 이는 다른 연도 사실을 가져오는 것을 막는 필요조건이며 주제·기간의 의미 검증 전체를 대체하지 않는다.

OCR 기본 해상도는 OCR_DPI=300이다. 기존 저장 페이지와 임베딩을 자동 재작성하지 않는다. 검색 공개 필터의 published_from/to는 문서 발행일이며 실적 대상 연도 필터가 아니다.

현재 google-genai 2.18.1 Interactions의 내부 재시도는 별도로 최대 1회다. 위 GEMINI_MAX_ATTEMPTS는 서비스 루프 횟수이며 전체 HTTP 호출 횟수나 엄격한 총 응답 시간 한도를 의미하지 않는다.

### Retrieval 표 근거 진단 확장 (2026-09-22)

`POST /api/v1/search`의 기존 필드와 필터를 유지한다. 결과에 `rrf_rank`(승격 전 순위, 후보 밖은 null), `retrieval_reason`(`hybrid_rrf`/`verified_table_conditions`), `table_evidence`(기본 빈 배열)를 추가한다. `rank`는 최종 순위이며 `rrf_score`는 기존 RRF 점수라 최종 순서와 단조 증가/감소 관계를 보장하지 않는다.

각 table_evidence는 문서·페이지·source_chunk_ids, row_label, metric, column_name, period, status(forecast/actual/provisional/unspecified), comparison_basis(모르면 null), unit, 원문 value, 행 quote/char_start/char_end, 헤더·단위·지표·행의 source_spans, processing_version을 담는다. 물리적 PDF 페이지 번호 및 final_text의 문자 offset이다. 표 구조 연결을 검증한 것이며 OCR 숫자가 원본 PDF와 같다는 보증이나 답변 발행 승인이 아니다. 일반 문장은 table_evidence가 아니다. 기존 분석 citation/카드 API는 바꾸지 않는다.

다단 헤더가 검증된 새 table_evidence는 `column_name`(하단 헤더)과 `period`(상단 헤더)를 별도 span으로 보존할 수 있다. 비교 질문의 검증된 사실에는 선택적 `comparison_cell`(`label`, `period`, `unit`, `value`, `bbox`, `source_spans`)이 붙는다. 행·열·기간·단위·비교 셀 중 하나라도 원문 좌표로 검증되지 않으면 후보를 승격하지 않는다. 기존 응답 필드는 유지한다.

300dpi 재처리 CLI는 DB 외부 비활성 revision manifest만 만든다. 페이지·청크·표 셀·미생성 embedding 슬롯에 버전을 붙이며 raw PDF SHA-256을 보존한다. 활성화 API와 DB revision 마이그레이션은 아직 없고, 기존 활성 DB 행을 갱신하지 않는다.

### 신규 PDF 혼합 추출 (2026-09-23)

업로드/중복/임베딩 API 요청은 유지한다. 신규 업로드만 `mixed-layout-v1`로 처리하며 중복 hash의 기존 문서는 재처리하지 않는다. `GET .../pages/{page_number}`에 nullable `extraction`을 추가한다(parser_version, selection_mode, ocr_reasons, ocr_dpi, metrics). 기존 `text_source` enum은 유지하며 mixed 페이지는 native로 호환 표시하고 정확한 선택은 extraction.selection_mode에서 확인한다.

Additive migration `20260922_0005`는 `page_extractions` 테이블만 생성한다. page_id FK/PK, parser_version, final_text_sha256, provenance JSON, table_facts JSON을 저장한다. 기존 pages/chunks/documents/analysis_runs UPDATE·backfill은 없다. 행이 없는 기존 페이지는 기존 검색/인용 경로를 유지한다.

provenance는 native block/word 좌표, OCR word 좌표·confidence·일치 재확인 기록, 선택 단어의 final_text offset, unsafe_spans, OCR 이유·품질 지표·DPI를 보존한다. 좌표는 회전 전 PDF points이며 물리 페이지 순번을 사용한다. 새 table_facts는 행/지표/열/기간/단위/값 각각의 source_spans와 source(native/ocr/mixed), source_chunk_ids를 포함한다. 기간 없는 표는 period=null, period_status=not_stated이며 기간을 만들어 붙이지 않는다. 기간 없는 셀은 기간 일치를 요구하는 검색 승격 대상이 아니다.

provenance.numeric_evidence는 일반 본문의 수치·지표·기간·단위·비교기준 span이다. 표 fact/UI로 분류하지 않는다. 좌표 표 후보는 분석의 neutral 후보로 전달할 수 있지만 기존 positive/negative 발행 검증은 그대로 적용한다. 중립 수치를 투자 판단 카드로 발행하지 않는다. 완전한 자유형 수치 답변 API를 새로 구현한 것은 아니다.


### Shadow retrieval 평가 전용 revision

`shadow_revisions / shadow_pages / shadow_chunks`는 기존 document/file hash와 parser version으로 연결된 별도 저장소다. 동일 원본·버전은 unique이며 pages에는 native/OCR/provenance/table facts, chunks에는 원문 offset과 bge-m3 1024 벡터를 보존한다. 공개 API·UI·활성 검색은 이 테이블을 조회하지 않는다. 활성화 API/포인터가 없으며 원본·활성 데이터 수정 없이 CLI로만 생성·검색한다. 동일 검색 함수의 BM25+exact cosine+RRF(k60, 후보20)+검증 표 승격을 revision 내부 행에만 적용한다. 완료되지 않은 임베딩 revision 검색은 거절하며 이미 생성된 벡터는 재생성하지 않는다.


### 신규 적재 fact-fusion-v4

새 file hash와 새 shadow parser version에만 적용한다. native 좌표 문단, PyMuPDF native table cell, 누락 영역 OCR(300dpi PSM6 / 200dpi PSM3 ROI, native 영역을 가린 200dpi PSM6 페이지 문맥)의 후보를 독립 생성한다. OCR 값·기간을 교정하지 않으며 300dpi cropped PSM7의 동일 문자열 확인만 허용한다(페이지당 숫자/기간 16개, 문자 16개). 원본 좌표, 각 word의 DPI/PSM/confidence, 후보 source와 parser version을 provenance에 보관한다. source는 native_text/native_table/ocr_text/ocr_table이다.

`final_text`는 원문 단어의 좌표 읽기 순서를 직렬화한 offset 저장소다. 검증된 paragraph/fact_quote만 검색 대표 청크가 된다. fact_span 청크는 헤더·행·기간·단위·값의 근거 연결에 남지만 독립 BM25/vector 검색 후보가 되지 않는다. 검색/임베딩용 표현은 검증된 사실 필드와 공백 정규화를 사용하며 citation quote/content는 그대로 보존한다. 공개 검색 응답에 additive `numeric_evidence`를 추가하고 기존 table_evidence/페이지/PDF 계약을 유지한다.

동일 위치의 서로 다른 OCR 값/기간/단위는 보류한다. 정상 native 사실은 낮은 우선순위 OCR 충돌로 제거하지 않는다. native 표는 cell 행/열 관계로 별도 사실을 생성하며 좌표 기반 native text 표 후보와도 대조한다. 일반 문장에는 표 UI를 붙이지 않는다. 기존 mixed-layout-v1 페이지/활성 검색/벡터는 새 parser 규칙을 적용하지 않는다. JSON 메타데이터 확장으로 새 DB migration은 없다. 기존 shadow revision도 삭제하거나 활성화하지 않는다.

### 복합 질문 evidence pack

`POST /api/v1/search`는 기존 `results` 순서와 필드를 유지한다. 복합 서술·표/수치 요청과 기간이 명시된 표/금액 질문에는 선택적 `requirements`, `evidence_pack`, `coverage_complete`를 반환한다. 그 밖의 단일 사실 질문의 세 필드는 null이다. Requirement에는 clause, kind, metric(surface/normalized/modifier), period, unit/unit_family, numeric_value_required, comparison_required/target 및 coverage(matched/evidence_id/reason/checks)가 포함된다. Pack은 같은 문서의 기존 hybrid 후보 20개와 검증된 table/numeric 후보에서 최대 5개를 선택하며, 각 항목은 requirement ID, 원래 RRF/BM25/vector 순위, 물리 페이지, 원문 quote와 좌표 source spans 및 requirement_checks를 포함한다. 모든 필수 check가 동일한 fact와 검증 span에서 충족돼야 complete다. 영업이익/영업이익률, 실제/잠정/전망 기간, 금액/비율 단위는 대체할 수 없다. `diagnostics` 평가 경로는 후보의 불일치 이유도 기록한다. 분석 생성 경로는 incomplete 또는 pack 항목 누락 시 근거 부족으로 보류한다. Shadow revision은 공개 문서 목록이나 active 검색 corpus에 들어가지 않는다.

### 구조화 primitive cell과 비교 관계 (parser `fact-fusion-paddle-v3`)

신규 추출의 table fact는 선택적 `table_id`, `row_id`, `column_id`, `cell_fact_id`, `cell_geometry`를 가진다. `provenance.primitive_cells`에 원시 셀 관계를, `unresolved_cell_observations`에 단위가 미확정인 좌표 셀을 남긴다. 미확정 셀은 검색 후보가 아니다. 비교는 같은 표·행·지표·단위의 검증 셀에서만 조립하며 `comparison_derivation.primitive_cells`와 기존 `comparison_cell`에 양쪽 원문 위치를 보존한다. 여러 기간에서 상대 셀을 하나로 확정할 수 없으면 자동 선택하지 않는다.

단위는 셀 → 같은 행 → 같은 열 → 명시 표 헤더 순이다. 금액/비율/주당/수량 호환성을 확인하며 혼합 선언의 배열 순서로 단위를 배정하지 않는다. 세로 기간 grid의 값에 붙은 `%`는 해당 셀의 unit source span이다. 축약 연도는 동일 지표와 동일 값이 적힌 인접 원문에 전체 연도가 있을 때만 별도 확인 span으로 연결한다. 그렇지 않으면 보류한다. 행 제목의 주체와 지표가 각각 원문 좌표로 확인되면 선택적 `row_subject`와 `row_subject` source span을 보존하며, matcher는 정확한 주체 일치와 원문 재검증을 모두 요구한다.

병합 HTML 셀은 명시 rowspan/colspan 및 실제 cell bbox 개수·순서·열 geometry가 일치할 때만 확장한다. 원본 단어·인용은 바꾸지 않는다. 기존 response 필드는 유지하며 DB migration·기존 페이지 재적재·active 전환은 없다. 옛 manifest는 원래 parser version에 그대로 바인딩된다. 동결 OCR 관찰의 새 추출 평가는 임시 인덱스이고 새로운 pinned OCR run으로 부르지 않는다.

명시한 두 기간의 비교 질의에서는 `requested_periods`와 기간별 독립 requirement를 반환한다. 기존 parser fact를 재작성하지 않고 검증된 structured primitive에서 query-time `primitive_graph_comparison`을 조립한다. `graph_comparison`은 양쪽 cell ID, 원문 기간의 year/quarter/status/qualifier/fiscal/raw, same_table/same_metric/same_row/same_unit/compatible_unit/adjacent_period 관계를 담는다. `comparison_cell` 및 양쪽 source spans 계약은 유지한다. 한 pack이 같은 검증 셀 쌍을 공유하면 두 requirement ID·각각의 checks·양쪽 table evidence를 함께 보존한다. Fiscal/분기/실적/전망/잠정 표기는 서로 대체하지 않고 단위 환산은 하지 않는다.

### Compound unit precision gate (2026-10-06)

새 structured/numeric fact는 `unit_surface`(원문 전체 단위), `canonical_unit`(공백만 제거), `value_span`, `unit_span`(원문 offset·관측 word bbox/boxes), `unit_source`(`same_cell`, `same_row`, `column_header`), `unit_association`을 보존한다. bbox는 원문 word box이며 글자별 box를 추정하지 않는다. 기존 저장 fact는 source_spans에서 동일 정보를 재검증해 audit에 기록하며 저장 JSON·manifest를 재작성하지 않는다.

셀 topology로 새로 만든 structured fact에는 `row_group_id`, `row_group_reason`, `metric_span`, `period_span`, `column_association_reason`도 보존한다. 행은 세로 overlap 0.8 이상·baseline 거리 최소 셀 높이의 0.2 이하를 모든 구성 셀 쌍에 요구하며 보고된 행 topology와 일치해야 한다. 열은 헤더/값 셀 x overlap 0.9 이상·양쪽 경계 차이 최소 폭의 0.1 이하를 요구한다. 병합 행의 문맥 소속, 겹치는 셀, 다단 헤더의 parent/child containment가 불명확하면 승인하지 않는다. 선택적 extraction audit에는 `coverage_complete=false`, rejection reason과 원문 span/bbox를 남긴다. 기존 저장 JSON·DB·manifest는 변경하지 않는다.

Paddle 셀 경계가 일부 겹쳐도 보고된 column 순서와 양쪽 x 경계 순서가 일치하고 지표·값·기간의 원문 bbox가 overlap 0.8 초과 조건으로 정확히 한 셀에만 속할 때는 검증할 수 있다. 원문 span이 겹친 영역에서 두 셀에 속하면 보류한다. period 원문 bbox는 value 원문 bbox보다 위에 있어야 한다. 셀 경계 jitter 때문에 모든 헤더를 하나의 행 그룹으로 강제하지 않으며 개별 period/value의 column geometry는 반드시 검증한다.

병합 문맥은 `metric_context_ownership.context_membership`과 개별 `ownership_id`로 분리하여 재검증한다. `context_membership`은 literal context span, source/cell uniqueness, vertical containment, horizontal continuity 및 서로 겹치지 않는 metric row를 증명하고 `context_id`, `members[{metric_span,row_bbox,metric_ownership_id}]`, `status`, `checks`를 보존한다. 여러 row가 검증되면 `shared_metric_context_verified`이며 각 row는 같은 context_id와 서로 다른 ownership_id를 가진다. membership 승인만으로 coverage_complete는 승인되지 않는다.

각 row의 unit/value는 동일 literal baseline에 유일하게 귀속되어야 하고 period는 공유 가능한 column header로 value column과 독립 검증한다. period 후보·row/column 교차점 value가 복수이거나 source/cell 소속이 중복이면 HOLD한다. `shared_context_metric_row_ambiguous`, `shared_context_metric_topology_conflict`, `shared_context_value_ownership_conflict`, 기존 period/chain 거절 사유를 구분한다. topology가 없으면 관측 span bbox에 동일 임계값을 적용하는 membership/ownership proof만 제공하며 cell이나 단위를 만들지 않는다. 기존 unit validator는 그대로 별도 적용한다.

shared proof는 primitive 재검증에서 필수이며 누락·변조를 허용하지 않는다. graph 비교는 같은 context와 같은 metric ownership 사이에서만 연결한다. query matcher는 downstream이 탈락한 sibling도 포함해 membership의 모든 literal metric 후보에서 target row가 유일한지 검사한다. 비교 primitive 양쪽과 comparison cell은 같은 metric ownership이어야 하며, evidence pack은 해당 row의 chain만 requirement를 만족시킨다. 같은 context에 query 조건을 만족하는 복수 ownership이 있으면 `shared_context_query_metric_ambiguous`로 HOLD한다. 검색·OCR·embedding·LLM 및 DB schema 변경은 없다.

더 긴 compound unit의 strict suffix이고 span/bbox가 겹치거나 같은 관측 행이면 `unit_suffix_conflict`로 거부한다. 셀/행 단위와 검증된 table·column topology의 헤더 선언만 연결한다. 병합 unit/value cell과 불명확한 header geometry는 보류한다. 승인 전 숫자 환산은 없고 인용은 원문을 유지한다. 단위 위치·연결이 검증되지 않은 fact는 검색 승격·pack 충족에 사용할 수 없으며 필수 근거가 없으면 `coverage_complete=false`, `확인할 수 없습니다`다. 평가 audit에 승인·거부 사유와 충돌 full surface/span/bbox를 기록한다.

### Query-time metric annotation identity

관측 primitive의 `metric`/`row_label`/`metric_span`/geometry/ownership은 원문 그대로 유지한다. query 후보에만 선택적 `metric_identity`를 붙인다. `raw_label`, `raw_span`, `canonical_label`, `annotation`, `marker_span`, `annotation_type`, `proof_level`, `definition_spans`, `proof_checks`, `scope_metrics`, `collision_spans`, `rejection_reason`을 보존한다. 별도 superscript는 원문 metric span을 덮어쓰지 않고 독립 marker span으로 보존한다. DB schema/migration 변경은 없다.

marker syntax는 후보 탐지용이다. `verified_annotation`은 source offset/quote/bbox와 unsafe span 검증, 유일한 metric cell, 같은 source/table의 유일한 인접 footer definition에 더해 명시적 주석 anchor 또는 raised definition marker 및 반복 convention/별도 superscript 증거를 요구한다. 단순 숫자 목록·다른 reference·remote/중복/불안전 definition·superscript만 있는 경우는 `probable_annotation`/`unverified_suffix`이며 제거를 승인하지 않는다. unsupported 표기/구조는 HOLD한다.

verified source prefix만 canonical label로 사용한다. query literal metric과 canonical label은 공백/case 이외에는 exact match해야 하고 modifier도 일치해야 한다. fuzzy/substring 또는 alias만으로 annotated equivalence를 승인하지 않는다. 동일 표의 period header 앞 모든 label column에서 전체 raw row 후보를 검사하며, chain이 탈락한 row 및 아직 미검증된 suffix의 potential base도 competing candidate로 남긴다. canonical collision은 `canonical_metric_collision`으로 HOLD하고 bare competing row에도 적용한다. context별로 임의 분할하여 collision을 숨기지 않는다.

기존 primitive/graph chain 검증은 별도로 유지한다. annotation proof를 page에서 재생성하여 metadata 삭제/변조를 거절하며 정의·marker 원문 span은 pack의 source_spans 및 chunk coverage에 포함한다. raw graph 연결 기준과 row/column/shared ownership/unit/period/value association, search/RRF/OCR/embedding/LLM은 변경하지 않는다.

### Explicit reporting scope (2026-10-08)

Structured query requirements preserve `scope: consolidated | separate | null`,
`scope_proof: [{char_start, char_end, quote, scope}]` relative to `clause`, and
`scope_ambiguous: boolean`, separately from metric/entity/period. Supported bounded
literals are 연결/consolidated and 별도/개별/separate/standalone, optionally with 기준,
including before dates or adjacent to a metric. Multiple distinct scopes in one
clause HOLD; multi-scope query parsing is not supported.

Query-time `metric_identity.source_scope` and each `scope_metrics[].source_scope`
carry the normalized scope and rederived original context membership (literal
spans, context ID, independent metric ownership IDs). No DB schema/migration or
stored observation change. Global `collision_spans` remain in audit. Only an
explicit query proof plus source membership and scope-local unique canonical row
may authorize a collision; unknown competing membership HOLDs. Publication
rederives the identity, membership, annotation, cell and comparison chain from the
page. Opposite-scope facts cannot satisfy the same requirement. Scope failures
include `query_scope_proof_invalid`, `query_scope_ambiguous`,
`source_scope_unverified`, `source_scope_membership_invalid`,
`metric_scope_mismatch`, and `metric_scope_ambiguous`.

### Verified dependency index admission v1

New fused extractions record `index_admission_contract=verified-dependencies-v1`,
`dependency_groups` and additive `verified_dependency` index segments. Each group
contains a revalidated primitive ID, table/row, scope, ownership/context IDs,
exact dependency source spans, metric anchor, raw/canonical metric, annotation
proof and a separate `search_text`. Page text, quotes and source offsets remain
unchanged. Only metric anchor chunks become searchable through this contract;
proof-only chunks remain addressable without becoming independent search hits.
Comparisons use unions of primitive groups on existing validated graph edges.
This is additive extraction provenance; no endpoint, migration or live revision
change. Existing frozen revisions retain their original admission and ranking.

Verified dependency admission also records `unit_dependency` under each group
(`semantic-unit-components-v1`). An atomic unit has one component; a composite
unit retains every original token slice, ordered offsets, source bbox/page/cell,
metric ownership binding and semantic unit proof ID. Raw unit text and canonical
representation remain separate. Only source-revalidated primitive units qualify;
missing, overlapping or conflicting components reject admission. Explicitly
verified header declarations may share a unit proof across independently owned
metric groups. Existing API response and source text representations are preserved.

### Source-owned period binding v1

새 extraction의 parser version은 `fact-fusion-paddle-v4`다. Structured cell 및
numeric evidence의 additive `period_binding` JSON은 `source-owned-period-v1`
계약, 원문 SHA-256, 물리 page, literal span과 ownership proof를 포함한다.
표 proof는 table identity/bbox, metric row, value column, parent column group,
parent/child/value cell bbox를 보존한다. 문장 proof는 같은 source의 명시적
sentence 범위와 metric/period/value/unit/status span을 보존한다.
새 버전에서 proof가 없거나 원문 재구성 결과와 다르면 admission을 거절한다.
`approved`는 period binding 판정이며 coverage 또는 factual correctness 판정이 아니다.
기존 immutable extraction의 parser version과 저장 내용은 유지한다. Legacy numeric
evidence는 기존 검증 경로를 사용하며 새 period proof를 검증했다고 주장하지 않는다.
Legacy table fact도 강화된 원문 재구성을 통과해야 하며 additive proof 필드만 생략 가능하다.
Document namespace는 page/primitive graph/evidence pack의 기존 document identity
검증에서 제공하며, foreign document ID가 붙은 stored fact는 거절한다.
API endpoint, DB schema, 검색 parameter와 기존 unit/scope contract는 바뀌지 않는다.

### Source-owned unit binding v1 (Stage 2)

새 `fact-fusion-paddle-v5` structured cell fact의 `unit_binding`은
`source-owned-unit-v1` proof다. 원문 SHA-256, page/table/row/column identity,
metric/value/unit span, metric/value/header/unit cell membership, 적용 scope,
metric context, 기존 period binding 및 `semantic-unit-components-v1` dependency를 포함한다.
Source stream 안에서 적용 가능한 unit 선언이 정확히 하나이고 기존 unit validator와
metric/period/geometry/context 검증이 모두 통과해야 생성한다. cell/row/column/table 순위로
후보를 선택하거나 상위 선언을 무시하지 않는다. 복수 선언은 같은 단위여도 HOLD다.
Composite component는 `verified-dependencies-v1`의 원문 dependency slices로 전달한다.
새 observation의 proof 삭제·변조는 admission/pack을 통과하지 못한다.
기존 v4 period proof 필수 검사는 유지한다. Legacy observation은 버전 변경 없이
기존 validator와 source rederivation을 통과해야 하며 새 계약으로 재인증하지 않는다.
`million USD`는 literal surface와 source component를 보존하고 `millionUSD`로 공백만 정규화한다.
USD와 원, millionUSD와 USD, %와 %pt를 동등 단위로 변환하지 않는다.

새 parser의 observed-table topology fallback도 기존 header geometry 범위에서
unit owner 유일성을 검사하며 structured 경로의 ambiguity HOLD를 우회하지 못한다. 기존 버전의 archived topology fact는 기존 원문 검증을 유지한다.

### Source-owned scope binding v1 (Stage 3)

새 `fact-fusion-paddle-v6` cell fact는 `source-owned-scope-v1`의 `scope_binding`을
필수로 보존한다. 원문 hash/page/table/row/column, metric/value source span과 cell,
literal scope 선언, context membership/ownership ID, period/unit proof를 포함한다.
Page annotation에서 document/page namespace를 붙이며 foreign namespace를 거절한다.
Row literal, 독립 scope column, full-width section interval, 기존 검증된 merged
context, adjacent-column rowspan containment로 증명된 parent/child만 승인한다.
Section 종료 선언과 검증된 이전 context 종료 proof도 dependency로 보존한다.
Query는 report scope(연결/별도)와 region scope(국내/해외)를 독립 차원으로 비교한다.
동일 차원의 복수 query, source mismatch, 미명시 query의 복수 scope, 같은 scope의
복수 metric row, 미검증 competing row와 cross-scope comparison은 HOLD다.
`approved`는 독립 scope association이며 다른 requirement/coverage를 승인하지 않는다.
새 native topology fallback의 scoped table은 검증된 scope proof를 우회할 수 없다.
Legacy observation은 원래 parser version과 기존 모든 source validator를 유지한다.
v4 period/v5 unit 필수 proof와 composite dependency 계약은 계속 적용된다.
API endpoint, DB schema, retrieval parameter와 immutable revision은 변경하지 않는다.

### Service quality E2E (2026-10-12)

- `AnalysisResult`에 `run_id`, `requirement_status`, `coverage_complete`를 추가한다.
  Parser 상태는 `supported_requirement`, `unsupported_requirement`,
  `ambiguous_requirement`, `no_factual_requirement_applicable`,
  `requirement_generation_error`다. Supported는 parser 지원 여부이며 fact 검증 성공이 아니다.
  Unsupported/ambiguous/error는 LLM 전에 `insufficient_evidence`로 종료한다.
- 빈 requirement는 coverage 성공으로 처리하지 않는다. 비구조화 요약도 기존
  원문 sentence/polarity/수치/citation 검증을 통과해야 한다.
- Citation에 optional `source_boxes`, `page_size`, `coordinate_system`을 추가한다.
  좌표계는 `unrotated_pdf_points`; literal 원문 span/box와 source hash를 검증한다.
  좌표 부재/불일치 시 box를 추정하지 않는다.
- `GET /api/v1/documents/{id}/pages/{page_number}/image`는 원본 PDF를
  unrotated PNG로 제공한다. 경로·페이지를 검증하고 private/no-store로 반환한다.
- SDK 누락 등 dependency 생성 단계의 configuration 오류는 안전한 503 응답이다.
  Retrieval 예외는 새 run 하나를 failed로 기록하고 LLM을 호출하지 않는다.
  Retrieval 503 detail은 `code=retrieval_failure`와 안전한 message, model 연결/timeout은
  504다. `GET /api/v1/documents/{id}/analyses/latest`는 기존 완료/HOLD 결과만 반환하며
  internal trace를 제외한다. OCR/embedding/generation과 새 run을 만들지 않는다.
- 검증 cache는 요청 내에서만 유지하며 문서/page namespace, parser revision,
  final text/source hash, 전체 provenance/facts의 SHA-256을 포함한다.
  Unit audit는 cache를 우회한다. Threshold/RRF/cutoff/DB schema는 유지한다.
  기존 검색 preview/frozen replay의 compound requirement 계약은 유지한다.
  사용자 analysis의 첫 검색은 `strict_requirements=True`로 확장된 parser 결과를
  사용하며 필수 requirement나 coverage가 유실되면 HOLD한다.
  Citation 페이지 링크는 `/source/{documentId}?page=N`의 원본 페이지 이미지
  뷰어로 이동한다. 브라우저 내장 PDF hash 이동과 구분해 physical page를 명시한다.
# Generation runtime diagnostics (2026-10-13)

Gemini uses stateless `models.generate_content` with the existing JSON schema. SDK retry attempts are 1 (including the original request); `GEMINI_MAX_ATTEMPTS` bounds the application's retry loop. HTTP 429/500/502/503/504 and network/timeout failures may retry and then use the configured local fallback. Authentication, model configuration, safety, JSON/schema errors remain fail-closed. No unvalidated streamed text is published.

Internal run trace records request/run ID, purpose, provider/model, timestamps, attempt latency/status, token usage and Ollama native timing. Prompt/source/API keys and generated text are excluded from runtime logs. Public execution metadata follows the provider consent contract below.

Opt-in `STOCK_BRIEF_LOW_MEMORY=1` serializes local embedding/generation within one process, sends embedding keep_alive=0, generation keep_alive=60s, num_ctx=4096 (server default prefill batch), and limits application PostgreSQL connections to pool_size=2/max_overflow=0. Use a single API worker; other Ollama clients and workers are outside this lock. DB schema, UUIDs, provenance and stored vectors are unchanged.

## Request-scoped provider contract (2026-10-13)

- AnalysisRequest adds execution_mode: LOCAL_ONLY(default), EXTERNAL_WITH_CONSENT, FALLBACK_ALLOWED; external_consent is strict JSON boolean, default false. External without true consent, or local with true consent, returns422.
- External additionally requires server ANALYSIS_EXTERNAL_ENABLED=1; fallback requires ANALYSIS_OLLAMA_FALLBACK_ENABLED=1. Both default0. Policy/provider mismatch returns403/detail.code=provider_policy before retrieval/run creation. Keys and legacy provider settings never supply consent.
- GET /api/v1/analysis-options returns policy availability/model IDs without keys or provider network calls; it does not grant consent.
- POST /api/v1/analyses retains JSON behavior. POST /api/v1/analyses/stream accepts the same body and emits application/x-ndjson: status with stage(retrieving/generating/fallback/validating) and provider/null, then one validated result or safe error. No partial model text/source/prompt is streamed as status. Prerequisite/policy errors use HTTP4xx/5xx before headers; later failures emit type:error/status/detail. Disconnect does not cancel an already running provider call; no silent resubmission.
- AnalysisResult.execution is optional/null for historical results. New results store requested_mode, external_consent, external_request_attempted, final_provider/null, fallback_used in existing analysis_runs.result JSON. Early HOLD means no provider call/final_provider null. Attempted transmission does not prove server receipt. No migration.
- Consent covers this body document/question/verified packet and configured transient retries. UI clears consent on document/question/mode/metadata changes and consumes it on submission. A new external POST needs consent again. It is a request declaration, not authenticated legal consent proof or a reusable token.
- External payload: question, company/stock code/type/issuer/date, selected locally verified evidence quote/page/UUID/section/factual values(period/unit/scope/status), analysis/system instructions/schema. PDF/images/embedding/full provenance/geometry graphs/full document uploads remain local. Selected excerpts can contain sensitive text; consent does not anonymize them.
- All providers share requirement/HOLD gates, schema/card limits, source ownership, literal quote/period/unit/scope checks and deduplication. Citation/schema/safety failures never cause fallback or relaxed validation.
