# API contract

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

분석용 retrieval은 사용자 질문과 호재·악재 보조 질의를 각각 같은 문서 범위에서 실행해 후보를 합친다. 투자등급·면책 등 일반 안내와 문맥 없는 숫자 표 조각을 제외하고, `quote`에는 DB 원문에 실제 존재하는 최대 320자의 관련 발췌를 반환한다. 같은 chunk ID는 최종 분석 항목 하나에만 사용할 수 있다. 한국어 질문에서 한국어가 아닌 제목·설명은 노출하지 않는다.

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
    "quote": "DB에서 그대로 복원한 원문"
  }],
  "insufficient_evidence_note": "근거가 부족해 추가 항목을 제시하지 않았습니다.",
  "disclaimer": "투자 권유나 매수·매도·보유 추천이 아니라는 안내"
}
```

모델 출력은 provider의 JSON Schema와 서버의 Pydantic Schema로 이중 검증한다. 앞뒤 공백과 JSON 코드블록은 제거한 뒤 역직렬화하지만 임의 분석 결과를 만들지 않는다. 검색 후보에 없는 chunk ID가 하나라도 있거나 JSON 파싱에 실패하면 결과를 노출하지 않고 `502`를 반환하며 실패 사유를 기록한다. citation 없는 호재·악재는 제거한다. Gemini HTTP 429·503·504, timeout과 네트워크 오류만 최대 `GEMINI_MAX_ATTEMPTS`회 지수 백오프로 재시도한다. 재시도 소진 뒤 fallback 설정이 `ollama`일 때만 Ollama를 한 번 호출한다. 키 누락, HTTP 401·403·404, 안전 차단, JSON/Schema/citation 오류에는 재시도하거나 fallback하지 않는다. 요청·응답 필드는 provider 변경과 무관하게 유지되며, 최종 provider/model과 fallback 여부는 내부 분석 기록에만 저장된다.
