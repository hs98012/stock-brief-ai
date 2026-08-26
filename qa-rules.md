# QA rules

## 인용 및 사실성

1. 핵심 요약, 호재, 악재, 이유, 수치 주장마다 evidence 연결을 검사한다.
2. evidence의 파일명·발행일·페이지·인용문이 원본 PDF와 정확히 일치해야 한다.
3. 인용문만으로 주장을 뒷받침하지 못하면 실패 처리한다. 여러 문장이 필요하면 evidence를 추가한다.
4. PDF 페이지 번호는 1부터 시작하는 실제 PDF 페이지 기준으로 수동 표본 검증한다.
5. 검색 결과가 없거나 상충하고 해소할 수 없으면 `확인할 수 없습니다`가 출력되는지 확인한다.
6. 검색 결과에 없는 내용은 이후 답변 단계에서 만들거나 보완하지 않는다. 빈 검색 결과는 그대로 `no_evidence`로 전달한다.
7. 분석 요청은 선택한 `document_id`로 검색 범위를 고정하고 모델에 질문·문서 메타데이터·evidence packet 외의 자료를 전달하지 않는다.
8. 모델의 모든 `evidence_chunk_ids`를 검색 허용 목록과 대조한다. 하나라도 허용되지 않으면 전체 결과를 실패 처리한다.
9. 인용문은 모델 출력이 아니라 DB의 `final_text[char_start:char_end]`에서 복원한 quote만 사용한다.
10. citation 없는 호재·악재는 제거하며 항목 수가 3개 미만이면 부족 안내를 표시한다.

## 금융 표현

- 실제 실적, 회사 가이던스, 증권사 추정치, 목표주가를 서로 다른 유형으로 표시한다.
- 목표주가에는 증권사명과 전망임을 반드시 붙인다.
- 핵심 요약은 확인된 사실과 초보자 관점의 의미만 중립적으로 설명한다. 리포트의 전망·판단은 `보고서는 … 언급합니다/제시합니다`처럼 출처를 문장 안에 귀속한다.
- 핵심 요약에 서비스 자신의 판단처럼 `매력적`, 매수·매도, 투자 기회, 목표주가, 주가 상승·하락 예상, 주가 충격 제한, 확정적 수익·성과 전망을 노출하지 않는다. 검증에 실패한 요약은 `확인할 수 없습니다`로 대체한다.
- 억/조, 원/달러, %, %p, 배, 주 등 수치와 단위를 원문대로 보존한다.
- 과거 문서에는 발행일 또는 기준 시점을 노출하고 현재 상태로 단정하지 않는다.
- 긍정·부정 평가는 인용 가능한 문서 근거 범위를 넘지 않는다.

## 안전 및 범위

- 매수·매도·보유 추천, 투자 성향별 지시, 예상 수익 보장, 자동매매를 테스트 케이스로 차단한다.
- 실제 검증용 PDF가 준비되기 전에는 가짜 PDF나 임의 재무 수치를 fixture로 만들지 않는다.
- API 응답과 로그에 키, 비밀번호, 원문 전체 또는 불필요한 개인정보를 남기지 않는다.

## 자동 검증

루트에서 `./scripts/check.sh`를 실행해 backend test, frontend state test, frontend lint, frontend production build가 순서대로 성공해야 한다. Compose 설정은 `docker compose config`로 확인하고, 통합 환경에서는 `docker compose up --build` 후 `/health`와 PostgreSQL의 `pg_extension`을 확인한다.

2차 backend 테스트는 텍스트 PDF 적재, SHA-256 중복 차단, 1-based 페이지 번호, 청크 문자 범위와 인용 복원, mock OCR 판단, 확장자 및 손상 PDF 오류를 포함한다. OCR 통합 점검 시 Docker 안에서 `tesseract --list-langs` 결과에 `kor`, `eng`가 모두 있는지도 확인한다.

3차 테스트는 FakeEmbeddingProvider와 mock Ollama HTTP만 사용해 외부 호출을 차단하고, 동일 provider/model/dimensions skip, 서버 미실행, 모델 미설치, 차원 오류, `HBM`·`파운드리`·`목표주가` BM25 검색, 의미 유사도, RRF 순위, 전체 출처 필드, 사전 메타데이터 필터를 확인한다. PostgreSQL 통합 검증에서는 안전 migration, `vector(1024)`, cosine HNSW 인덱스와 `<=>` 연산을 확인한다.

4차 테스트는 mock GenerationProvider와 mock Ollama HTTP를 사용한다. JSON Schema, 허용되지 않은 근거 ID의 전체 거부, citation 없는 항목 제거, 근거 부족 시 미충족 항목 미생성, Ollama/모델 503, 메타데이터 검증과 프론트 로딩·성공·근거 부족·오류 렌더링을 확인한다. 실제 PDF, 모델 출력 또는 외부 호출은 테스트 fixture에 저장하지 않는다.

Gemini 생성 테스트는 공식 SDK client를 mock하며 실제 API 키나 네트워크를 사용하지 않는다. 성공 시 Ollama 미호출, fallback `none`, timeout·네트워크·HTTP 429·503·504의 최대 2회 Gemini 시도 후 1회 Ollama fallback, 키·HTTP 401·403·404·안전 차단·JSON/Schema/citation 오류의 재시도 및 fallback 금지를 각각 검증한다. 내부 trace의 최종 provider/model, fallback 여부, attempt 수와 상태를 확인한다. 키, 전체 프롬프트와 문서 전문은 로그에 남기지 않는다.

Ollama 생성 provider 테스트는 `stream: false`와 호환형 인라인 JSON Schema payload, 정상 envelope, 공백·JSON 코드블록, HTTP 오류, 연결 오류, envelope 오류, JSON 파싱 오류를 각각 검증한다. HTTP 오류 로그에는 상태 코드와 제한된 응답 일부만 남기고 질문·evidence packet 전체는 남기지 않는다.

분석 근거 품질 테스트는 질문·호재·악재 다중 검색, 선택 문서 필터, 투자등급·면책 제외, 문맥 없는 백분율 표 제외, DB substring 발췌, 한국어 출력, chunk 중복 사용 방지를 포함한다. 호재·악재의 이유가 기업 실적·제품·시장·수익성·위험과 직접 연결되는지 실제 문서 골든셋으로 페이지 단위 대조한다.

버전 관리 평가 fixture에는 document UUID나 실제 생성 결과를 저장하지 않고 파일명·기업명·발행일·문서 유형으로 DB 문서를 찾는다. 문서별 case는 polarity, 실제 PDF 기대 페이지, citation, 한국어 출력, 금지 근거 부재를 판정한다. 아직 업로드하지 않은 fixture 문서는 실패가 아닌 `SKIP`으로 기록하며, 로컬 Ollama 반복 평가에서는 `GENERATION_TEMPERATURE=0`을 유지한다.

평가 실패는 관련 청크가 후보에서 제외됐는지, 잘못된 polarity로 분류됐는지, 모델이 전달된 후보를 선택하지 않았는지, 선택 후 안전 검증에서 제거됐는지 구분한다. 이 내부 trace는 기본 분석 응답과 사용자 UI에 노출하지 않는다. 분석 결과 저장 시 일시적 연결 종료를 복구하더라도 생성 provider는 다시 호출하지 않는다.
