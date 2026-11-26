# QA rules

## Paddle CPU worker

- PaddleOCR 3.3.2 / PaddleX 3.3.13 / PaddlePaddle 3.2.2는 backend와 분리한다. 생성 모델을 호출하지 않는다.
- 모델이 반환한 줄 bbox를 임의 단어 bbox로 나누지 않는다. 낮은 confidence, HTML/OCR 불일치, 여러 셀에 걸친 중심점, 병합 셀은 fact로 승인하지 않는다.
- 한국어 원본 렌더와 기간·행·단위·값을 대조한다. OCR 문자열 존재나 confidence만으로 정답 처리하지 않는다.
- 행과 괄호 단위가 한 OCR 영역이면 문자 범위만 분리하고 동일한 원본 영역 bbox/관측 ID를 보존한다. 글자별 좌표를 추정하지 않는다.
- disabled chart 모델의 불필요한 초기화만 버전 고정 패치로 차단한다. 메모리 부족/worker 오류는 provenance에 기록하며 recall을 추정하지 않는다.

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
11. 원본 `quote`와 표시용 `display_quote`를 구분한다. 표시용 정규화가 수치·단위·문장 의미를 바꾸지 않는지 검사한다.
12. 표 중심 citation에 제목·단위·기간 헤더가 없으면 숫자 나열을 숨기고 실제 PDF 페이지 링크를 제공한다. 표시한 표 라벨은 모두 원문 문자열에 존재해야 한다.
13. `table_facts`는 같은 페이지에서 지표·행·단위·기간·값의 열 정렬을 확인하고 값이 원본 citation에도 존재할 때만 만든다. 증감률이나 합계를 계산하지 않으며 OCR 표 제목이 모호하면 제목을 생략한다.
14. 일반 인용은 완결 문장 1~2개만 선택한다. `Analyst`, 이메일, 연락처와 단독 OCR 잡음을 제거하고 `Google, Meta` 또는 한글 단어 중간에서 자르지 않는다.
15. 정상 약어 AMD·HBM·DRAM·NAND·Foundry/LS·CSP는 OCR 잡음으로 간주하지 않는다. 깨진 토큰이 핵심 주장에 포함되면 후보 및 카드를 제외한다.
16. 품질 판정은 chunk 전체가 아니라 완결 문장·문단 또는 검증된 표 행 evidence span에 적용한다. 연락처·면책·OCR 잡음이 있는 span만 제외하고 같은 chunk의 정상 span은 유지한다.
17. 같은 원본 chunk의 서로 겹치지 않는 긍정·부정 span은 각각 사용할 수 있다. 동일하거나 짧은 쪽 기준 80% 이상 겹치는 span은 중복 노출하지 않는다.
18. 범용 요약의 polarity fallback은 `quality_status=valid`, 복원 가능한 페이지 문자 범위, 직접적인 사업·실적 사실을 모두 만족하는 span에만 적용한다. 불완전 표와 OCR 제외 span에는 적용하지 않는다.
19. 빈 polarity는 `no_evidence`와 `extraction_limited`를 구분한다. 후자의 일반 응답에는 내부 제외 사유나 깨진 문자열을 넣지 않고 PDF 페이지 번호만 제공한다.
16. `주가 하락 가능성`, `단기 매력`, `저평가`, 매수·매도·목표주가와 일반적인 `수요 관련 전망`, `위험 요인` 제목을 차단한다. 원문에서 구체 원인을 복원할 수 없으면 polarity 카드를 비워 둔다.

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

원본 PDF 제공 테스트는 inline PDF 응답, 페이지 범위, 없는 문서와 허용된 raw 디렉터리 밖 storage path 차단을 확인한다. citation 표시 테스트는 한글 단어 중간 줄바꿈 복원, 단독 OCR 잡음 제거, 숫자 표 조각 숨김과 `#page=` 링크를 확인한다.

Gemini 생성 테스트는 공식 SDK client를 mock하며 실제 API 키나 네트워크를 사용하지 않는다. 성공 시 Ollama 미호출, fallback `none`, timeout·네트워크·HTTP 429·503·504의 최대 2회 Gemini 시도 후 1회 Ollama fallback, 키·HTTP 401·403·404·안전 차단·JSON/Schema/citation 오류의 재시도 및 fallback 금지를 각각 검증한다. 내부 trace의 최종 provider/model, fallback 여부, attempt 수와 상태를 확인한다. 키, 전체 프롬프트와 문서 전문은 로그에 남기지 않는다.

Ollama 생성 provider 테스트는 `stream: false`와 호환형 인라인 JSON Schema payload, 정상 envelope, 공백·JSON 코드블록, HTTP 오류, 연결 오류, envelope 오류, JSON 파싱 오류를 각각 검증한다. HTTP 오류 로그에는 상태 코드와 제한된 응답 일부만 남기고 질문·evidence packet 전체는 남기지 않는다.

분석 근거 품질 테스트는 질문·호재·악재 다중 검색, 선택 문서 필터, 투자등급·면책 제외, 문맥 없는 백분율 표 제외, DB substring 발췌, 한국어 출력, chunk 중복 사용 방지를 포함한다. 호재·악재의 이유가 기업 실적·제품·시장·수익성·위험과 직접 연결되는지 실제 문서 골든셋으로 페이지 단위 대조한다.

버전 관리 평가 fixture에는 document UUID나 실제 생성 결과를 저장하지 않고 파일명·기업명·발행일·문서 유형으로 DB 문서를 찾는다. 문서별 case는 polarity, 실제 PDF 기대 페이지, citation, 한국어 출력, 금지 근거 부재를 판정한다. 아직 업로드하지 않은 fixture 문서는 실패가 아닌 `SKIP`으로 기록하며, 로컬 Ollama 반복 평가에서는 `GENERATION_TEMPERATURE=0`을 유지한다.

평가 실패는 관련 청크가 후보에서 제외됐는지, 잘못된 polarity로 분류됐는지, 모델이 전달된 후보를 선택하지 않았는지, 선택 후 안전 검증에서 제거됐는지 구분한다. 이 내부 trace는 기본 분석 응답과 사용자 UI에 노출하지 않는다. 분석 결과 저장 시 일시적 연결 종료를 복구하더라도 생성 provider는 다시 호출하지 않는다.

## 2026-09-22 측정 및 회귀 검사

- `./scripts/check.sh`와 `python scripts/audit_rag.py --output evals/results/audit/run.json`을 사용한다. 검색만 분리할 때 `--retrieval-only`.
- page recall@5와 실제 정답 근거 recall@5를 구분한다. 같은 페이지의 다른 청크 노출은 근거 검색 성공이 아니다. 답변 정확성·주장 지지 여부는 원문 시각 대조 후 판정하며 null은 미평가다.
- content/offset/page_number/document 연결 변조 및 청크 미포함 문장이 후보에 섞이는 회귀를 검사한다. 순서가 다른 청크도 오프셋으로 정렬하고 공백 이외 누락을 거부한다.
- PDF 물리적 페이지와 인쇄 쪽수를 구별한다. OCR 텍스트의 숫자·분기·단위가 PDF와 다르면 DB 문자열과의 일치만으로 인용을 통과시키지 않는다.
- google-genai 2.18.1의 Interactions 내부 재시도는 서비스 바깥의 재시도다. HttpRetryOptions attempts=1도 내부 1회 재시도로 변환된다. 서비스 시도 횟수는 실제 HTTP 요청 횟수와 다르며 엄격한 총 wall-clock deadline을 보장하지 않는다.

### 표 구조와 retrieval 회귀

문서 독립 fake chunk/table fixture에서 F/E/A/P·불명확 기간, 지표 부모 행, 행/열 수 불일치·분절, 중복 열, 헤더 청크 누락/잘못된 페이지, 일반 문장의 표 오분류, 실적과 시장 기대치의 원문 span 구분을 검사한다. 강한 방해 후보 때문에 top-5에서 빠진 표를 별도 pool이 회복하는 통합 테스트를 유지한다. 기업명·문서 ID를 운영 검색 조건으로 추가하지 않는다.

실제 DB 평가에는 scripts/audit_retrieval.py만 사용하며 READ ONLY 트랜잭션을 강제한다. query embedding은 허용하지만 생성/기존 17문항 CLI는 이번 작업에서 호출하지 않는다. page hit와 gold span/table cell hit를 구분한다. 상위 후보 순서 변경에 따른 기존 hit 유실도 비교한다. 300dpi 재처리 manifest는 삭제/활성화 명령이 없고 원본 해시와 버전을 포함한다. DB 활성 버전 전환은 별도 미구현 항목이다.

### 혼합 페이지·좌표 추출 테스트 (2026-09-23)

긴 native 본문+미포함 시각 영역, 짧고 완전한 native 페이지의 OCR 생략, 숫자 충돌 시 native 보존과 근거 제외, OCR 실패 시 정상 native 보존, 낮은 confidence 수치 보류, 깨진 기간 미보정, 비고 열 날짜의 값 오인 방지, 정상 본문/표 구분을 테스트한다. source word 좌표/offset, final_text 해시, row/metric/period/unit/value 검증을 우회하는 stored fact는 거부한다.

신규 업로드→짧은 청크 분할→임베딩→검색 및 neutral 분석 후보까지 provenance가 유지되어야 한다. 같은 페이지라도 올바른 source_spans를 모두 덮는 chunk가 없으면 표 후보를 승격하지 않는다. 기존 안전성/삼성전자 회귀 테스트를 유지한다. 실제 PDF 비교는 scripts/audit_parser.py의 비활성 실행으로만 하며 원본 hash를 검사한다.


### Shadow retrieval 평가 전용 revision

`shadow_revisions / shadow_pages / shadow_chunks`는 기존 document/file hash와 parser version으로 연결된 별도 저장소다. 동일 원본·버전은 unique이며 pages에는 native/OCR/provenance/table facts, chunks에는 원문 offset과 bge-m3 1024 벡터를 보존한다. 공개 API·UI·활성 검색은 이 테이블을 조회하지 않는다. 활성화 API/포인터가 없으며 원본·활성 데이터 수정 없이 CLI로만 생성·검색한다. 동일 검색 함수의 BM25+exact cosine+RRF(k60, 후보20)+검증 표 승격을 revision 내부 행에만 적용한다. 완료되지 않은 임베딩 revision 검색은 거절하며 이미 생성된 벡터는 재생성하지 않는다.


### 신규 적재 fact-fusion-v4

새 file hash와 새 shadow parser version에만 적용한다. native 좌표 문단, PyMuPDF native table cell, 누락 영역 OCR(300dpi PSM6 / 200dpi PSM3 ROI, native 영역을 가린 200dpi PSM6 페이지 문맥)의 후보를 독립 생성한다. OCR 값·기간을 교정하지 않으며 300dpi cropped PSM7의 동일 문자열 확인만 허용한다(페이지당 숫자/기간 16개, 문자 16개). 원본 좌표, 각 word의 DPI/PSM/confidence, 후보 source와 parser version을 provenance에 보관한다. source는 native_text/native_table/ocr_text/ocr_table이다.

`final_text`는 원문 단어의 좌표 읽기 순서를 직렬화한 offset 저장소다. 검증된 paragraph/fact_quote만 검색 대표 청크가 된다. fact_span 청크는 헤더·행·기간·단위·값의 근거 연결에 남지만 독립 BM25/vector 검색 후보가 되지 않는다. 검색/임베딩용 표현은 검증된 사실 필드와 공백 정규화를 사용하며 citation quote/content는 그대로 보존한다. 공개 검색 응답에 additive `numeric_evidence`를 추가하고 기존 table_evidence/페이지/PDF 계약을 유지한다.

복합 헤더 표는 상단 기간·하단 열·행·값의 좌표를 따로 검증한다. 같은 페이지의 근접 숫자나 이전 행의 단위를 상속하지 않는다. 비교 질문은 별도 비교 셀의 label/period/unit/value/source span이 없으면 `coverage_complete=false`다. 표 fact가 없을 때 본문 numeric evidence로 표 요구를 대체하지 않는다.

Selection 회귀 검사는 지표 충돌(금액/비율/증가율), F/P/A 및 연간/분기 기간 불일치, 단위 불일치, 비교 셀 누락, 올바른 후보 선호, 명시적 서술 factor 일부 누락을 포함한다. 동일 고정 shadow/index에서 전후 검색하며 글로벌 top-5 ID·quote·table evidence와 active corpus hash를 별도로 비교한다. Coverage의 lexical match와 원문 gold의 strict 성공은 같은 지표가 아니다.

동일 위치의 서로 다른 OCR 값/기간/단위는 보류한다. 정상 native 사실은 낮은 우선순위 OCR 충돌로 제거하지 않는다. native 표는 cell 행/열 관계로 별도 사실을 생성하며 좌표 기반 native text 표 후보와도 대조한다. 일반 문장에는 표 UI를 붙이지 않는다. 기존 mixed-layout-v1 페이지/활성 검색/벡터는 새 parser 규칙을 적용하지 않는다. JSON 메타데이터 확장으로 새 DB migration은 없다. 기존 shadow revision도 삭제하거나 활성화하지 않는다.

복합 질문 평가에서는 전역 top-5와 evidence pack을 별도로 기록한다. `compound_evidence_coverage@5`는 모든 필수 서술/표 사실이 원문 위치가 검증된 한 pack 안에 있을 때만 성공이다. `single_fact_regression`은 단일 질문의 기존 top-5 ID·quote·table evidence를 비교한다. Pinned manifest가 없거나 worker/source/bbox/hash가 어긋나면 채점하지 않는다. 개발 10/10·대조군 2/2·복합 coverage 1/1·단일 회귀 0을 확인한 뒤에만 사전 고정 holdout을 한 번 평가하고, 결과를 개발 점수와 합산하지 않는다.

Primitive cell extraction 검증은 세로/가로 기간, 명시 단위 열, 여러 단위의 scope, 금액/비율/주당/수량 호환성, 병합 헤더의 물리 cell 대응, 비교 양쪽 span 변조, 축약 연도의 원문 교차 확인, 주체 span 변조를 포함한다. 불완전한 표를 numeric prose로 대체하지 않는다. 새 업로드 fixture에서 ingestion → source_chunk_ids → embedding → 검색까지 확인한다. 임시 추출 인덱스의 재실행은 같은 원문/fixture/index hash로 비교하며 생성 모델을 호출하지 않는다. 평가 artifact의 벡터는 문자열이 아닌 float 배열로 저장한다. 원문 의미 판정을 자동 채점할 수 없는 서술은 수동 원문 리뷰로 분리한다.

Primitive graph 회귀: 3개 이상 기간에서 요청한 두 기간만 선택, A/F/P/FY/분기 구분, 유사 금액/비율 metric 분리, missing period·unknown/mismatched unit·변조 셀 reject, row ID가 달라도 검증된 같은 logical row만 연결, merged parent-year/child-column facet 분리, 양쪽 원문 span·pack 독립 requirement 검증. OCR 숫자는 graph에서 교정하지 않는다. 신규 미사용 문서는 production source hash를 고정한 뒤 선택하고 평가 결과를 본 뒤 production 규칙을 조정하지 않는다.

### Compound unit precision gate (2026-10-06)

`tests/test_unit_validation.py`에서 전체 compound span, suffix 충돌, 정상 단위, 다른 행/열 차단, header topology/merged 보류, 신규 삼성 incomplete, corpus shortcut 금지를 검사한다. `scripts/audit_unit_precision.py`는 원문 관찰·원본 manifest·저장된 BM25/vector 순위를 고정해 검증/selection만 재생하며 OCR·임베딩·LLM·DB를 호출하지 않는다. 새 retrieval 실행이나 live active hash 검증으로 표현하지 않는다. 기존 회귀 네 질문과 5개 challenge를 분리해 기록한다. 로컬 challenge 원시 자료가 없으면 해당 테스트는 skip하며 일반화 성공으로 세지 않는다.

target 테스트를 먼저 실행한 뒤 최종 `./scripts/check.sh`, Compose health, `git diff --check`를 확인한다. live DB/Compose가 중단되어 있으면 확인하지 못한 항목을 명시하고 과거 active hash를 현재 증거로 재사용하지 않는다.

`tests/test_row_association.py`는 같은 행/열 승인, 다른 행 지표·다른 열 값/기간·단위의 변조 거절, 헤더 경계 충돌, merged body/header, span 누락 및 immutable challenge 원문 bbox를 검증한다. `audit_unit_precision.py --row-association`은 challenge cell fact만 동결 text/word/cell bbox에서 재생성하고 기존 rank/index/selection 규칙을 유지한다. 개발 12개·고정 regression·POSCO compound를 별도로 확인한다. 거절 audit의 원문 span/bbox·단계와 coverage를 보고하고 active PostgreSQL 정렬 JSON hash를 라이브 읽기로 대조한다. challenge는 sealed holdout이 아니며 새 sealed holdout 수집은 후속 작업이다.

`tests/test_metric_context_ownership.py`의 기존 uniqueness·geometry·source·period·value·graph 검사를 유지하되, 복수 분리 row의 blanket HOLD expectation은 shared membership 승인으로 바꾼다. `tests/test_shared_metric_context.py`는 topology 있음/없음, 분리된 2×2 chain, graph isolation, target-only 비교/단일 기간 pack을 검증한다. sibling unit/value 차용, 동일 value span 공유, 중복 value, 중복 source/cell 및 unit cell, 겹친 metric row 경계, target 미지정, row 귀속 불명, period ambiguity, mixed comparison, 동일 이름의 복수 row, 탈락한 sibling, shared proof 삭제 및 ownership 변조는 HOLD한다. 실제 challenge 테스트는 gold source span/bbox에 맞는 primitive 승인과 query coverage를 분리한다. row ≥80%/baseline ≤20%, column ≥90%/boundary ≤10%와 unit validator는 변경하지 않는다.

검증은 targeted shared-context/ownership/row/column/graph/requirement/unit 테스트, `./scripts/check.sh`, immutable observation과 frozen hybrid rank의 offline replay, production hardcoding 검사 및 이번 변경 diff 검사를 실행한다. 개발 12/12, POSCO 1/1, 삼성 false-complete 0, SK HOLD, 기존 fixed-regression selected pack과 기아 manual strict review를 유지한다. active DB는 REPEATABLE READ READ ONLY 트랜잭션에서 전후 테이블 해시만 확인한다. migration/reprocessing/OCR/embedding/LLM/active revision mutation은 실행하지 않는다.

### Metric annotation 검증

`tests/test_metric_annotations.py`는 실제 footnote proof가 있는 두 ratio metric의 exact canonical match, 별도 superscript span, 같은 verified marker의 서로 다른 base 및 isolated comparison pack을 검증한다. 의미 숫자 10종 보존, 정의 없는 suffix, plain numbered reference, 두 annotation/bare row collision 및 탈락한 sibling, partial/substring query, raw/canonical/marker/proof/definition 변조·삭제, query canonical 불일치, empty base, remote/중복/unsafe definition, 손상된 downstream chain을 HOLD한다. proof rederivation과 pack source/chunk coverage를 함께 검사한다. semantic annotation 계층을 제거한 RED 테스트에서 기존 suffix mismatch를 재현한다.

shared-context/ownership/row/column/unit/graph 테스트를 유지하고 전체 `./scripts/check.sh`, immutable observation/frozen hybrid rank replay, hardcoding/diff 검사, REPEATABLE READ READ ONLY의 active 5개 테이블 전후 해시 검증을 실행한다. geometry/shared/unit validator 및 pipeline source hash는 불변이어야 한다. 현대차는 footnote 승인 여부와 canonical collision/최종 coverage를 각각 보고하며 false-complete 0을 우선한다.

### Query reporting scope QA (2026-10-08)

Run `backend/tests/test_query_scope.py` with annotation, shared context, ownership,
row/column regression tests, then `./scripts/check.sh`. Re-evaluate immutable
observations with `scripts/audit_unit_precision.py --row-association` using a new
output artifact; no OCR, embedding, LLM or database operations. Compare prior
selected packs, development/POSCO/Samsung/SK/Kia outcomes. Validate active five
DB table hashes before/after using `scripts/hash_active_tables.py` (READ ONLY).
Scope is never a company/row/value heuristic, and never a concatenated metric
label. Source literals alone are insufficient: membership and independent row
ownership must be rederived. Explicit scope authorizes only scope-local uniqueness,
not unit/value/period approval. Check query removal/change, scope span/membership
removal, context/ownership ID mutation, annotation deletion, period/value mutation,
and opposite-scope comparison insertion. Unsupported or ambiguous cases HOLD.

### Dependency admission QA

Check exact source coverage and selected-pack coverage for every group dependency;
check raw label → marker → definition → canonical traceability, both periods,
shared context with separate metric/value owners, and connected/separate scopes.
Check no unrelated page/row span, no forged IDs, missing values/units or annotation
proof can enter a verified dependency group. Physical ranges deduplicate by page
and offsets; groups share references, not scope identity. Keep frozen regression
corpora untouched. Run targeted tests, `./scripts/check.sh`, frozen-rank regressions,
diff/hardcoding checks and before/after READ ONLY active table hashes. Fresh offline
BM25 and stored hybrid-rank replay are separate evaluations; neither substitutes
for a vector replay over embeddings that do not exist.

`tests/test_unit_dependencies.py` verifies atomic units, two/multiple source
components, complete metric/value comparison packs, partial-unit coverage failure,
owner/row/table/context/membership conflicts, ambiguous duplicate observations,
different-cell components, unverified primitives and injected unrelated spans.
The component contract is dictionary-independent; English unit examples test the
contract after semantic verification, without expanding the current unit parser.
Existing frozen selected packs and review-aware outcomes must remain unchanged.

### Source-owned period binding v1 QA

`backend/tests/test_period_binding.py`는 corpus를 읽지 않는 독립 synthetic fixture다.
단일/복수/multi-level header와 명시적 문장, 별도 actual/forecast 문장의 positive를
검증한다. 복수 header owner, 다른 row/column/table/document, period span 삭제,
owner 변조, qualifier 충돌, 다른 문장/지표/미등록 subject 및 proof 삭제의 negative는
admission/candidate/pack에서 거절되어야 한다. Unit/scope/geometry validator를 우회하지 않는다.
기존 development 검증은 original parser version을 유지한 frozen observation/rank로
실행한다. Offline PASS와 manual REVIEW, coverage와 automatic strict를 구분한다.
Live DB hash는 서비스가 종료된 동안 `NOT_VERIFIED`로 기록하고 재기동하지 않는다.
Sealed first-run 파일의 SHA-256, permission, immutable flag를 전후 비교한다.

### Source-owned unit QA

`test_unit_binding.py`의 독립 source fixture로 적용 범위와 conflict를 검증한다.
모든 승인에는 unique source owner와 기존 full-unit/component validator 통과가 필요하다.
Cell의 단위가 있다고 row/column/table 선언을 버리지 않는다. 단위가 같은 복수 owner도
임의 선택하지 않는다. Source stream과 table membership 밖의 unit은 상속하지 않는다.
Proof와 constituent 원문 span을 admission과 pack에서 재검증하며 새 v5 proof 삭제를 거절한다.
Unsupported merged/multi-level unit mapping과 remote scope declaration은 추정하지 않는다.
기존 fixture는 원래 processing_version과 frozen ranks를 보존하여 대조하고 v1은 실행하지 않는다.

### Source-owned scope QA

`backend/tests/test_scope_binding.py`의 독립 source fixture로 다섯 구조의 positive,
query에 따른 유일한 metric 선택, scoped two-period comparison과 negative를 검증한다.
Scope span/bbox/hash/table/page/document/context/ownership 및 period/unit proof를
삭제·변조하면 admission/pack/coverage가 거절해야 한다. Canonical collision은 query와
검증된 scope-local uniqueness로만 제한한다. Query/source mismatch와 parent/child
proof 누락은 HOLD이며 unsupported header를 unscoped default로 처리하지 않는다.
원문 context boundary와 section 종료 span을 dependency에서 확인한다.
기존 archived observations/ranks를 그대로 재검증하고 selected pack을 완전 비교한다.
Sealed v1은 hash/mode/flags 대조만 수행하며 실행/채점하지 않는다. Live DB hash는
종료 상태에서 `NOT_VERIFIED`다. Production parser hash를 고정한 뒤 회귀를 실행한다.

### Service quality QA (2026-10-12)

`test_service_requirements.py`, `test_verification_performance.py`,
`test_citation_geometry.py`, `test_dependency_errors.py`, frontend API/UI tests로
empty requirement fail-closed, cache mutation/request isolation, 동일 cell membership,
literal geometry와 오류 안내를 검증한다. 전체 `scripts/check.sh`를 실행한다.
비교는 같은 E2E DB/query/model/cutoff의 순차 요청으로 기록하며 cProfile 시간은
실사용 latency와 구분한다. Source/chunk/vector hash와 selected 결과를 완전 대조한다.
Sealed document/gold/prediction/scoring inventory의 hash/mode/immutable flags만 검증한다.
Production DB에는 접속하지 않는다. 새 E2E run을 과거 완료 run으로 위장하지 않는다.
# Runtime optimization QA (2026-10-13)

- Run `test_generation_transport.py`, `test_low_memory.py`, provider/requirement/citation regressions and `./scripts/check.sh`.
- Benchmark with `scripts/measure_e2e_generation.py` against its fixed guarded E2E database only; snapshot 583 finite nonzero 1024-dimensional vectors and source hashes before/after. Do not run restoration/migration/embedding modes.
- Samples cover host vm_stat/pressure/swap/process RSS, thermal observations and /api/ps. Missing observations are NOT_VERIFIED; RSS is not total unified-memory peak.
- Build E2E UI with NEXT_DIST_DIR=.next-e2e to keep the running dev cache separate. Browser success requires actual cards, citation/page/bbox and HOLD observations; API-only runs do not count.

## Provider execution QA (2026-10-13)

- Run test_provider_consent.py, existing generation transport/analysis/low-memory/requirement/citation tests, frontend consent/stream tests and scripts/check.sh.
- Mock success/timeout429/transient/schema failures; verify retry bounds, one allowed local fallback, none for schema/auth/safety/citation errors and one analysis_run with consent metadata.
- Test JSON and stream consent gates. Never send actual document evidence to Gemini without separate explicit approval or infer consent from environment/key presence.
- Browser fixtures must be labelled mock. Observe consent/status/citation/bbox/HOLD separately from actual external E2E or latency.
- Keep108~304s local baseline; external latency NOT_VERIFIED. Hash guarded E2E source/chunks/583vectors and sealed files before/after. No production or sealed regrading. Reuse development replay with new artifact paths and existing audit-only cache wrapper; do not overwrite old results.
