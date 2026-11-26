# Acceptance criteria

## Paddle 신규 적재 검증

- 복잡 페이지에서 유효한 Paddle 결과가 있으면 Tesseract를 호출하지 않는다. worker 실패/무효 결과에서만 기존 fallback을 사용한다.
- native 관측을 유지하고 Paddle의 셀 HTML·OCR 문자열·고유 셀 위치·명시적 단위/기간이 일치할 때만 table fact를 만든다. 병합 셀 등 불확실한 구조는 보류한다.
- 새 업로드의 provenance와 source spans가 청킹·임베딩 후 검색까지 보존된다. 활성 데이터와 기존 revision의 SHA-256은 평가 전후 동일해야 한다.
- 고정 12개 근거 recall 및 기존 성공 회귀 여부는 별도 shadow 실행으로 기록한다. 테스트 통과만으로 10/12 달성을 주장하지 않는다.

## 1차 완료 기준

- `docker compose up --build`로 frontend, backend, PostgreSQL 16 + pgvector가 실행된다.
- 초기 화면에 제품 소개, `서비스 준비 중`, 투자 권유가 아니라는 안내가 보인다.
- `GET /health`가 HTTP 200과 `{\"status\": \"ok\"}`를 반환한다.
- PostgreSQL 초기화 시 `vector` extension이 활성화된다.
- backend 테스트가 1개 이상 통과하고 frontend lint와 production build가 성공한다.
- `scripts/check.sh`가 위 검증을 backend test → frontend lint → frontend build 순서로 실행한다.
- 실제 비밀값이 저장소에 없고 `.env`는 무시된다.

## 향후 분석 기능의 필수 성공 기준

- 모든 핵심 주장에는 원본 파일명, 발행일, PDF 페이지 번호, 근거 문장이 표시된다.
- 핵심 답변 항목은 하나 이상의 유효한 evidence 없이 사용자에게 노출할 수 없다.
- 근거가 부족하거나 문서에서 검증되지 않으면 `확인할 수 없습니다`라고 답한다.
- 과거 보고서의 내용을 최신 사실처럼 단정하지 않고 발행일과 기준 시점을 드러낸다.
- 전망치·추정치와 실제 실적을 명확히 구분한다.
- 금액, 비율, 통화, 배수, 수량 등 원문의 단위를 보존한다.
- 증권사 목표주가는 객관적 사실이 아니라 해당 증권사의 전망임을 표시한다.
- `증권사 전망`과 `DART 공시 사실`을 구분 표시한다.
- 호재·악재 개수를 채우기 위한 추측, 임의 재무 수치, 가짜 인용을 생성하지 않는다.
- 투자 매수·매도 추천, 수익 보장 표현, 자동매매 기능을 제공하지 않는다.

## 2차 완료 기준

- Alembic이 documents, pages, chunks와 nullable `vector` embedding 컬럼을 생성한다.
- 동일 SHA-256 PDF는 한 번만 저장되며 중복 응답이 기존 문서를 가리킨다.
- 원본 PDF와 페이지 이미지는 Git이 아닌 영속 볼륨에 저장된다.
- native text가 설정 임계치보다 짧을 때만 Poppler와 Tesseract `kor+eng` OCR을 시도한다.
- OCR 실패는 `pages.ocr_error`에 기록하고 처리 가능한 다른 페이지를 계속 저장한다.
- 각 chunk는 한 페이지 안에 있고 `final_text[char_start:char_end] == content`를 만족한다.
- PDF가 아니거나 손상됐거나 크기 제한을 넘으면 명확한 4xx 응답을 반환한다.
- 문서 목록·상세·페이지 조회 API가 계약과 일치한다.

## 3차 완료 기준

- 문서별 임베딩 상태·모델·완료 시각·실패 사유·실패 청크 ID가 저장된다.
- 동일 모델로 완료된 청크는 재임베딩하지 않는다.
- `embedding`은 `vector(1024)`이며 cosine HNSW 인덱스가 적용된다.
- 맥 호스트 Ollama와 `bge-m3`만 기본 임베딩 경로로 사용하며 OpenAI API 키나 유료 외부 API가 필요하지 않다.
- Ollama 서버가 꺼졌거나 모델이 없으면 임베딩 API는 `ollama pull bge-m3` 안내가 담긴 `503`을 반환한다.
- Ollama를 사용할 수 없어도 BM25 검색은 동작하고 vector 미사용 사유를 응답에 표시한다.
- 1536차원 기존 벡터가 하나라도 있으면 migration은 자동 삭제·변환 없이 재임베딩 안내와 함께 중단한다.
- 한국어·영문·숫자·종목코드 토큰을 보존한 BM25 후보와 pgvector cosine 후보를 필터 적용 후 구한다.
- 두 후보 순위는 RRF로 결합하며 결과에 각 원본 순위와 RRF 점수를 표시한다.
- top_k 기본값은 5이고 1~20 범위 밖은 `422`다.
- 모든 결과에 파일명, 발행일, 발행기관, 문서 유형, 페이지와 문자 위치로 복원된 원문 인용이 있다.
- 근거가 없으면 `status: no_evidence`와 빈 결과를 반환하며 생성형 답변을 만들지 않는다.

## 4차 완료 기준

- 문서 메타데이터 PATCH는 허용 필드만 수정하며 종목코드는 6자리 숫자 또는 null만 허용한다.
- 선택 문서 범위의 하이브리드 검색 결과만 설정된 Gemini/Ollama 생성 provider에 전달하고 JSON Schema 출력을 검증한다.
- 기본 분석 provider는 Gemini이며 기존 분석 API 응답과 citation 검증을 유지한다. 설정한 경우에만 재시도 가능한 Gemini 오류에서 Ollama를 한 번 fallback으로 사용한다.
- 모델이 검색 결과에 없는 chunk ID를 반환하면 분석 전체를 실패시키고 사유를 기록한다.
- 호재·악재 항목은 실제 citation이 하나 이상 있어야 노출되며, 인용은 DB 원문을 그대로 사용한다.
- 근거가 부족하면 항목을 3개로 채우지 않고 정해진 부족 안내를 표시한다.
- 증권사 리포트 항목은 `증권사 리포트 해석`, DART 항목은 `DART 공시 사실`로 구분한다.
- Ollama fallback을 설정한 경우 `gemma3:4b`가 없으면 pull 안내가 포함된 오류를 반환하고 자동 다운로드하지 않는다.
- 화면은 실제 FastAPI를 호출해 문서 선택·메타데이터 수정·질문·로딩·결과·근거 부족·오류 상태를 제공한다.
- 생성 결과에는 매수·매도·보유 추천, 목표주가 산출과 수익 보장 표현이 없다.
- backend test, frontend component test, lint와 production build가 모두 성공한다.

## 분석 근거 품질 기준

- 한국어 질문의 호재·악재 제목과 설명은 자연스러운 한국어다.
- 사용자 질문, 호재 관점, 악재 관점의 문서 범위 하이브리드 검색 후보를 함께 사용한다.
- 투자등급 정의·비중, 산업 의견 산정 방식, 면책 문구는 호재·악재 근거가 될 수 없다.
- 문맥 없는 숫자·백분율 나열은 제외하고, 실적 전망 등 해석 가능한 제목·문장이 있는 표만 제한적으로 유지한다.
- 같은 chunk는 서로 다른 호재·악재 항목에 중복 배정하지 않는다.
- 인용 카드는 DB 원문에 실제 존재하는 320자 이하의 관련 발췌를 우선 표시한다.
- 원본 `quote`는 그대로 보존하고, 화면 표시용 정규화는 한글 단어 중간 줄바꿈과 의미 없는 단독 OCR 조각에만 적용한다.
- 문맥 없는 표 숫자 덩어리는 카드 본문에 노출하지 않으며, 정확한 표 제목·단위·기간을 원문에서 복원할 수 없으면 해당 PDF 페이지 링크로 안내한다.
- 표의 지표·행·단위·기간·값을 DB 페이지와 citation quote에서 모두 확인하면 `table_facts` 핵심 수치 카드로 표시한다. 값을 계산하거나 OCR 오류를 임의 보정하지 않으며, 하나라도 모호하면 기존 페이지 안내로 fallback한다.
- 원본 PDF 링크는 선택 문서의 영속 볼륨 파일만 inline 제공하고 1부터 시작하는 페이지 fragment로 열린다. 존재하지 않는 문서·페이지와 허용 경로 밖 파일은 실패한다.
- 일반 문장 인용은 완결 문장 경계에서만 끝나며 Analyst·이메일·담당자 연락처와 깨진 OCR 핵심 토큰을 노출하지 않는다.
- 연락처·OCR 잡음이 일부 문장에만 있으면 해당 evidence span만 제외하고 같은 chunk의 정상 문장은 보존한다.
- 동일 chunk의 서로 겹치지 않는 긍정·부정 span은 원본 페이지 문자 범위를 유지한 독립 citation으로 복원된다.
- 범용 요약에서 모델이 한 관점을 누락해도 `quality_status=valid`인 직접 실적·수요·수익성·비용·가격·생산 span이 있으면 중립적 fallback 카드 하나를 복원한다.
- 빈 관점은 `no_evidence`와 `extraction_limited`를 구분하며, 후자는 깨진 OCR 문자열 없이 원문 PDF 페이지 링크를 제공한다.
- 카드 제목은 citation에서 확인되는 구체적인 사업·실적 원인을 포함한다. 주가 상승·하락, 단기 매력, 저평가와 일반적인 긍정·위험 요인 제목은 제거한다.
- 핵심 요약은 최종 검증 후 살아남은 구체 제목만 출처 귀속 문장으로 조합하며 카드가 없으면 `확인할 수 없습니다`를 유지한다.
- 모든 노출 근거는 해당 기업의 실적·제품·시장·수익성·위험 주장과 직접 연결돼야 한다.

## 2026-09-22 신뢰도 수용 조건

- 실제 금융 문서 평가와 변조 청크 단위 테스트를 구분한다. 테스트용 텍스트는 실제 재무 성능 평가 표본이 아니다.
- 인용이 실제 page.final_text 부분 문자열이며, 동일 문서의 유효한 source_chunk_ids가 비공백 전체를 덮어야 한다.
- 근거 없음은 summary `확인할 수 없습니다`, 빈 항목·인용 및 insufficient_evidence 상태로 표시한다. 다른 연도의 사실로 질문을 대체하지 않는다.
- OCR 300dpi는 새 적재에만 적용한다. DB손해보험 1페이지 숫자 개선을 다른 문서의 정확도 개선으로 일반화하지 않는다.
- evals/audit-cases.json의 고정 질문으로 기존 삼성전자와 추가 기업 자료를 나눠 측정한다. HTTP 오류·미검증 항목은 정답으로 취급하지 않는다.

### Retrieval·표·기간 보존 후속 검증

- 생성 미호출, 실제 DB READ ONLY의 고정 11질문/12근거 단위: recall@5 6/12 → 7/12. 기존 2/2 유지, 추가 기업 4/10 → 5/10. 일반 성능으로 확대하지 않는다.
- 행·부모 지표·열·기간·단위·값·페이지가 원문 범위와 저장 chunk로 연결되는 표 후보만 승격한다. 훼손된 기간/열 개수 불일치에서 값을 추정하지 않는다. 기존 PDF fallback/안전 검증을 유지한다.
- 300dpi 버전은 비활성 manifest로만 생성: DB/원본/벡터 무변경. 원본 대조·임베딩·DB 버전 전환 경로가 준비될 때까지 활성화하지 않는다. 재처리 버전 recall 미측정이며 완료로 간주하지 않는다.
- 자세한 6개 실패 분류와 top-5/rank, 악화와 제한은 evals/audit-report.md 후속 절, 원문 판정과 해시는 evals/retrieval-reviewed.json 참조.

### 신규 적재 파서 수락 기준 (2026-09-23)

- native 길이 80자 조건을 제거하고 렌더링 잉크와 native word의 공간 차이, 깨진 문자, 선형 영역의 숫자 누락으로 선택적 OCR을 결정한다. native가 짧아도 렌더링과 일치하면 OCR을 생략한다.
- native 본문을 길이가 긴 OCR로 교체하지 않는다. 겹치지 않는 OCR 영역을 보완하고 겹친 숫자 충돌/불확실 token은 근거로 발행하지 않는다. 낮은 신뢰도의 토큰을 다른 segmentation으로 재확인할 때 원문을 수정하지 않고 동일 토큰만 확인한다.
- 좌표 열/행 대응, 단위, 최소 2개 정렬 데이터 행, 기간·값 confidence 및 모든 원문 chunk 범위를 검증한다. 비고 열 숫자로 깨진 값 셀을 대체하지 않는다.
- 실제 DB 원문과 임베딩은 읽기 전용 평가만 한다. 신규 업로드/임베딩/검색 통합 테스트는 격리 SQLite와 문서 독립 fixture·가짜 embedding provider로 실행한다. 기존 revision activation/재임베딩은 구현하지 않는다.
- 상세한 원문 대조와 남은 보류는 evals/audit-report.md의 신규 적재 섹션을 따른다. 기존 활성 retrieval 7/12와 비활성 신규 파서의 추출 성공 수를 합쳐 성능으로 주장하지 않는다.


### Shadow retrieval 평가 전용 revision

`shadow_revisions / shadow_pages / shadow_chunks`는 기존 document/file hash와 parser version으로 연결된 별도 저장소다. 동일 원본·버전은 unique이며 pages에는 native/OCR/provenance/table facts, chunks에는 원문 offset과 bge-m3 1024 벡터를 보존한다. 공개 API·UI·활성 검색은 이 테이블을 조회하지 않는다. 활성화 API/포인터가 없으며 원본·활성 데이터 수정 없이 CLI로만 생성·검색한다. 동일 검색 함수의 BM25+exact cosine+RRF(k60, 후보20)+검증 표 승격을 revision 내부 행에만 적용한다. 완료되지 않은 임베딩 revision 검색은 거절하며 이미 생성된 벡터는 재생성하지 않는다.


### 신규 적재 fact-fusion-v4

새 file hash와 새 shadow parser version에만 적용한다. native 좌표 문단, PyMuPDF native table cell, 누락 영역 OCR(300dpi PSM6 / 200dpi PSM3 ROI, native 영역을 가린 200dpi PSM6 페이지 문맥)의 후보를 독립 생성한다. OCR 값·기간을 교정하지 않으며 300dpi cropped PSM7의 동일 문자열 확인만 허용한다(페이지당 숫자/기간 16개, 문자 16개). 원본 좌표, 각 word의 DPI/PSM/confidence, 후보 source와 parser version을 provenance에 보관한다. source는 native_text/native_table/ocr_text/ocr_table이다.

`final_text`는 원문 단어의 좌표 읽기 순서를 직렬화한 offset 저장소다. 검증된 paragraph/fact_quote만 검색 대표 청크가 된다. fact_span 청크는 헤더·행·기간·단위·값의 근거 연결에 남지만 독립 BM25/vector 검색 후보가 되지 않는다. 검색/임베딩용 표현은 검증된 사실 필드와 공백 정규화를 사용하며 citation quote/content는 그대로 보존한다. 공개 검색 응답에 additive `numeric_evidence`를 추가하고 기존 table_evidence/페이지/PDF 계약을 유지한다.

동일 위치의 서로 다른 OCR 값/기간/단위는 보류한다. 정상 native 사실은 낮은 우선순위 OCR 충돌로 제거하지 않는다. native 표는 cell 행/열 관계로 별도 사실을 생성하며 좌표 기반 native text 표 후보와도 대조한다. 일반 문장에는 표 UI를 붙이지 않는다. 기존 mixed-layout-v1 페이지/활성 검색/벡터는 새 parser 규칙을 적용하지 않는다. JSON 메타데이터 확장으로 새 DB migration은 없다. 기존 shadow revision도 삭제하거나 활성화하지 않는다.

복합 질문은 각 필수 요구사항을 같은 문서의 검증된 원문 page/span/bbox로 최대 5개 pack에 함께 담았을 때만 `coverage_complete=true`다. 원인 근거 또는 표의 행·지표·기간·단위·값 중 하나라도 빠지면 false로 남기고 분석 생성을 보류한다. 단일 사실 질문의 기존 top-5 ID·quote·table evidence 순위는 유지한다. Shadow 개발 세트와 별도 holdout은 합산하지 않는다.

선택의 complete 판정은 요구 절의 정확한 지표·기간·단위·값·필수 비교 셀과 원문 span을 각각 대조한다. 다른 절의 영업이익률 fact가 영업이익 요구를 충족하지 않는다. 서술은 명시된 factor의 어휘·설명·결과·원문 위치만 결정적으로 검증하며, 암묵적인 모든 원인의 의미적 완전성을 증명했다고 취급하지 않는다. 엄격한 원문 평가를 별도로 유지한다.

동일 행·지표·기간·단위·값·비교 셀의 검증 fact가 여러 페이지에 반복될 때만 이미 선택한 서술 페이지를 우선할 수 있다. 값이나 기간이 다른 fact에는 페이지 근접성을 근거로 우선순위를 주지 않는다.

다단 표의 상단 기간과 하단 열 표기는 원문 bbox로 같은 셀에 연결될 때만 채택한다. 혼합 단위 표에서 행·열의 단위를 확정할 수 없으면 후보를 보류한다. 비교 질의는 주 값과 비교 값의 각각의 헤더·기간·단위·bbox/span이 같은 표 행에서 검증되어야 한다.

구조화 셀은 행·열·기간·단위·값의 bbox/span과 셀 ID가 함께 검증될 때만 후보화한다. 비교는 primitive cell 두 개에서 유도하며 다른 행·표·불명확한 단위를 섞지 않는다. 원본에 없는 연도·단위·값을 만들지 않는다. 주체/지표 분리는 별도 원문 word span이 있을 때만 허용한다. 금액의 `%`, 비율의 금액, 주당 지표의 조원 연결을 거부한다. 새 parser version은 신규 file hash 업로드/비활성 평가에 적용하며 기존 active 데이터와 pinned manifest는 그대로다. 미사용 표 검증과 미사용 문서 검증을 구분해 보고한다.

다기간 비교는 질문에 명시된 정확한 두 기간의 validated primitive에서만 조립한다. 기간별 requirement 중 하나라도 없거나 metric·논리 행·단위·하위 열 facet이 다르면 incomplete다. row ID만 같다는 이유로 연결하지 않고 label provenance와 행 geometry를 확인한다. 여러 하위 열에 다른 값이 있으면 질문의 명시 facet 없이 선택하지 않는다. 단일 사실·컨센서스 경로와 active corpus는 유지한다.

행 그룹은 같은 표의 cell bbox 세로 overlap과 baseline 거리, 모든 셀 쌍의 일관성으로 검증한다. 지표/값은 같은 그룹이어야 하며 기간·열 단위는 값 열의 경계 geometry가 일치해야 한다. 병합 문맥 소속이 불명확하거나 원문 span/bbox가 누락되면 후보를 만들지 않고 구체적인 거절 사유를 기록한다. 이미 관찰한 challenge의 안전한 보류를 일반화 성공으로 세지 않는다.

병합 shared context는 서로 분리된 복수 metric row의 membership을 승인할 수 있다. context_id는 공유하고 ownership_id는 row마다 달라야 한다. membership 승인과 query coverage는 별개다. metric별 unit/value baseline, period column 및 value 교차점 uniqueness, source/cell ownership을 각각 검증하며 서로 다른 row를 graph 비교나 evidence pack에 섞지 않는다. topology 부재에서도 literal span bbox에 같은 row/column 임계값을 적용하고 unit validator를 우회하지 않는다. query target row가 membership의 전체 metric 후보에서 유일하지 않으면 탈락한 sibling chain 여부와 관계없이 HOLD한다. shared proof 누락·변조, duplicate period/value, 중복 cell 소속도 HOLD한다. 기존 “복수 metric이면 무조건 HOLD” acceptance를 이 계약으로 대체한다.

### Compound unit precision gate (2026-10-06)

- `1.2조 원`은 전체 원문 단위 span을 추적할 때에만 `unit_surface=조 원`, `canonical_unit=조원`으로 승인한다. `조 원`/`억원`/`천원`의 `원` suffix만 선택하면 `unit_suffix_conflict`다.
- 다른 행/값 열의 단위, geometry가 없는 header, 불명확한 merged unit/value cell은 보류한다. 검증된 동일 열 header와 원문 `%`/`억원`/`천원` 연결은 유지한다.
- 기존 개발 10/10 후보·2/2 대조군·복합 1/1, 기존 회귀 네 질문과 POSCO pack을 별도로 검증한다. 관찰된 추가 표 3개와 신규 문서 2개는 5개 challenge set이다. false-complete를 우선하고 안전한 보류는 허용한다.
- 앞으로 아직 보지 않은 서비스 범위의 증권사 리포트 또는 DART 문서 2개 이상을 별도 sealed holdout으로 마련해야 한다. 이번 작업에서 다운로드하거나 기능을 추가하지 않는다.

### Metric annotation 동치성

실제 footnote definition과 structural proof가 있을 때만 raw label을 보존하면서 canonical metric을 query에 연결한다. verified annotation + exact canonical match + canonical collision 없음 + 기존 unique row/downstream chain 검증이 모두 필요하다. probable/unverified suffix, 의미 숫자, 다른 reference, 잘못된 source/proof/query canonical 필드, 동일 canonical 후보 복수는 HOLD한다. 동일 marker를 공유하는 서로 다른 metric은 각각의 base와 ownership을 유지한다. plain row와 annotated row의 collision도 검사한다.

현대차의 `3)`는 원문 footer와 반복 convention으로 검증할 수 있지만, 같은 표의 연결/별도 row에서 canonical metric이 충돌하면 coverage를 승인하지 않는다. scope 의미를 자동 추론하여 충돌을 없애지 않는다. 기존 selected pack과 개발/POSCO/삼성/SK 및 기아 manual review 회귀를 유지하고 DB는 READ ONLY hash만 확인한다.

### Query reporting scope acceptance (2026-10-08)

- Preserve explicit reporting scope and exact query offsets independently of metric.
- A canonical collision across verified scopes may PASS only when the explicitly
  requested scope contains one row and its existing unit/period/value/graph/pack
  validators all pass. Keep all global collision candidates in the identity audit.
- Without query scope, with conflicting scope, duplicate same-scope metrics,
  unmatched/unknown membership or missing annotation authorization, HOLD.
- Scope/context/ownership/annotation/period/value tampering and opposite-scope
  comparison insertion must invalidate previously passing evidence.
- Modern Hyundai challenge remains an offline observation fixture; no live DB
  promotion. Development 12/12, POSCO 1/1, Samsung false-complete 0, SK HOLD,
  Kia manual strict review and previous selected evidence packs remain required.

### Verified dependency admission

- Revalidate primitive cells from stored source words/topology before admission;
  retain only their declared metric/context/unit/period/value/annotation dependencies.
- Separate scope/ownership groups; share source references without joining owners.
  A value source with conflicting row owners cannot authorize admission.
- Preserve page slices and offsets; expose full chain search text only at the
  group's metric anchor. Never overwrite source text with a canonical label.
- Missing annotation proof, unverified primitives, altered ownership, borrowed
  sibling values and period-only cells cannot authorize dependency groups.
- Regenerate Hyundai only in a new offline fixture, using unchanged production
  BM25/RRF/selector/coverage. Without stored new embeddings, report vector results
  as unavailable; do not invent vector ranks or make external calls.

- Composite units in verified-dependencies-v1 preserve all source token components
  and the full literal unit span without surrounding line/cell admission.
- A searchable semantic unit cannot satisfy missing original component coverage.
  Component ownership conflicts, ambiguous membership and injected dependencies
  must fail verification; verified shared headers retain distinct metric owners.
- Samsung offline fixture regeneration may admit verified native unit components;
  Paddle source-cell geometry thresholds and live data remain unchanged.

### Source-owned period binding v1 acceptance

- 단일 기간 열도 두 기간 비교와 독립적으로 verified primitive를 생성할 수 있다.
- Literal 기간 header의 유일한 column group owner, value column membership,
  기존 metric row/geometry/unit proof를 모두 원문에서 재구성한다.
- 같은 열에 복수 period owner, unsupported date header 충돌, actual/forecast
  충돌, foreign table/document, span/ownership 변조는 HOLD한다.
- 명시적 한 문장 안의 한 기간·한 지표 구문만 paragraph binding으로 지원한다.
  미등록 지표/다른 subject를 지나거나 다른 문장/문단에서 상속하지 않는다.
- 새 extraction의 proof 삭제는 거절한다. Legacy numeric observation은 기존
  계약을 유지하며 새 ownership을 검증했다고 표시하지 않는다. Legacy table도
  source rederivation을 통과해야 한다.
- Independent synthetic fixture에서 primitive graph → dependency admission →
  physical chunk → BM25 candidate → evidence pack → coverage를 검증한다.
  Numeric prose는 기존 numeric candidate/pack 경로를 사용한다.
- Sealed holdout v1 재실행·재채점 없이 기존 개발/오프라인 regression으로 검증한다.

### Unit binding Stage 2 acceptance

- 독립 synthetic cell/row/column/table 단일 선언, composite 조+원·million+USD,
  명시적으로 분리된 mixed row는 graph→dependency admission→exact chunks→pack→coverage로 전달한다.
- 다른 metric row/column, 복수 table 선언, unmapped mixed header, source/proof/component 삭제,
  ownership/scope/canonical/source 변조, 단위 추정은 HOLD다.
- Unit proof만으로 scope/annotation/comparison 등 다른 requirement를 승인하지 않는다.
- 기존 period regression, development 12/12, POSCO 1/1, selected pack 20/20,
  현대차·삼성 offline PASS, 기아 REVIEW, SK·Counts HOLD, review-aware false-complete 0을 유지한다.
- Sealed v1은 hash/permission/flags만 대조하며 재실행·재채점·Gold 변경은 금지한다.
- Live DB 종료 상태이면 DB hash는 NOT_VERIFIED다. 서비스 재기동/DB write/migration,
  OCR/embedding/LLM 및 retrieval parameter 변경 없이 검증한다.

### Scope binding Stage 3 acceptance

- 독립 row/column/section/merged/parent-child fixture에서 scope, period, unit,
  metric/value ownership을 graph→admission→exact chunk→pack→coverage까지 보존한다.
- Section은 full-width topology 및 다음 section 경계로 interval을 증명한다.
  Parent/child는 adjacent columns, rowspan containment, literal spans가 모두 필요하다.
- Scope 미명시 기본값, mismatch, 동일 scope의 중복 metric, proof/identity 삭제·변조,
  불명확한 상속, period/unit 미검증, 다른 scope value 혼입은 HOLD한다.
- 기존 native merged context의 검증된 독립 row membership을 재사용한다.
- 개발 12/12, POSCO 1/1, selected pack 20/20, offline PASS/REVIEW/HOLD 상태,
  review-aware false-complete 0과 sealed v1 파일 무결성을 유지해야 한다.
- DB 재기동/write/migration, OCR/embedding/LLM 및 sealed 재실행·재채점 없이 검증한다.

### Service quality E2E acceptance (2026-10-12)

이번 통합 작업은 격리 persistent E2E DB에서만 누락 embedding 및 새 analysis run을
허용한다. 기존 단계의 offline 제한과 구분하며 Production migration/write는 금지한다.
583개 UUID/source/provenance 보존, 1024차원 finite nonzero vector, restart hash 일치가
검색 실행의 선행 조건이다. OCR/chunk를 다시 생성하지 않는다.
빈 factual requirement, parser 예외, scope/period/unit 불일치는 LLM 전에 HOLD한다.
원문 bbox가 검증된 경우에만 동일 좌표계 image/SVG로 표시한다.
브라우저에서 카드·원문 페이지·HOLD/오류를 확인하며 API 성공만으로 UI PASS를 기록하지 않는다.
실행하지 못한 항목은 NOT_VERIFIED로 기록하고 sealed first-run은 재실행/재채점하지 않는다.
# Low-memory acceptance (2026-10-13)

- Default execution remains unchanged; development low-memory mode preserves original quotes, units, periods, scope and evidence UUIDs.
- Actual SDK in-memory HTTP tests must show no hidden retries; fallback still creates one analysis run and validates evidence before publication.
- Prompt UUIDs and factual evidence are unchanged. Reject prompt optimizations that reduce verified coverage even if latency improves.
- Performance results report cold/warm native load timing and host swap; isolated favorable runs are not proof of stable latency or causality.

## Provider consent acceptance (2026-10-13)

- Omitted mode is LOCAL_ONLY even with a Gemini key/legacy configuration. Local requests must not construct or invoke an external adapter.
- External mode needs strict true request consent plus server policy; forbidden provider/fallback blocks before retrieval/run creation.
- Same verified evidence yields the same grounded bounded cards/citations across local/mock Gemini/mock fallback. Fabricated numbers/unknown UUIDs/period-unit-scope errors and existing HOLD/REVIEW remain blocked.
- UI defaults local, describes transmission before consent, resets consent after edits/submission and shows generation/fallback/validation/completion/failure/HOLD. No unvalidated model text streaming.
- Mock timing is not external performance. Real Gemini latency/fallback/quality stays NOT_VERIFIED until separately approved execution.
