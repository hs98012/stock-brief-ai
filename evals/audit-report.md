# RAG 정확도·근거 신뢰도 진단 (2026-09-22)

## 범위와 기준선

작업 시작 시 이미 존재한 미커밋 변경을 포함한 작업 트리가 기준선이다. HEAD를 기준으로 재설정하지 않았다. 기존 evidence_facts.py, document_candidates.py 및 회귀 테스트를 이번 작업의 신규 구현으로 주장하지 않는다. 시작 상태 backend 테스트는 174 통과 / 1 실패였다.

기존 삼성전자 fixture 5개·17문항 중 2025-07-09 보고서의 3문항을 재사용했다. DB손해보험·LG·POSCO홀딩스 3개 추가 기업 보고서로 8문항을 작성했다. 세 보고서도 이미 DB에 있었으므로 엄격한 blind holdout은 아니다. 파일 SHA-256은 audit-documents.json에 기록했다. 질문과 원문 정답은 audit-cases.json에 고정했고, 신규 자료의 1·2페이지, LG 3페이지, DB손해보험 전체 4페이지를 시각 대조했다. 기존 삼성전자 1페이지도 원본을 확인했다. 기존 근거 없음 문항의 전 페이지 확인은 기존 fixture의 검토 기록에 의존한다.

변경 전 Docker 이미지 ID는 `a92eac57eba2695f1cfa0454a0bdaa1399f82baa7daa5725fd39675a58872bfc`, 최종 변경 후는 `9f07172f930558eb3e80f5cb109f63d55901f1f90038c9bdefb41406635469c6`이다. 같은 DB 원문·청크·벡터를 사용했고 질문 파일 해시도 동일하다.

공개 기본 Gemini 경로는 HTTP 429 및 SDK 내부 재시도 대기로 90초 클라이언트 제한을 넘었다. 임시 서버에서 동일 bge-m3 + gemma3:4b, temperature=0, 생성 제한 90초, 클라이언트 110초로 비교했다. 서비스 기본 .env와 문서·페이지·청크·벡터는 변경하지 않았다. 평가 실행에 따른 analysis_runs 기록은 추가됐다. 로컬 모델 비교를 Gemini 성능이라고 해석하면 안 된다. 외부 요청 시간 초과는 오답으로 채점하지 않고 미평가로 구분한다.

## 실제 확인한 현재 파이프라인

| 단계 | 파일·함수 / 실제 동작 |
|---|---|
| 업로드 | backend/app/main.py:upload_document → service.py:ingest_document. Swagger/API 업로드이며 현재 frontend/app/page.tsx에는 업로드 폼이 없다. |
| 중복 | service.py:_read_upload에서 확장자·서명·크기 검증 후 SHA-256. 동일 file_hash이면 기존 문서 반환, 재파싱하지 않는다. |
| 파싱/OCR | pdf_pipeline.py:extract_pdf → PyMuPDF page.get_text("text"). native 글자수 80 미만만 pdf2image/Poppler → Tesseract kor+eng. 더 긴 텍스트를 채택한다. 80자 이상인 혼합/깨진 페이지의 품질 판단은 없다. |
| 페이지/청크 | service.py:ingest_document → chunking.py:split_page. 페이지별 최대 1,200자, 겹침 없음, 페이지를 넘지 않는 char_start/end. section_title은 None. 표 구조를 DB에 저장하는 파서는 없다. |
| 임베딩 | main.py:create_embeddings → embedding_service.py:embed_document → embeddings.py:OllamaEmbeddingProvider.embed. 업로드와 별도 API, batch=100, bge-m3 1024차원. 같은 모델·차원의 기존 벡터는 건너뜀. |
| BM25 | search.py:hybrid_search에서 필터된 모든 청크를 읽고 매 요청 BM25Okapi 재구성. 영속 BM25 인덱스 적재 단계는 없다. 한글 연속 문자열 토크나이저로 조사·붙여쓰기 대응이 제한적이다. |
| 벡터/RRF | 같은 provider/model/dimension의 pgvector cosine 거리. BM25·벡터 각각 max(4k,20)개, reciprocal_rank_fusion 상수60. 공개 검색은 기업·종목·기관·문서종류·발행일 필터. 발행일은 실적 연도가 아니다. 공개 API에는 document_id 필터 필드가 없고 내부 SearchFilters에는 있다. |
| 분석 후보 | analysis_retrieval.py:collect_analysis_evidence. 선택 document_id로 3개 질의, 각 15~20개 검색. 분석 경로는 PostgreSQL 인덱스 스캔을 꺼 exact cosine 사용. document_candidates.py:document_candidates가 문서 전체 페이지를 훑어 문장·제한적 표 후보를 추가한다. 따라서 top-k 검색 밖 근거도 후보가 된다. |
| 사실/분류 | evidence_facts.py:economic_facts → 지표·방향·비교대상·전망 여부를 규칙 추출. 중립 사실은 최종 positive/negative 후보에서 빠진다. 표도 모든 지표/수치 질문을 지원하지 않으며 일부 영업이익·매출 행 구조만 검증한다. |
| 생성/검증 | analysis_service.py:analyze_document → _prompt → generation.py provider.generate. 모델은 후보 ID를 선택한다. validated_items와 grounded_card가 제목·설명을 규칙 기반 카드로 복원하고, 요약도 카드 제목으로 다시 만든다. 자유형 숫자·복수 페이지 계산 답변 API가 아니다. |
| 저장 | analysis_runs에 상태·provider/model·JSON·진단 trace 저장. evidence/answer_items 관계 테이블과 published 상태 DB 제약은 현재 구현돼 있지 않다. 이번 변경은 기존 JSON 구조를 유지한다. |
| 인용/UI | source_chunk_ids → 저장 청크 → 해당 문서 Page의 실제 substring을 검증. citation_display.py는 표시 텍스트/제한적 표 설명을 구성. frontend/app/analysis-view.tsx에서 /file?page_number=N#page=N 원본 링크 제공. |

페이지 번호는 PDF **물리적 순번(index+1)** 이다. PDF의 인쇄 쪽수와 page label은 읽지 않으며 UI는 같은 번호를 `PDF N페이지`로 표시한다. /file의 page_number는 범위를 검증할 뿐 PDF를 잘라 반환하지 않는다. 브라우저의 #page=N 이동 지원 여부는 별도 UI 확인 사항이다. 원본 링크의 번호가 맞다는 것과 OCR 인용 내용이 원본과 같다는 것은 다른 검증이다.

문서 설명의 최대 320자 인용은 모든 분석 경로에 적용되지 않아 README를 정정했다. UI의 gemma3 필수 안내는 Gemini 기본 경로와 맞지 않는 기존 문구로 남아 있다.

## 재현된 실패 사례와 원인

1. **근거 부족 시 답변 강행**: 기존 삼성전자 2030 탄소배출 질문에 파운드리 가동률 상승을 응답. 목표라는 질의어가 목표주가에 부분 일치하고 연도 검증이 없었다. 원문 인용은 존재하지만 질문의 주장을 뒷받침하지 않는다.
2. **실제/전망 혼동**: LG 2Q26 실제 실적 문장을 인용하면서 제목은 `영업이익 증가 전망`. 규칙이 `시장 기대를 상회했다`의 기대를 전망 표현으로 오인했다.
3. **원문 추출 오류**: DB손해보험 p1 원문 4,993억원이 200dpi OCR에서 4,999억워. LG p1 2Q26이 2026, DB p2 1Q26이 1026. 페이지가 검색돼도 정답 수치/기간이 보존되지 않는다.
4. **청크 분절·검색 실패**: POSCO p2 철강 424십억원 행이 top5에 없는데 같은 페이지의 매출 표와 영업이익률 표가 있어 page recall은 성공으로 보인다. LG p2 CNS 3.42조원 질문은 p2 자체가 top5에서 빠진다.
5. **관련 없는 청크 상위 노출**: POSCO 영업이익 전망 질문에서 p8 투자등급/면책이 RRF 2위(BM25 3위, vector 4위). 검색 API는 분석의 boilerplate 후보 필터와 별개다.
6. **근거는 찾았으나 답변 오류/누락**: 삼성전자 실적 하회 근거가 후보와 생성 선택에 있는데 최종 검증에서 제거돼 보류된다. POSCO 전망 수치를 물어도 성수기 판매량 증가만 응답한다. 질문에 답한 것으로 채점하지 않는다.
7. **인용 연결 취약점(변조 회귀 실험)**: 페이지 문자열과 청크 content/offset/page_number가 틀려도 전체 페이지 후보가 답변에 사용될 수 있었다. 실제 DB 손상을 발견했다는 뜻은 아니며, 테스트에서 재현한 무결성 결함이다.

## 변경한 파일과 이유

| 파일 | 이번 변경 |
|---|---|
| backend/app/evidence_integrity.py | 청크의 문서·페이지·번호·범위·원문 일치와 인용 전체 범위의 청크 커버리지 공통 검사. |
| backend/app/document_candidates.py | 유효 청크만 오프셋순 정렬, 비공백 누락이 있는 전체 페이지 문장을 후보로 인증하지 않음. 기존 파일에 보강. |
| backend/app/search.py | 원문과 불일치한 청크를 BM25/RRF 후보에서 제거, 벡터 결과도 동일 유효 후보로 제한. |
| backend/app/analysis_service.py | 생성 후 source_chunk_ids를 DB에서 다시 읽어 최종 인용 검증; 불일치 502/failed. 전체 보류 summary를 정확히 `확인할 수 없습니다`로 통일. |
| backend/app/analysis_retrieval.py | 원문 후보에서 확인할 수 없는 명시 연도 질문을 생성 전에 보류. 지표·주제 의미 전체를 증명하는 검사는 아니므로 한계를 남김. |
| backend/app/evidence_facts.py | 성장의 목적어를 앞 지표의 증가로 오인하는 오류와 시장 기대 비교를 전망으로 오인하는 오류 수정. 기존 파일에 보강. |
| backend/app/pdf_pipeline.py, docker-compose.yml, .env.example | 새 OCR 적재 기본 300dpi 및 OCR_DPI 설정. 기존 문서/벡터 재작성 없음. |
| backend/app/generation.py | google-genai 2.18.1 Interactions 내부 retry 기본 3회를 1회로 제한. attempts=0도 SDK가 1로 보정하므로 0회라고 주장하지 않음. 서비스 외부 loop와 합쳐진 wall-clock 상한은 별도 과제. |
| backend/tests/test_evidence_integrity.py, test_analysis.py | 원문 변조·연도 누락·실제/전망·생성 중 원문 변경 회귀 검사. 기존 테스트의 가짜 오프셋을 실제 substring 위치로 수정. |
| scripts/audit_rag.py, scripts/audit_ocr.py, evals/audit-*.json | 고정 질문, 실제 API 원시 응답/검색순위/페이지/시간, 동일 PDF OCR 비교. 의미 평가는 자동 키워드 통과로 꾸미지 않고 수동 판정. |
| README.md, api-contract.md, acceptance.md, qa-rules.md | 실제 호출 구조, 보류/인용 검증/평가 조건과 한계 문서화. |

공개 API 필드, DB 스키마와 1024차원 벡터, BM25·cosine·RRF는 유지했다. 재정렬 모델, 새 DB, 에이전트 시스템은 추가하지 않았다.

## 변경 전후 평가 결과

아래 결과는 소표본 진단이며 일반적인 서비스 정확도나 모델 성능이 아니다. top5 페이지 recall과 정답 근거 검색을 별도로 평가한다. 답변 오류에는 누락/오답을 포함하지만 HTTP 오류는 미평가로 남긴다. 인용 없음은 인용 정확도 100%가 아니라 해당 없음이다.

정답 근거를 **필요한 사실 묶음**으로 정의했다. 수치·단위·기간이 필요한 묶음은 세 요소가 모두 보존돼야 hit다. LG 기간 비교는 분기/연간 2묶음, DB 표 조회는 두 분기 2묶음, POSCO 결합은 개선 원인/철강 수치 2묶음이다. 부분 복원은 그 묶음의 성공으로 세지 않았다. 판정 사유·원시 파일 해시는 [audit-reviewed.json](audit-reviewed.json)에 기록했다.

| 구분 | 기존 삼성전자 | 추가 3개 기업 |
|---|---:|---:|
| 정답 근거 recall@5 | 2/2 → 2/2 | 4/10 → 4/10 |
| 답변 정답 (양쪽 평가 가능한 동일 문항) | 0/2 → 1/2 | 1/6 → 2/6 |
| 답변 평가 불가 (HTTP 오류/timeout) | 1 → 1 | 2 → 1 |

전체 정답 근거 recall@5는 **6/12 → 6/12**, 기대 페이지를 모두 검색한 문항은 **8/9 → 8/9**다. top5 청크 ID와 순위는 11문항 모두 전후 동일했고 벡터 검색도 모두 사용됐다. 페이지별 엄격 recall과 의미상 근거 recall을 혼합하지 않았다.

근거 없는 두 질문의 보류는 **1/2 → 2/2**, 정확한 보류 문구는 **0/2 → 2/2**. 양쪽 응답을 평가 가능한 동일 8문항의 정답은 **1/8 → 3/8**다. 변경 전 3개, 변경 후 2개 생성 실행 실패는 정답/오답 분모에서 제외했다. DB 스캔 문항은 변경 후 응답이 왔지만 틀린 OCR 인용/수치 누락으로 실패했다. 이 표본으로 일반 정확도를 주장하지 않는다.

출력된 인용의 물리적 페이지 존재·DB 문자열 오프셋 일치는 **4/4 → 4/4**였다. 원본에서 실제 표시 주장을 뒷받침하는지 검토하면 **3/4 → 4/4**다(이전 LG의 전망 표현은 미지지). 그러나 이것은 질문 관련성이나 인용 속 모든 OCR 숫자의 정확성을 뜻하지 않는다. 이후 DB손해보험 인용의 4,999억워/149%는 원문과 다르고, POSCO 인용은 핵심 판매량 증가만 식별되며 다른 문구는 깨져 있다. 실제 질문 전체에 답했는지는 별도 정답 지표에서 실패로 처리했다. 잘못된 물리 페이지를 붙인 실행 사례는 없었으며, 원문을 변조한 회귀 실험에서 연결 결함을 재현했다.

| 질문 ID / 종류 | 정답 페이지 | 근거 recall@5 전→후 | 답변 전→후 | 응답초 전→후 | 실패/비고 |
|---|---|---:|---|---:|---|
| old-miss / 사실 조회 | 1 | 1/1 → 동일 | 미통과 → 미통과 | 33.753 → 32.787 | 근거는 찾았으나 답변 오류 |
| old-risk / 사실 조회 | 1 | 1/1 → 동일 | 미평가 → 미평가 | 110.061 → 99.647 | 실행 실패 |
| old-none / 근거 없음 | 없음 | 해당 없음 | 미통과 → 정답 | 33.598 → 0.276 | 근거 부족 시 답변 강행 |
| lg-fact / 사실 조회 | 1 | 1/1 → 동일 | 미통과 → 정답 | 36.151 → 83.824 | 근거는 찾았으나 답변 오류 |
| lg-period / 수치·단위·기간 | 1 | 1/2 → 동일 | 미평가 → 미평가 | 98.080 → 94.761 | 원문 추출 오류 / 청크 누락 / 실행 실패 |
| lg-table / 표 조회 | 2 | 0/1 → 동일 | 미통과 → 미통과 | 0.975 → 1.237 | 검색 실패 |
| db-scan / 스캔 문서 | 1 | 0/1 → 동일 | 미평가 → 미통과 | 110.111 → 38.772 | 원문 추출 오류 |
| db-table / 표 조회 | 2 | 1/2 → 동일 | 미통과 → 미통과 | 0.495 → 0.502 | 원문 추출 오류 / 근거는 찾았으나 답변 오류 |
| posco-multi / 여러 페이지 결합 | 1,2 | 0/2 → 동일 | 미통과 → 미통과 | 32.862 → 40.832 | 원문 추출 오류 / 검색 실패 / 근거는 찾았으나 답변 오류 |
| posco-forecast / 수치·단위·기간 | 1 | 1/1 → 동일 | 미통과 → 미통과 | 34.520 → 35.918 | 관련 없는 청크 상위 노출 / 근거는 찾았으나 답변 오류 |
| db-none / 근거 없음 | 없음 | 해당 없음 | 정답 → 정답 | 22.368 → 0.464 | 해당 없음 |

LG 실제 실적 질문의 동등한 정답 근거는 p3에서도 시각 확인했다. 표의 최초 정답 페이지 p1을 그대로 유지했으며, 인용 p3을 잘못된 인용으로 처리하지 않았다.

검색 시간 중앙값은 1.913 → 1.829초. HTTP 성공 응답의 분석 시간 중앙값은 33.230 → 32.787초이나 표본 구성과 장비 부하가 달라 성능 개선 근거로 보지 않는다. LG 사실 질문은 36.151 → 83.824초로 느려졌다. 반복 실험/p95는 실시하지 않았다.

원시 결과: [변경 전](results/audit/before-local.json), [변경 후](results/audit/after-local.json), [OCR 비교](results/audit/ocr.json). 기존 17문항 전체를 실행했다고 주장하지 않는다. Gemini 실패 관찰, 초기 임시 서버 설정 충돌(500)과 중간 실행 결과는 최종 비교에서 제외했다.

검증: `./scripts/check.sh` 완료 — backend **184 통과 / SDK 부재로 1 skip**, frontend **7 통과**, lint 및 production build 성공. Docker 설치 SDK에서 재시도 기본3/설정1을 직접 확인했다. 같은 추가 회귀 8사례를 시작 시 소스 스냅샷에 적용하면 6실패/2통과, 수정 후 해당 사례는 모두 통과했다. 이 회귀 비율은 금융 문서 정확도가 아니다.


## 청크 크기 분리 실험

실제 저장된 p2 텍스트에 split_page만 적용하고 DB/임베딩은 바꾸지 않았다.

| 문서·행 | 최대600자 | 최대1200자(현재) | 최대2000자 |
|---|---|---|---|
| POSCO 철강 영업이익 424 | 9청크, 행 청크에 기간·단위 없음 | 5청크, 기간·단위 없음 | 3청크, 기간·단위 없음 |
| DB손해보험 보험손익 227/282 | 4청크, 기간·단위 있음 | 2청크, 기간·단위 있음 | 2청크, 기간·단위 있음 |

단순 길이 확대만으로 POSCO 표 헤더와 행을 함께 보존하지 못했다. DB 표는 길이보다 OCR의 1Q26 오독과 중립 표 후보 제거가 문제다. 이 실험은 chunk coverage 비교이며 새 벡터 생성/RRF ablation이 아니다. 결과: evals/results/audit/chunk-sizes.json.

## OCR 별도 비교

같은 원본 PDF 3개 p1을 Tesseract 5.5.0 kor+eng으로 비교했다. DB손해보험은 `4,999억워 → 4,993억원`으로 교정됐고 컨센서스/13.8%가 보존됐다. LG의 `2Q26 → 2026` 오류는 두 해상도에서 그대로다. POSCO는 YoY 글자가 좋아졌지만 `영업이익 → 영언이익`으로 일부 글자가 악화됐다. 따라서 300dpi를 전반적 정확도 개선으로 보고하지 않는다. 이 비교는 재파싱 단계 실험이며, 기존 DB를 유지한 API 전후 평가의 OCR 개선으로 합산하지 않는다.

첫 200dpi 실행에는 130.744초 지연이 있었고 다른 실행들은 수 초였다. 모델 실행/컨테이너 빌드가 같은 장비에서 겹친 단회 관찰이므로 해상도별 속도 비교나 p95로 해석하지 않는다. 원시 결과는 evals/results/audit/ocr.json.

OCR 기본값 변경 후 같은 파일을 재업로드해도 SHA-256 중복 경로가 기존 문서를 반환하므로 재OCR되지 않는다. 기존 인용 오프셋을 보존하는 명시적인 버전형 재처리 경로가 아직 없어 이번 작업에서 기존 금융 문서를 삭제·재적재하지 않았다.

## 여전히 실패하는 사례와 다음 우선순위

1. 표 헤더·행·단위·분기를 함께 보존하는 추출/청킹이 최우선이다. LG CNS, DB 보험손익, POSCO 철강 실적 행을 대상으로 페이지 이미지와 OCR 좌표를 대조하고, 수치 복원은 확인된 원문에만 허용해야 한다. 80자 길이 기준은 혼합 페이지의 누락을 발견하지 못한다.
2. 일반 숫자/기간 질의를 positive/negative 규칙 카드로만 답하는 현재 계약의 한계가 크다. 중립 사실을 억지로 호재/악재로 만들지 말고, 기존 응답 형식 내에서 정확히 답할 수 없는 경우를 명확히 보류해야 한다. 자유형 QA 기능 확장은 별도 결정이다.
3. 연도가 원문 어딘가에 있는 것만으로 주제·기간이 정합하지는 않다. 앞으로 질문의 지표·기간·대상과 선택 근거를 함께 확인하는 평가를 확장해야 한다. 이번 연도 검사는 문서 밖 미래 연도 답변 강행만 차단한다.
4. 검색 단계에서 면책/투자등급의 상위 노출과 붙여쓰기 한국어 BM25를 개선할 여지가 있다. 원문과 청크 구조 문제를 먼저 고친 다음 고정 질문으로 재정렬 필요성을 다시 측정한다.
5. 완전 미사용 기업 2~3개를 확보해 사전 고정 질문/정답과 별도 검증한다. 이번 추가 기업은 기존 DB 업로드 이력이 있어 엄격한 일반화 검증이 아니다.
6. Gemini 429 해소 후 같은 질문을 기본 경로로 재측정한다. SDK 내부·외부 재시도와 전체 요청 deadline, 모델 생성 timeout 및 실패 run 상태 정리도 별도 우선순위다.

## 재현 명령

```bash
./scripts/check.sh
docker compose up -d --build
.venv/bin/python scripts/audit_rag.py --output evals/results/audit/current.json
# 외부 생성이 막힐 때 검색만 측정
.venv/bin/python scripts/audit_rag.py --retrieval-only --output evals/results/audit/search.json
# 기본 Gemini 설정을 바꾸지 않는 로컬 모델 비교 서버
docker compose run -d --no-deps --name stock-brief-audit-repro -p 8003:8000 \
  -e ANALYSIS_LLM_PROVIDER=ollama -e ANALYSIS_LLM_FALLBACK_PROVIDER=none \
  -e OLLAMA_GENERATION_TIMEOUT_SECONDS=90 backend
.venv/bin/python scripts/audit_rag.py --api-base-url http://localhost:8003 \
  --timeout 110 --output evals/results/audit/local.json
# 원본을 읽기 전용 마운트하고 DB를 건드리지 않는 OCR 비교
docker compose run --rm --no-deps -v "$PWD:/audit:ro" --entrypoint python backend \
  /audit/scripts/audit_ocr.py --pdf-dir /audit/holdout-v1 \
  --manifest /audit/evals/audit-documents.json > evals/results/audit/ocr.json
```

조건: Docker Desktop, 기존 PostgreSQL/uploads volume, 해당 메타데이터의 원본 문서와 완료된 bge-m3 임베딩, 호스트 Ollama bge-m3/gemma3:4b. 평가용 임시 컨테이너는 종료했으며 기본 Docker Compose 서비스는 실행 상태다. 로컬 .venv에는 google-genai가 없어 SDK integration test 1개는 skip되며 실제 Docker 설치 SDK에서 기본3/설정1 매핑을 별도 실행 검증했다. 전체 생성 전후 결과의 provider/model은 각 JSON의 analysis/trace로 확인한다. API 수치 결과와 원문 PDF는 기존 저장소 정책대로 커밋하지 않고 evals/results/에 둔다. 감사 요약과 질문·파일 해시는 버전 관리 가능하다.

## 비교 참고 자료 적용 범위

[Financial-Report-RAG](https://github.com/sieduck/Financial-Report-RAG)의 질문별 평가, [sec-rag-analyst](https://github.com/tkarim45/sec-rag-analyst)의 검색 단계 분리 측정, [agentic-financial-rag](https://github.com/MazkaB/agentic-financial-rag)의 주장·수치 검증 관점, [FinanceBench_RAG](https://github.com/aquib8112/FinanceBench_RAG)의 페이지 검색과 실패 분석을 참고했다. 공개 README의 설계 설명을 비교한 것이며 코드 이식이나 성능 수치 재현은 하지 않았다. 외부 성능 수치를 본 서비스 평가에 사용하지 않았다.

## 후속 단계: retrieval·표·기간 보존 (생성 미호출)

이 절은 앞선 카드/생성 평가 이후의 **별도 변경 전후 비교**다. 이전 절의 이미지 ID, 생성 호출 및 analysis_runs 쓰기는 이전 작업 기록이며 이번 실행에는 해당하지 않는다. 이번 DB 작업은 `SET TRANSACTION READ ONLY`에서 SELECT만 실행했다. Gemini/Ollama 생성과 기존 17문항 CLI는 실행하지 않았다. bge-m3 질의 임베딩만 호출했다.

분모는 12문항이 아니라 **11개 질문 중 9개 답변 가능한 질문의 12개 정답 근거 단위**다. 근거 없음 2문항의 생성 보류는 재평가하지 않았다. 아래 수치는 주어진 작은 고정 표본의 결과이며 일반 성능이나 새로운 blind holdout 결과가 아니다.

### 누락 6개 분류

추출 누락·훼손 **5개**, 온전한 행/헤더가 있지만 검색 top-5 밖 **1개**, 온전한 정답 span이 top-5에 있으나 검증에서만 탈락 **0개**. 훼손된 텍스트가 top-5에 있는 것은 3번 유형으로 잘못 세지 않았다.

#### lg-period / 연간 전망

- 질문: LG의 2Q26 연결 영업이익과 2026F 연간 영업이익을 단위와 실제·전망을 구분해 알려줘.
- 정답: PDF 물리적 p1 — 2026F 영업이익 1,643십억원
- 페이지·청크/span: 페이지·청크는 존재. p1/p4 수치가 1.643으로 저장되어 원문 1,643과 다르다. p7에는 1,643이 있지만 열 머리글이 20266 등으로 훼손됐다. 온전한 기간·수치 결합 span 없음.
- 실패 단계: 1 — 추출 훼손 (표 헤더 분절도 동반)
- 다음 개선 영역: OCR/파서 → 표 청킹
- 아래 순위는 해당 행 또는 **훼손된 인접 청크**의 순위다. 온전한 정답 span이 없는 경우 그 span 자체의 순위는 N/A다.

| 참조 chunk | 페이지·문자 범위 | BM25 | vector | RRF |
|---|---|---:|---:|---:|
| `596a6390-8c10-4eb5-a147-6084a3e5fb0a` | p1 [0, 1199) | 4 | 9 | 5 |
| `a2d0fddf-24c7-40f8-adb7-b499645d7d4c` | p4 [1197, 2396) | 2 | 2 | 2 |
| `559d613c-fa00-4473-a319-70c12296f425` | p7 [0, 1163) | 9 | 3 | 4 |

변경 전 top-5 (순서대로):

1. p4 `54968648-782e-4567-888e-6b2222d0981c` — BM25 3, vector 1, RRF 1, hybrid_rrf
2. p4 `a2d0fddf-24c7-40f8-adb7-b499645d7d4c` — BM25 2, vector 2, RRF 2, hybrid_rrf
3. p3 `792b9fa0-647d-446d-b2a4-0dfc619593ff` — BM25 1, vector 4, RRF 3, hybrid_rrf
4. p7 `559d613c-fa00-4473-a319-70c12296f425` — BM25 9, vector 3, RRF 4, hybrid_rrf
5. p1 `596a6390-8c10-4eb5-a147-6084a3e5fb0a` — BM25 4, vector 9, RRF 5, hybrid_rrf

변경 후 최종 top-5 (순서대로):

1. p4 `54968648-782e-4567-888e-6b2222d0981c` — BM25 3, vector 1, RRF 1, hybrid_rrf
2. p4 `a2d0fddf-24c7-40f8-adb7-b499645d7d4c` — BM25 2, vector 2, RRF 2, hybrid_rrf
3. p3 `792b9fa0-647d-446d-b2a4-0dfc619593ff` — BM25 1, vector 4, RRF 3, hybrid_rrf
4. p7 `559d613c-fa00-4473-a319-70c12296f425` — BM25 9, vector 3, RRF 4, hybrid_rrf
5. p1 `596a6390-8c10-4eb5-a147-6084a3e5fb0a` — BM25 4, vector 9, RRF 5, hybrid_rrf

#### lg-table / 지분가치

- 질문: 표 1에서 LG CNS 지분가치와 단위를 알려줘.
- 정답: PDF 물리적 p2 — LG CNS 지분가치 3.42조원
- 페이지·청크/span: 페이지·청크 존재, 정답 행은 없음. native_text 287자(청크 284자)만 저장되고 native 길이 80자 기준 때문에 OCR 미실행. CNS와 3.42는 저장 텍스트에 없다. 기존 보고서의 단순 검색 실패 분류를 정정한다.
- 실패 단계: 1 — 추출 누락
- 다음 개선 영역: 혼합 native/시각 페이지 OCR 파서
- 아래 순위는 해당 행 또는 **훼손된 인접 청크**의 순위다. 온전한 정답 span이 없는 경우 그 span 자체의 순위는 N/A다.

| 참조 chunk | 페이지·문자 범위 | BM25 | vector | RRF |
|---|---|---:|---:|---:|
| `e517cb14-7e8a-40d7-a415-70315edc5423` | p2 [0, 284) | 16 | 18 | 19 |

변경 전 top-5 (순서대로):

1. p4 `a2d0fddf-24c7-40f8-adb7-b499645d7d4c` — BM25 1, vector 2, RRF 1, hybrid_rrf
2. p4 `b5aa3283-ebb3-4dc8-ad35-20c39d463e15` — BM25 5, vector 1, RRF 2, hybrid_rrf
3. p4 `54968648-782e-4567-888e-6b2222d0981c` — BM25 2, vector 8, RRF 3, hybrid_rrf
4. p3 `792b9fa0-647d-446d-b2a4-0dfc619593ff` — BM25 3, vector 7, RRF 4, hybrid_rrf
5. p5 `e74527cb-2679-4cd9-a68a-0578c6bd8598` — BM25 8, vector 4, RRF 5, hybrid_rrf

변경 후 최종 top-5 (순서대로):

1. p4 `a2d0fddf-24c7-40f8-adb7-b499645d7d4c` — BM25 1, vector 2, RRF 1, hybrid_rrf
2. p4 `b5aa3283-ebb3-4dc8-ad35-20c39d463e15` — BM25 5, vector 1, RRF 2, hybrid_rrf
3. p4 `54968648-782e-4567-888e-6b2222d0981c` — BM25 2, vector 8, RRF 3, hybrid_rrf
4. p3 `792b9fa0-647d-446d-b2a4-0dfc619593ff` — BM25 3, vector 7, RRF 4, hybrid_rrf
5. p5 `e74527cb-2679-4cd9-a68a-0578c6bd8598` — BM25 8, vector 4, RRF 5, hybrid_rrf

#### db-scan / 순이익 비교

- 질문: DB손해보험의 2분기 순이익 예상치와 컨센서스 수치, 상회율을 알려줘.
- 정답: PDF 물리적 p1 — 2분기 순이익 예상 4,993억원 / 컨센서스 4,386억원 / 13.8% 상회
- 페이지·청크/span: 페이지·청크 존재. 핵심 금액이 4,999억워로 잘못 저장되어 정확한 span 없음. 같은 페이지 top-5를 성공으로 세지 않는다.
- 실패 단계: 1 — OCR 수치 훼손
- 다음 개선 영역: OCR 파서
- 아래 순위는 해당 행 또는 **훼손된 인접 청크**의 순위다. 온전한 정답 span이 없는 경우 그 span 자체의 순위는 N/A다.

| 참조 chunk | 페이지·문자 범위 | BM25 | vector | RRF |
|---|---|---:|---:|---:|
| `5ed15a8d-2759-4ff4-8e2e-9ad47fc61f67` | p1 [0, 1190) | 1 | 4 | 1 |
| `d2858de0-552f-42a4-b953-e996b9b82a51` | p1 [1191, 2374) | 3 | 3 | 2 |

변경 전 top-5 (순서대로):

1. p1 `5ed15a8d-2759-4ff4-8e2e-9ad47fc61f67` — BM25 1, vector 4, RRF 1, hybrid_rrf
2. p1 `d2858de0-552f-42a4-b953-e996b9b82a51` — BM25 3, vector 3, RRF 2, hybrid_rrf
3. p4 `5d6edfd4-56f1-4a1f-b2d3-23527cb6e290` — BM25 2, vector 5, RRF 3, hybrid_rrf
4. p2 `f1b1f5a6-f32f-4108-976c-b50ec876832a` — BM25 8, vector 1, RRF 4, hybrid_rrf
5. p2 `3f1ca407-c192-407a-a7b4-5a1138338103` — BM25 4, vector 7, RRF 5, hybrid_rrf

변경 후 최종 top-5 (순서대로):

1. p1 `5ed15a8d-2759-4ff4-8e2e-9ad47fc61f67` — BM25 1, vector 4, RRF 1, hybrid_rrf
2. p1 `d2858de0-552f-42a4-b953-e996b9b82a51` — BM25 3, vector 3, RRF 2, hybrid_rrf
3. p4 `5d6edfd4-56f1-4a1f-b2d3-23527cb6e290` — BM25 2, vector 5, RRF 3, hybrid_rrf
4. p2 `f1b1f5a6-f32f-4108-976c-b50ec876832a` — BM25 8, vector 1, RRF 4, hybrid_rrf
5. p2 `3f1ca407-c192-407a-a7b4-5a1138338103` — BM25 4, vector 7, RRF 5, hybrid_rrf

#### db-table / 1Q26 보험손익

- 질문: 표 1의 1Q26과 2Q26F 보험손익을 단위와 함께 알려줘.
- 정답: PDF 물리적 p2 — 1Q26 보험손익 227십억원 (2Q26F 282와 구분)
- 페이지·청크/span: 페이지·행 청크 존재. 1Q26 열이 1026으로 저장되어 정확한 기간 연결 불가. 227을 추측해 연결하지 않는다. 별도 2Q26F 단위는 기존 성공 1건으로 유지.
- 실패 단계: 1 — OCR 기간 훼손
- 다음 개선 영역: 표 OCR/열 좌표 파서
- 아래 순위는 해당 행 또는 **훼손된 인접 청크**의 순위다. 온전한 정답 span이 없는 경우 그 span 자체의 순위는 N/A다.

| 참조 chunk | 페이지·문자 범위 | BM25 | vector | RRF |
|---|---|---:|---:|---:|
| `f1b1f5a6-f32f-4108-976c-b50ec876832a` | p2 [0, 1187) | 1 | 1 | 1 |

변경 전 top-5 (순서대로):

1. p2 `f1b1f5a6-f32f-4108-976c-b50ec876832a` — BM25 1, vector 1, RRF 1, hybrid_rrf
2. p2 `3f1ca407-c192-407a-a7b4-5a1138338103` — BM25 2, vector 3, RRF 2, hybrid_rrf
3. p3 `fdb0f5fe-ea3c-49db-8252-debea46cb03f` — BM25 4, vector 5, RRF 3, hybrid_rrf
4. p3 `38b9c614-d982-4868-9e01-abcfaa252aac` — BM25 8, vector 2, RRF 4, hybrid_rrf
5. p3 `a1c78b49-e6cf-4223-8897-312fbeb1040c` — BM25 7, vector 4, RRF 5, hybrid_rrf

변경 후 최종 top-5 (순서대로):

1. p2 `f1b1f5a6-f32f-4108-976c-b50ec876832a` — BM25 1, vector 1, RRF 1, verified_table_conditions
2. p2 `3f1ca407-c192-407a-a7b4-5a1138338103` — BM25 2, vector 3, RRF 2, hybrid_rrf
3. p3 `fdb0f5fe-ea3c-49db-8252-debea46cb03f` — BM25 4, vector 5, RRF 3, hybrid_rrf
4. p3 `38b9c614-d982-4868-9e01-abcfaa252aac` — BM25 8, vector 2, RRF 4, hybrid_rrf
5. p3 `a1c78b49-e6cf-4223-8897-312fbeb1040c` — BM25 7, vector 4, RRF 5, hybrid_rrf

#### posco-multi / 실적 개선 이유

- 질문: 1페이지 철강 부문 실적 개선 이유와 2페이지 표의 2Q26F 철강 영업이익을 함께 알려줘.
- 정답: PDF 물리적 p1 — 판가 상승·성수기 판매량 증가·원화 약세 및 중국 장가항 연결 제외
- 페이지·청크/span: 페이지·청크 존재. 판가/원화 관련 본문과 연결 제외 문맥이 깨져 전체 이유 묶음이 온전히 없다. 일부 이유 문장만 검색된 것을 성공으로 세지 않는다.
- 실패 단계: 1 — OCR 본문 훼손
- 다음 개선 영역: OCR/읽기 순서 파서
- 아래 순위는 해당 행 또는 **훼손된 인접 청크**의 순위다. 온전한 정답 span이 없는 경우 그 span 자체의 순위는 N/A다.

| 참조 chunk | 페이지·문자 범위 | BM25 | vector | RRF |
|---|---|---:|---:|---:|
| `78d9f01d-96c5-4dac-b6c2-c9488d4df852` | p1 [0, 1197) | 3 | 7 | 5 |
| `9e56ae4b-1c1e-4251-bd16-73d9454b5ba4` | p1 [1198, 2393) | 2 | 4 | 2 |

변경 전 top-5 (순서대로):

1. p2 `ac5b3413-7c84-4955-9f15-c488574e4a86` — BM25 1, vector 1, RRF 1, hybrid_rrf
2. p1 `9e56ae4b-1c1e-4251-bd16-73d9454b5ba4` — BM25 2, vector 4, RRF 2, hybrid_rrf
3. p2 `10b711a3-97e5-46d4-a3fe-14ac196f239a` — BM25 6, vector 2, RRF 3, hybrid_rrf
4. p3 `d573a84c-013b-44e4-a8ad-94ef5ceeb69f` — BM25 4, vector 5, RRF 4, hybrid_rrf
5. p1 `78d9f01d-96c5-4dac-b6c2-c9488d4df852` — BM25 3, vector 7, RRF 5, hybrid_rrf

변경 후 최종 top-5 (순서대로):

1. p2 `1a262113-4088-49f3-ba3b-3dacb1c083ff` — BM25 7, vector 3, RRF 6, verified_table_conditions
2. p2 `ac5b3413-7c84-4955-9f15-c488574e4a86` — BM25 1, vector 1, RRF 1, hybrid_rrf
3. p1 `9e56ae4b-1c1e-4251-bd16-73d9454b5ba4` — BM25 2, vector 4, RRF 2, hybrid_rrf
4. p2 `10b711a3-97e5-46d4-a3fe-14ac196f239a` — BM25 6, vector 2, RRF 3, hybrid_rrf
5. p3 `d573a84c-013b-44e4-a8ad-94ef5ceeb69f` — BM25 4, vector 5, RRF 4, hybrid_rrf

#### posco-multi / 철강 영업이익

- 질문: 1페이지 철강 부문 실적 개선 이유와 2페이지 표의 2Q26F 철강 영업이익을 함께 알려줘.
- 정답: PDF 물리적 p2 — 2Q26F 철강 영업이익 424십억원, 전망
- 페이지·청크/span: 행과 헤더가 같은 페이지의 다른 청크에 존재. 행 청크는 BM25 7위, vector 3위, RRF 6위. 청크 단독에는 기간·단위 없음. 새 후보는 행+부모 지표+기간 헤더+단위 각각의 저장 span을 검증한다.
- 실패 단계: 2 — 검색 top-5 누락 (부모 헤더 분절 동반)
- 다음 개선 영역: 같은 페이지 표 parent context + 조건 재정렬
- 아래 순위는 해당 행 또는 **훼손된 인접 청크**의 순위다. 온전한 정답 span이 없는 경우 그 span 자체의 순위는 N/A다.

| 참조 chunk | 페이지·문자 범위 | BM25 | vector | RRF |
|---|---|---:|---:|---:|
| `1a262113-4088-49f3-ba3b-3dacb1c083ff` | p2 [2403, 3592) | 7 | 3 | 6 |

변경 전 top-5 (순서대로):

1. p2 `ac5b3413-7c84-4955-9f15-c488574e4a86` — BM25 1, vector 1, RRF 1, hybrid_rrf
2. p1 `9e56ae4b-1c1e-4251-bd16-73d9454b5ba4` — BM25 2, vector 4, RRF 2, hybrid_rrf
3. p2 `10b711a3-97e5-46d4-a3fe-14ac196f239a` — BM25 6, vector 2, RRF 3, hybrid_rrf
4. p3 `d573a84c-013b-44e4-a8ad-94ef5ceeb69f` — BM25 4, vector 5, RRF 4, hybrid_rrf
5. p1 `78d9f01d-96c5-4dac-b6c2-c9488d4df852` — BM25 3, vector 7, RRF 5, hybrid_rrf

변경 후 최종 top-5 (순서대로):

1. p2 `1a262113-4088-49f3-ba3b-3dacb1c083ff` — BM25 7, vector 3, RRF 6, verified_table_conditions
2. p2 `ac5b3413-7c84-4955-9f15-c488574e4a86` — BM25 1, vector 1, RRF 1, hybrid_rrf
3. p1 `9e56ae4b-1c1e-4251-bd16-73d9454b5ba4` — BM25 2, vector 4, RRF 2, hybrid_rrf
4. p2 `10b711a3-97e5-46d4-a3fe-14ac196f239a` — BM25 6, vector 2, RRF 3, hybrid_rrf
5. p3 `d573a84c-013b-44e4-a8ad-94ef5ceeb69f` — BM25 4, vector 5, RRF 4, hybrid_rrf

### 변경과 측정

`table_evidence.extract_page_table_facts`는 표의 행 이름·부모 지표·열 이름·기간·단위·원문 값·물리적 페이지와 각각의 정확한 원문 범위를 보존한다. 표 제목의 고유 문자열이나 기업명은 조건에 사용하지 않는다. 행과 열 개수가 다르거나 기간이 손상됐으면 그 셀은 후보를 만들지 않는다. F/E는 전망, A는 실제, P는 잠정, 접미사 없는 기간은 unspecified로 남긴다. 현재 날짜로 실적 여부를 추정하지 않는다. 일반 문장을 표로 만들지 않는다. 시장 기대치/전년 대비 등 문장 내 기준은 `evidence_spans.temporal_context`의 원문 범위로 연결한다. 비교 열의 기간이나 표 병합 관계가 불명확하면 인증하지 않으며 기존 PDF fallback을 유지한다.

`verified_table_candidates`가 문서 필터 안의 같은 페이지에서 헤더·단위·부모 지표·행을 연결한다. 모든 조각이 현재 page text와 일치하고 저장 청크로 덮이는지 검사한다. 질문에 사업부 행이 있으면 전체 합계 행을 대신 올리지 않는다. row+metric+period가 모두 맞는 표 후보만 RRF 뒤에 승격한다. 별도 모델 reranker, top-k/후보 수/RRF 가중치 변경은 없다(top5, 각 검색 후보20, RRF k60). 일반 청크의 상대 순위는 유지한다. 검색 quote는 기존 chunk 호환성을 유지하고 `table_evidence[].quote`는 실제 한 행이며 헤더는 별도 source_spans다. 이 메타데이터를 곧바로 카드/최종 답변으로 발행하지 않는다. 기존 evidence·OCR 품질·투자 표현 검증 및 PDF 링크는 유지한다.

| 자료 | 변경 전 recall@5 | 변경 후 recall@5 |
|---|---:|---:|
| 기존 삼성전자 | 2/2 | 2/2 |
| 추가 3기업 보고서 | 4/10 | 5/10 |
| 합계 | **6/12 (50.0%)** | **7/12 (58.3%)** |

성공으로 유지한 6개 단위는 이전 원본 대조 판정과 이번 before/after top-5의 `(chunk_id, quote)`가 동일함을 재확인했다. 신규 성공은 p2 철강 424 행과 기간·단위·지표 연결을 원문 대조한 1건뿐이다. 해당 행 RRF 6위 → 최종 1위. 나머지 5개는 여전히 실패. 기존 성공 단위의 회귀는 없지만, POSCO 여러 페이지 질문의 일부 이유가 있는 p1 첫 청크는 5위에서 top-5 밖으로 밀렸다. 그 이유 묶음은 원래도 실패이므로 집계 손실은 없지만 **상위 후보 다양성 손실**로 남긴다. 질문 전체 답변 성공이나 주장 인용 정확도 상승으로 확대 해석하지 않는다. 생성 정확도·보류율은 이번 미측정.

| 질문 | 검색 시간 전(초) | 후(초) |
|---|---:|---:|
| old-miss | 1.6955 | 1.6695 |
| old-risk | 0.0611 | 0.0507 |
| old-none | 0.0515 | 0.0483 |
| lg-fact | 0.0626 | 0.0538 |
| lg-period | 0.0759 | 0.0618 |
| lg-table | 0.0619 | 0.0549 |
| db-scan | 0.0472 | 0.0445 |
| db-table | 0.0476 | 0.0443 |
| posco-multi | 0.0644 | 0.0661 |
| posco-forecast | 0.0618 | 0.0608 |
| db-none | 0.049 | 0.0495 |

단일 실행이며 캐시/부하 통제를 하지 않아 속도 개선 주장에 사용하지 않는다.

### 비활성 300dpi 재처리 버전

`stage_reprocessing.py`로 원본 3개 문서 전체를 강제 300dpi OCR하여 **DB 외부의 비활성 revision JSON**에 저장했다. raw SHA-256, 파서 코드 해시·버전, Tesseract/PyMuPDF 버전, 각 페이지·청크·table_fact·embedding 슬롯의 processing version을 남겼다. native_text와 OCR 모두 보존한다. 기존 DB 활성 버전·PDF·벡터는 그대로다. 새 embedding은 not_created이며 activation_eligible=false다. 현재 DB는 revision/active 포인터 스키마를 지원하지 않으므로 이번에 그 마이그레이션이나 활성화 경로를 구현·적용한 것은 아니다. 검증 전 전환을 막기 위해 스테이징 CLI에는 활성화/삭제 기능이 없다.

| 문서 | chunk 전→스테이징 | table_fact 셀 전→스테이징 | OCR 선택 페이지 전→스테이징 |
|---|---:|---:|---:|
| DB손해보험 | 11 → 12 | 85 → 96 | 3 → 4 |
| POSCO홀딩스 | 27 → 27 | 110 → 92 | 7 → 8 |
| LG | 21 → 26 | 0 → 0 | 5 → 9 |

전 table_fact 수는 기존 DB에 저장된 테이블 행 수가 아니라, **동일한 새 파서**를 기존 final_text에 적용한 셀 개수다. OCR 시도는 각 문서 모든 페이지(4/8/9)에서 수행했다. POSCO table_fact 수는 오히려 감소했으므로 전체 재처리 성공으로 판단하지 않는다.

300dpi 후보에서 DB손해보험 4,993/4,386/13.8 문장이 복구되고 LG p2 CNS 3.42가 나타났지만, DB p2 1Q26은 여전히 1026이다. LG 표 구조는 자동 인증하지 못했다. 새 버전은 아직 원문·청크·표 전체 검토와 새 임베딩이 없으므로 **재처리 버전 recall@5는 미측정**이다. 현재 활성 데이터의 6→7을 OCR 재처리 효과로 주장하지 않는다.

### 재현 명령과 조건

기존 Compose DB, 호스트 Ollama bge-m3, 원본 PDF, Docker 이미지의 Tesseract kor+eng/Poppler가 필요하다. 아래 실행은 생성 모델을 사용하지 않는다. 저장 경로는 덮어쓰기보다 실행별 새 디렉터리 사용을 권장한다.

```sh
mkdir -p evals/results/retrieval
docker compose run --rm -T --no-deps -v "$PWD:/workspace:ro" --entrypoint python backend /workspace/scripts/audit_retrieval.py --baseline > evals/results/retrieval/before.json
docker compose run --rm -T --no-deps -v "$PWD:/workspace:ro" --entrypoint python backend /workspace/scripts/audit_retrieval.py > evals/results/retrieval/after.json
docker compose run --rm -T --no-deps -v "$PWD:/workspace:ro" --entrypoint python backend /workspace/scripts/stage_reprocessing.py --pdf-dir /workspace/holdout-v1 --manifest /workspace/evals/audit-documents.json > evals/results/retrieval/staged-ocr300.json
./scripts/check.sh
docker compose ps
curl --fail http://localhost:8001/health
curl --fail -o /dev/null http://localhost:3000
git diff --check
```

검색 CLI는 생성/analysis endpoint를 import하거나 호출하지 않으며 트랜잭션을 READ ONLY로 열고 rollback한다. trace의 vector 전체 순위는 같은 query embedding·저장 벡터의 exact cosine 정렬이며, 실제 후보는 pgvector 검색 결과다. RRF 순위 null은 해당 후보20 합집합 밖이라는 뜻이다. stdout JSON에 전체 순위와 최종 후보, 원문 span, 시간을 남긴다. 개인정보/원문·벡터 포함 실행 산출물은 evals/results/ 아래 Git 제외다. 원본 PDF는 .gitignore로 제외했다.

### 남은 우선순위

1. native 글자 수만으로 혼합 페이지 OCR을 건너뛰는 문제와 표 열 좌표/읽기 순서를 먼저 개선하고 300dpi의 손실도 검토한다.
2. 비활성 revision을 원본 PDF로 검증한 뒤, 별도 DB 버전 스키마·활성 포인터·이전 버전 보존·원자적 전환을 구현해야 한다. 이번 실제 DB 읽기 전용 제약 아래서는 적용하지 않았다.
3. 중립 수치 질문이 현재 카드 생성 구조에서 제외되는 문제는 후속 작업이다. 이번에는 polarity/card 규칙을 추가하지 않았다.

### 최종 검증 결과

- `./scripts/check.sh`: backend **196 passed, 1 skipped**(로컬 google-genai 미설치로 SDK 관련 테스트 1개 건너뜀), frontend **7 passed**, lint/production build 통과. 기존 안전성·삼성전자 회귀 테스트 포함.
- `docker compose ps`: PostgreSQL/backend healthy. backend `/health` 200, frontend HTTP 200. 기존 서비스는 재배포하지 않았으며, 변경된 검색 코드는 프로젝트를 읽기 전용으로 마운트한 일회성 Compose backend 컨테이너에서 실제 DB와 통합 평가했다.
- `git diff --check`: 통과. 생성 모델과 기존 17문항 CLI 호출 없음.
- 문서 10개, 페이지 75개, 청크 231개. 시작 스냅샷과 종료 READ ONLY 조회의 정렬 JSON SHA-256 동일(청크 해시에 embedding 포함):
  - documents `035046f0b38bbb8cf91fdf6b83cee1669c18c61bb7ba81986500a4d2b67db3a1`
  - pages `1cf7866151671415c87cc90b8a439c48969ebdc7a95611ba289fc041179cb575`
  - chunks `51e3390752e5fe0538f2e7364f6661a6d5250a5ae3d54c27f0b8b9ecbfe41eab`
- `.venv/bin/python scripts/verify_retrieval_review.py`: 저장 산출물 해시·기존 성공 후보 원문 유지·신규 표 근거 판정 연결 확인, **6/12 → 7/12**. 이 명령은 수동 원문 판정의 재현성을 확인하는 것이며 독립적인 의미 채점기가 아니다. CLI 재실행으로 산출물 해시가 바뀌면 새 원문 판정 없이 승인하지 않는다.

이번 단계 변경 파일: `backend/app/search.py`, `table_evidence.py`, `analysis_retrieval.py`, `schemas.py`, `pdf_pipeline.py`; `backend/tests/test_table_evidence.py`, `test_pipeline.py`; `scripts/audit_retrieval.py`, `stage_reprocessing.py`, `verify_retrieval_review.py`; `evals/audit-report.md`, `retrieval-reviewed.json`; `api-contract.md`, `acceptance.md`, `qa-rules.md`, `.gitignore`. 다른 변경 파일은 작업 시작 시 이미 존재한 변경을 보존한 것이다.

## 신규 적재: 혼합 페이지 감지·좌표 표 복원 (2026-09-23)

이 절은 앞선 retrieval 개선/강제 300dpi staging과 별개다. **실제 DB에 새 PDF를 업로드하지 않았고 기존 문서·벡터·분석 결과도 재처리하지 않았다.** 실제 원본 3개 보고서(21페이지)는 DB 없는 비활성 파서로만 비교했다. 신규 업로드 API 연결은 격리된 SQLite fixture와 가짜 임베딩 provider로 검사했다. Gemini/Ollama 생성 호출과 기존 17문항 CLI 실행은 없다.

### 1. 변경 전후 경로와 적용 파일

변경 전: `service.ingest_document → pdf_pipeline.extract_pdf → native < 80자이면 OCR → 더 긴 native/OCR 문자열 전체 선택 → split_page(1200) → Page/Chunk 저장`. 좌표·선택 이유·표 사실을 저장하지 않았다.

변경 후: `extract_pdf → page_layout.native_observation → 선택적 300dpi OCR(word box/confidence) → select_sources → layout_tables.extract_layout_facts / numeric_evidence.extract_numeric_evidence → 기존 split_page → Page/Chunk + PageExtraction 저장`. 임베딩은 기존 chunk에 같은 bge-m3 1024차원으로 생성되며 page FK를 통해 파서 provenance와 연결된다. 청크 크기/RRF/임베딩 모델은 변경하지 않았다.

- `backend/app/pdf_pipeline.py`, 신규 `page_layout.py`: 렌더링/native 공간 검사, OCR 좌표, native 본문 보존·미포함 OCR 보완, DPI/version/선택 이유 저장. CropBox와 회전 전 PDF point 좌표를 일치시킨다.
- 신규 `layout_tables.py`: 좌표 열·행·부모 지표·단위 연결. 신규 `numeric_evidence.py`: 일반 본문 수치를 표와 분리해 literal span으로 보존.
- `models.py`, `service.py`, 신규 `alembic/versions/20260922_0005_page_extractions.py`: 기존 행 변경 없는 새 `page_extractions` 테이블 및 신규 적재 연결.
- 신규 `extraction_provenance.py`, `table_evidence.py`, `document_candidates.py`, `analysis_retrieval.py`, `analysis_service.py`: page hash/word span/품질/chunk 검증, 저장 표 검색 및 neutral 분석 후보 연결. 기존 발행/투자 표현 검증 유지.
- `schemas.py`, `main.py`: 페이지 응답에 nullable extraction 요약 추가. 기존 enum/필드 유지.
- `tests/test_page_layout.py`, `tests/test_pipeline.py`: 새 적재·OCR 선택·좌표/보류·단절·위변조 테스트. 기존 안전성/삼성전자 테스트 유지.
- `scripts/audit_parser.py`, `scripts/replay_layout_observations.py`, `scripts/verify_ingestion_review.py`, `evals/ingestion-reviewed.json`, 본 보고서 및 `api-contract.md`, `acceptance.md`, `qa-rules.md`.

이번 작업 시작 전 다른 변경들은 보존했다. reset/checkout/DB 초기화/PDF 삭제를 하지 않았다.

### 2. 일반적인 OCR 실행 조건과 선택

80자 길이 문턱을 없앴다. 72dpi 렌더에서 어두운 픽셀(<180)을 측정하고 native 단어 bbox(+1 point)로 덮이지 않는 잉크가 200 pixel 이상이면서 35% 이상이면 OCR한다. native word가 없는데 잉크가 있거나, replacement/control 문자 비율이 1%를 넘거나, 선형 영역이 있는데 native 숫자가 없고 미포함 잉크가 있는 경우도 실행한다. 회사/문서/질문/정답 값 분기는 없다. 이 임계치는 결정적 휴리스틱이며 보편 최적값을 검증한 것은 아니다. `OCR_MIN_NATIVE_TEXT_CHARS`는 더 이상 판정에 사용하지 않는다.

짧아도 공간적으로 완전한 native 페이지는 OCR을 생략한다(자동 테스트). 감사 PDF 21페이지는 모두 실제 미포함 영역 신호가 있어 OCR 대상이었다. 모든 PDF에 무조건 OCR하도록 구현한 것은 아니다. LG p2 native 287자에서도 미포함 잉크 약 96%를 감지해 표 영역을 읽었다.

더 긴 OCR을 통째로 선택하지 않는다. 정상 native 본문은 보존하고 native word로 덮이지 않는 OCR 부분을 추가한다. 겹친 숫자가 다르면 native를 임의 교정하지 않고 충돌을 기록해 근거 대상에서 제외한다. 손상 native token은 unsafe로 남기되 정상 native 본문까지 버리지 않는다. OCR 실패 시 native를 유지하며 페이지 오류를 기록한다.

OCR 값/기간은 confidence 80, 행/지표/단위는 65 기준을 적용한다. 약한 숫자/기간·영문 토큰 중 최대 16개/페이지를 cropped PSM7로 재확인할 수 있다. **두 번째 결과가 원래 토큰과 정확히 같고 confidence ≥80인 경우만 확인**하며 다른 문자열/수치로 바꾸지 않는다. 원래 confidence와 재확인 crop/text/confidence를 모두 보존한다. confidence는 정답 보증이 아니며 `1026`처럼 높은 confidence의 잘못된 기간도 문법 검증에서 보류한다.

### 3. 저장·청킹·검색·인용 연결

`page_extractions(page_id PK/FK, parser_version, final_text_sha256, provenance JSON, table_facts JSON)`을 additive migration으로 추가했다. 기존 75페이지에는 행을 생성하지 않았다. provenance에는 native block/word, OCR word, 최종 선택 word의 bbox/source/confidence/문자 offset, unsafe span, OCR 이유·DPI·버전을 저장한다. mixed는 기존 API `text_source=native`를 유지하고 `extraction.selection_mode=mixed`로 정확히 구분한다.

표 fact는 row_label + metric + column_name + period + status + unit + literal value + 물리 페이지 + source_spans이다. 행·열·단위·값 각각의 source span을 보존하며 native/OCR/mixed 출처를 남긴다. 행과 헤더가 서로 다른 1200자 청크여도 같은 페이지의 좌표로 연결하고, 적재 후 각 span을 덮는 source_chunk_ids를 붙인다. 값만의 인용이나 합성 문장을 만들지 않는다. 일반 본문 numeric_evidence는 별도 provenance로 보관해 표 UI에 넣지 않는다.

최소 2개 정렬 데이터 행과 명시적 열/단위를 요구한다. 옆 비고 열의 날짜가 손상된 값 셀을 대신하지 못하게 오른쪽 열 경계를 검사한다. F/E=전망, A=실제, P=잠정, 나머지는 불명으로 보존한다. 불명 기간을 앞뒤 분기로 추론하지 않는다. 기간 없는 표는 period=null이며 기간 일치 검색 승격에 사용하지 않는다.

신규 페이지 검색은 저장 fact의 page hash, 원문 word/bbox, 값·열·상태·단위 및 모든 span의 chunk coverage를 검증한 뒤 row/metric/period/비교 조건이 맞을 때만 승격한다. 불확실하면 일반 chunk 검색으로 fallback한다. 기존 페이지는 종전 문자열 기반 경로 그대로다. 새 표는 분석 neutral 후보에도 전달되지만 기존 positive/negative 카드 발행 규칙을 우회하지 않는다. 자유형 중립 수치 답변 기능까지 추가한 것은 아니다.

### 4. 추출 실패 5개 근거 단위의 결과

| 기존 실패 단위 | 이번 결과 | 원본 대조와 제한 |
|---|---|---|
| LG 연간 전망, 물리 p1 | **복구** | 표의 영업이익 / 2026F / 십억원 / 1,643을 좌표 셀로 생성. 행·기간 헤더·행 단위·값 bbox와 final_text span을 모두 대조. |
| DB손해보험 순이익 비교, p1 | **복구** | 2분기 순이익 4,993억원, 컨센서스 4,386억원, 13.8% 상회 예상의 동일 본문에 수치 근거 3개 생성. 일반 문장이므로 table_fact로 표시하지 않음. |
| LG CNS 지분가치, p2 | **보류** | OCR 미실행 문제는 해소. CNS 및 3.42는 동일 토큰 재확인에 성공했지만 앞의 이름 토큰 `“LG` confidence 35가 불확실해 완전한 row/metric 후보로 승인하지 않음. 정답 3.42조원 확보로 세지 않음. |
| DB손해보험 1Q26 보험손익, p2 | **여전히 실패** | `1Q26`이 여전히 `1026`으로 읽힘. 227을 1Q26에 붙이지 않으며 1Q26 fact가 없는 것을 확인. |
| POSCO p1 개선 이유 묶음 | **보류** | 일부 문구가 나아져도 옆 열·본문 읽기 순서와 모든 원인 묶음을 인증하지 못함. 정답 복구로 세지 않음. |

기존 추출 실패 5개 중 **2개**만 복구로 판정했다. DB p1의 세 숫자를 3개 복구로 부풀리지 않았다. 이와 별도로 기존 성공 근거 POSCO p2 철강 / 영업이익 / 2Q26F / 십억원 / 424도 새 좌표 파서가 연결한다. 해당 2Q26F는 처음 confidence 72였으나 cropped PSM7에서 같은 토큰 confidence 90으로 확인됐다. 고유 문구/정답 기반 보정은 없다.

주의: 변경 전 비활성 파서도 이미 300dpi 기본값이므로 DB p1 세 숫자는 그 텍스트에 있었다. 이번 개선은 그 수치를 새로 정답으로 '고친' 것이 아니라, 기간·지표·단위·비교 기준과 좌표를 가진 검증 가능한 본문 후보로 적재하는 것이다. 기존 활성 DB의 200dpi 오독은 변경하지 않았다.

### 5. 기준선 비교와 평가 범위

| 원본 | OCR 실행 페이지 전→후 | 표 셀 후보 전→후 | 비활성 전체 파싱 시간 초 전→후 |
|---|---:|---:|---:|
| 20260710_DB손해보험 (005830_매수).pdf | 3 → 4/4 | 96 → 125 | 15.788 → 22.862 |
| 20260713_POSCO홀딩스 (005490_매수).pdf | 7 → 8/8 | 92 → 114 | 40.049 → 52.029 |
| 20260814_LG (003550_매수).pdf | 5 → 9/9 | 0 → 35 | 28.303 → 59.985 |

전은 기존 파서+기존 문자열 표 파서, 후는 새 좌표/품질 파서다. 셀 후보 개수는 정답 수가 아니며 정답률로 해석하지 않는다. OCR 좌표와 최대 16개 재확인으로 처리 시간이 늘었다. 단일 실행이라 속도 일반화는 하지 않는다.

**활성 DB retrieval recall@5: 7/12 → 7/12**(기존 삼성전자 2/2, 추가 기업 5/10). 11개 질문 전부의 top-5 chunk ID·quote·table_evidence가 동일함을 확인했다. vector 검색도 모두 사용됐다. 이것은 기존 활성 데이터에서 검색 코드 회귀가 없다는 평가다. **새 파서 텍스트를 실제 DB에 올리거나 재임베딩한 recall은 미측정**이며 9/12로 주장하지 않는다. 생성/답변 정확도도 미측정이다.

원본 3개는 기존 감사에 사용한 알려진 보고서이며 blind holdout이 아니다. LG p1 연간 표와 DB p1 비교 문장을 원본 PDF 렌더로 다시 직접 대조했다. 숫자/기간 보정은 없고 최종 판정은 이 작은 표본에만 해당한다.

### 6. 신규 업로드 적용 범위와 데이터 보존

`docker compose up -d --build`로 새 backend를 기동했다. 지금부터 **새 file hash의 신규 PDF 업로드**에 선택적 OCR→좌표/본문 사실→provenance 저장→기존 청킹·임베딩·검색 연결이 적용된다. 중복 PDF는 기존 document를 반환하며 재처리하지 않는다. 기존 staging/revision activation, 기존 문서 재임베딩, 활성 포인터 전환은 추가하지 않았다.

배포 전후 READ ONLY 정렬 JSON SHA-256이 documents(10), pages(75), chunks(231; embedding 포함), analysis_runs(311) 모두 동일하다. page_extractions는 0행이며 기존 문서에 backfill하지 않았다. 원본 PDF는 hash 확인 후 읽기만 했고 Git에 추가하지 않았다.

### 7. 남은 문제와 다음 작업

- `“LG` 같은 낮은 품질의 행 이름, `1026` 같은 문법상 모호한 열, 복잡한 옆 열/본문 읽기 순서는 여전히 보류 대상이다. 범용 행 그룹화·라벨 영역 인식의 추가 평가가 필요하다.
- 테이블별 평균 수치/보고서 지식으로 빠진 값을 채우지 않았다. confidence/일치 재확인만으로 OCR의 진실성을 보장할 수 없다. 다른 제작 도구·언어·스캔 품질의 새 표본 검증이 다음 우선순위다.
- 낮은 contrast/그림·수직선·복잡한 병합 셀, 날짜가 생략된 표, 다중 열 문장은 모두 지원 완료로 보지 않는다. 토큰 재확인 예산 초과는 보류하며 latency도 더 측정해야 한다.
- 기존 문서 활성화는 이번 범위 밖이다. 이 신규 파서가 더 검증된 뒤 별도 버전 보존/전환 작업으로 다뤄야 한다.

### 8. 실행·재현 및 검증

```sh
# DB 없는 비활성 실제 PDF 추출 (Tesseract kor+eng/Poppler 포함 backend 이미지)
docker compose run --rm -T --no-deps -v "$PWD:/workspace:ro" --entrypoint python backend /workspace/scripts/audit_parser.py > evals/results/ingestion/parser-confirmed.json
# 같은 OCR observations에서 최종 행 span 도출만 재현 (OCR 재실행/수치 수정 없음)
.venv/bin/python scripts/replay_layout_observations.py evals/results/ingestion/parser-confirmed.json > evals/results/ingestion/parser-reviewed.json
# 실제 DB READ ONLY 검색; 질의 bge-m3 임베딩만 호출
docker compose run --rm -T --no-deps -v "$PWD:/workspace:ro" --entrypoint python backend /workspace/scripts/audit_retrieval.py > evals/results/ingestion/retrieval-after.json
.venv/bin/python scripts/verify_ingestion_review.py
./scripts/check.sh
git diff --check
docker compose up -d --build
docker compose ps
curl --fail http://localhost:8001/health
curl --fail -o /dev/null http://localhost:3000
```

검증: backend **206 passed, 1 skipped**(로컬 google-genai SDK 관련 건너뜀), frontend **7 passed**, lint/production build/check.sh/diff-check 통과. Compose PostgreSQL/backend healthy, backend/frontend HTTP 200. 최종 DB 해시 검증 통과. 샘플 업로드/임베딩 테스트는 격리 fixture에서만 실행했다.

최종 행 quote를 불필요한 한 글자/글머리표로 남기지 않도록 전체 행 이름 span을 선택하는 도출 검증에는 같은 OCR observations를 재사용했다. 원본 이미지/인식 텍스트를 변경하지 않았다. 감사 PDF는 CropBox=MediaBox인 것도 확인해 CropBox 좌표 정합성 변경이 평가 픽셀을 바꾸지 않음을 확인했다. raw 실행 산출물은 evals/results/ 아래 Git 제외, 원문 판정과 source span 및 해시는 evals/ingestion-reviewed.json에 보관한다. 재실행으로 산출물 해시가 달라지면 새 원문 판정 없이 검증 파일을 통과시키지 않는다.


## Shadow revision retrieval 평가 (2026-09-23)

신규 파서의 실제 원본 재실행 결과를 additive `20260923_0006` migration의 `shadow_revisions/pages/chunks`에만 저장했다. 원본 document/file hash/parser version unique, 페이지별 native/OCR/provenance/table facts, chunk별 offset/bge-m3 1024 벡터를 보존한다. DB손해보험 4페이지/8청크, POSCO 8/16, LG 9/18: 총 **3 revision, 21페이지, 42개 실제 임베딩**. 동일 원본·버전 재실행은 같은 revision/벡터를 재사용했고 top-5도 동일했다. 활성화 코드·포인터·API는 없다.

검색은 활성 경로와 공유하는 `search.rank_rows`의 BM25 + exact cosine + RRF(k60, 후보20) + verified table candidate를 revision 내부에서만 실행했다. 기존 활성 PostgreSQL 검색 경로와 순위 규칙은 유지했다. 문서/질문/정답 조건은 평가 fixture에만 있으며 검색 코드에 기업별 분기는 없다.

| 고정 12개 근거 단위 | 활성 baseline | shadow 비교 |
|---|---:|---:|
| 삼성전자 공통 대조군(재처리 안 함) | 2/2 | 2/2 |
| 추가 3기업(실제 shadow 검색) | 5/10 | 6/10 |
| 합계 recall@5 | **7/12** | **8/12** |

새 성공: LG p1 `영업이익 / 2026F / 십억원 / 1,643` 표 fact는 최종 1위이며 헤더·행·단위·값의 원문 span/bbox를 검증했다. DB p1 `2분기 순이익 4,993억원 / 컨센서스 4,386억원 / 13.8% 상회 예상`은 최종 1위 chunk 안의 검증된 본문 numeric evidence 3개에 모두 존재한다(근거 단위는 1개). 생성·답변 정확도·근거 없음 보류율은 평가하지 않았다.

남은 실패 **4/12**, 모두 추출 단계:
- LG CNS p2: top1이지만 행 이름 `“LG` confidence 35, 승인된 행 사실 없음. 값만으로 성공 처리하지 않음.
- DB 1Q26 보험손익 p2: top1이지만 기간 `1026` 오독 지속. 227을 1Q26에 추정 연결하지 않음.
- POSCO 개선 이유 p1: top4이지만 옆 열이 본문과 섞이며 전체 원인 묶음 span 인증 보류.
- **POSCO 전망 p1 회귀**: top1에 7,570/7,097은 있으나 기간 `202614`, 지표 `AHO 익`/`영언이익`으로 훼손. 기존 활성 성공을 shadow 성공으로 계승하지 않음.

따라서 목표 **9/12 미달**이다. 청킹/검색 실패로 잘못 돌리거나 추가 튜닝하지 않았다. 다음 작업은 POSCO 본문 OCR·읽기 순서와 기존 성공 span의 보존 검증이다. 활성 데이터는 documents/pages/chunks(벡터 포함)/analysis_runs/page_extractions 정렬 JSON 해시가 전후 동일했고 활성 11질문의 top-5 ID·quote·table evidence도 직전 7/12 결과와 동일했다. 원본 PDF·활성 데이터·UI·생성 모델은 변경/호출하지 않았다.

변경: `shadow_models.py`, `shadow_revision.py`, `search.py` 공통 순위 함수 분리, migration/env, `test_shadow_revision.py`, `audit_shadow.py`, `verify_shadow_review.py`, `evals/shadow-reviewed.json`, 계약/수락/QA 문서. 원시 JSON은 Git 제외 `evals/results/shadow/run.json`, 중복 재실행은 `repeat.json`; 판정은 원시 파일 SHA에 묶어 재현한다.

```sh
docker compose run --rm -T --no-deps -v "$PWD:/workspace:ro" --entrypoint python backend /workspace/scripts/audit_shadow.py > evals/results/shadow/run.json
.venv/bin/python scripts/verify_shadow_review.py
```

첫 명령은 shadow 테이블에만 쓴다. 새 파싱/UUID로 산출물 해시가 바뀌면 기존 판정을 자동 재사용하지 않고 다시 원문 검토해야 한다. `./scripts/check.sh`: backend **208 passed, 1 skipped**, frontend **7 passed**, lint/production build 통과. `git diff --check`, `docker compose up -d --build`, backend `/health` 200 통과. 생성 모델/기존 17문항 생성 CLI 호출 없음.


## Fact-level fusion v4 shadow 평가 (2026-09-23)

`fact-fusion-v4`를 신규 parser version으로 추가했다. 기존 `mixed-layout-v1`, fact-fusion-v2/v3 revision과 활성 documents/pages/chunks/embeddings는 그대로 보존했다. PyMuPDF native words/blocks와 `find_tables()` cell topology, 300dpi PSM6 및 200dpi PSM3 OCR 후보를 독립 생성하고, 후보마다 `native_text | native_table | ocr_text | ocr_table`, bbox, source span, confidence, OCR DPI/PSM, parser version을 저장한다. 같은 위치의 값·기간 충돌은 보류하며 native 후보를 낮은 신뢰도 OCR이 덮지 않는다.

표·수치의 source span은 원문 quote 및 chunk와 연결한다. 검색 대표 후보에서는 헤더/행/값 proof-only 조각을 분리해 검색 노이즈를 줄이고, 검증된 table/numeric fact 필드를 BM25/vector 검색 표현에 추가한다. 활성 경로에는 fact-fusion parser가 적용되지 않는다.

| 평가 | 결과 |
|---|---:|
| 활성 baseline | **7/12** |
| fact-fusion-v4 shadow | **8/12** |
| 목표 | **10/12 미달** |

v4 shadow top-5에서 원문으로 확인된 개선/유지: LG 2026F 1,643십억원 table fact, DB 4,993/4,386/13.8 본문 quote(단, 4,993 fact 연결은 보류), POSCO 2Q26F 철강 424십억원 table fact, POSCO 7,570/7,097 numeric facts. 다만 DB 4,993 후보는 동일 문장 quote에는 있으나 stored numeric evidence가 불완전해 정답 성공으로 부풀리지 않았다. LG 실제 5,330/92.5는 top-5 literal chunk가 있으나 2Q26 period span이 구조화되지 않아 safe fact 승격으로 세지 않았다.

미해결 4개는 다음과 같다.

| 단위 | 판정 | 원인 |
|---|---|---|
| LG CNS 3.42조원 | 보류 | 행 이름 `LG` confidence가 낮고 native table topology가 행 전체를 검증하지 못함 |
| DB 1Q26 보험손익 227 | 실패 | OCR이 `1026`; 기간 자동 보정 금지 |
| POSCO 개선 이유 | 보류 | OCR 문장과 좌측 열이 섞여 원인 전체 source span 불완전 |
| DB 2분기 순이익 4,993 | 보류 | quote는 top-5이나 `4,993`의 structured numeric evidence 연결이 불완전 |

평가는 active baseline과 v4 shadow 모두 bge-m3 검색을 사용했고 생성 모델은 호출하지 않았다. active/prior-shadow hash 전후 동일, v4 3개 revision은 ready 상태다. 원시 결과는 `evals/results/fusion/shadow-v4.json`에 있고 Git에서 제외된다. `./scripts/check.sh`는 backend **224 passed, 1 skipped**, frontend **7 passed**, lint/build를 통과했다. `git diff --check`도 통과했다. 목표 미달이므로 active 전환이나 일반화 완료를 주장하지 않는다.

## PP-StructureV3 신규 적재·shadow retrieval (2026-09-24)

복잡 페이지에서 native 좌표·표 후보를 보존하면서 PP-StructureV3 레이아웃/읽기 순서/표 셀/OCR 좌표를 주 추출 결과로 사용한다. Paddle가 유효 결과를 반환하지 못할 때만 Tesseract가 마지막 fallback이다. 각 승격 fact는 물리 페이지, 행·열·기간·단위·값, source span/bbox, confidence, 모델 및 `fact-fusion-paddle-v2` 버전을 보존한다. 활성 문서 검색 경로와 데이터는 바꾸지 않았다. Linux aarch64/Python 3.12 환경의 PaddleOCR 3.3.2 + PaddlePaddle CPU 3.2.2는 분리된 `ocr-worker`에 설치했다.

고정 12개 근거 단위의 bge-m3 BM25+vector+RRF top-5를 같은 원본 3개와 삼성전자 대조군으로 다시 측정했다. 기존 활성 **7/12**, 앞선 fact-fusion shadow **8/12**, 새 Paddle shadow **11/12**다. 원본 PDF 렌더와 검증된 span/bbox를 대조해 LG CNS p2 `LG CNS/3.42조원`, DB p2 `보험손익/1Q26/십억원/227`, LG p1 `영업이익/2026F/십억원/1,643`, DB p1 `4,993/4,386/13.8%`, POSCO p2 `철강/영업이익/2Q26F/십억원/424`, POSCO p1 `7,570/7,097억원`을 성공으로 셌다. 앞선 8개 성공 근거는 회귀하지 않았다. 삼성전자 2개는 재처리하지 않은 활성 공통 대조군이다.

남은 실패 **1/12**: POSCO p1 철강 개선 이유 문장은 Paddle 읽기 순서와 위치가 보존됐으나 p1 문단이 복합 질문의 top-5에 없고 p2 표 후보만 노출됐다. 분류는 **fact 연결 실패(복합 질문의 본문·표 근거를 함께 검색 후보에 연결하지 못함)**이며, 페이지 문장이 존재한다는 이유로 성공 처리하지 않았다. 다음 작업은 문서 범위 내 복합 질문의 본문·표 근거 연결을 별도 측정하고, 21페이지에서 1,833개까지 늘어난 fact anchor 청크의 색인 비용과 중복을 줄이는 것이다. 현재 활성화 기능은 없고 기존 문서는 전환하지 않았다.

DB손해보험 4페이지/474청크, POSCO 8/710, LG 9/649의 신규 버전 revision만 추가했고 각 청크에 bge-m3 벡터가 있다. 활성 및 이전 shadow 데이터 해시는 전후 동일했고 활성 top-5 ID·quote·table evidence도 기준선과 동일했다. 생성 모델 호출은 없었다. 원시 결과는 Git 제외 `evals/results/paddle/shadow-v2.json`, 원본 대조 판정과 해시 고정 검증은 `evals/paddle-reviewed.json`에 있다. 재실행 시 원시 결과 해시가 달라지면 새 원문 검토가 필요하다.

검증: `./scripts/check.sh` backend **235 passed, 1 skipped**, frontend **7 passed**, lint/production build 통과. `git diff --check`, `docker compose up -d --build` 통과; PostgreSQL/backend/OCR worker healthy, backend `/health` 응답 `{"status":"ok"}`. 현재 성공 범위는 이 고정 12단위와 세 원본의 shadow 평가이며, 미지의 신규 문서 전체에 대한 일반화 수치는 아니다.

## Pinned Paddle shadow 실행 증거 (2026-09-24)

위의 과거 `11/12`는 **historical/non-reproducible**이다. 재처리 후보 9/10과 재처리하지 않은 활성 삼성전자 대조군 2/2를 합친 참고 수치였고, 당시 worker image·전체 의존성·모델 파일 hash가 없었다. 현재 환경의 식별자를 과거 결과에 소급 적용하지 않는다.

새 `20260924-pinned2` 실행은 DB손해보험·POSCO홀딩스·LG 원본의 21페이지를 현재 PP-StructureV3 worker로 다시 처리해 별도 shadow revision 3개와 bge-m3 벡터를 만들었다. 매 페이지 `ocr_source=paddle`, fallback 0이며, worker image ID `sha256:572cdba45c476468d0ab92ff8210e9cf381b88cffce1bb2d900ea096ccc3e273`와 실행 시점 Python/PaddlePaddle/PaddleOCR/PaddleX 버전, `pip freeze` hash, 64개 모델 파일 hash, OCR 옵션, PDF hash, parser/git/diff hash, 페이지·evidence의 bbox/span/text hash를 revision별 불변 JSON manifest로 보관했다. DB/POSCO/LG manifest SHA-256은 각각 `c7bca864702a87a91bf94dda383e7787ad4f417b42d4b2b187d0eb5019562d7d`, `90f31f1e4af080839f3c23aab94a5d2d43a4ae3398953e0c60a464fab85acc38`, `5a495f9ad20d4146a68db8d3fe3ebbc365b98fc3cbf53980fff2c153b5918a55`다. 원시 manifest는 Git 제외 `evals/results/paddle/pinned-20260924-pinned2.json`에 있다.

고정 개발 12단위를 **동일한 revision으로 읽기 전용 재검색 두 번** 수행하고 `evals/pinned-reviewed-final.json`에 묶었다. 두 결과의 top-5, 인용 span/table·numeric evidence, manifest hash, 평가 코드 hash가 일치했다. `paddle_candidate_recall@5=9/10`, `invariant_control_recall@5=2/2`, `combined_comparison_recall@5=11/12`이며 실패는 POSCO 개선 이유 묶음 1개다. 이는 retrieval 결과이며 생성 품질이나 일반화 성능이 아니다. 평가 원시는 Git 제외 `evals/results/paddle/pinned-20260924-pinned2-final{1,2}.json`에 있다. 최초 pinned 평가에서 revision suffix와 fact의 base parser version이 달라 table/numeric 승격이 되지 않은 결과는 무효로 두고, 검색 adapter의 version 전달만 바로잡은 후 이 두 평가를 실행했다. 추출 결과·OCR/청킹/순위 규칙은 변경하지 않았다.

`documents/pages/chunks(벡터 포함)/analysis_runs/page_extractions`의 실행 전후 SHA-256은 두 평가에서 각각 동일하다. 대표적으로 documents `90a528749fa287d8614fe5383fa6c8a37f67498e778206108d5796860565f8b4`, pages `1cf7866151671415c87cc90b8a439c48969ebdc7a95611ba289fc041179cb575`, chunks `bce2ec67ef0b99dca798891b76998fedc9cbbe969c01a749906619198033bf0e`다. 활성 전환·생성 모델 호출은 없었다. 기아·SK하이닉스의 미사용 PDF 2개는 `evals/holdout-cases.json`에 질문·gold bundle·물리 페이지·원본 SHA-256을 사전 고정했고 **채점하지 않았다**. 남은 검색 실패 해결은 별도 evidence-bundle 작업으로 남긴다.

검증: `scripts/verify_pinned_shadow.py`의 두 재검색 검증, 관련 backend 12개 테스트, 전체 `./scripts/check.sh`(backend 245 passed/1 skipped, frontend 7 passed, lint/build), `git diff --check` 통과. `docker compose up -d --build` 후 PostgreSQL/backend/OCR worker healthy, backend `/health` 정상, frontend HTTP 200이다.

## Evidence-bundle retrieval 개발·holdout (2026-09-30)

복합 질문에만 서술 원인과 명시적 표/수치 요구를 분리하고, 기존 hybrid RRF 후보 20개와 검증 table/numeric 후보를 같은 문서 내에서 최대 5개 pack으로 고른다. 원문 page/span/bbox와 행·지표·기간·단위·값을 확인하며, 하나라도 빠지면 `coverage_complete=false`다. 기존 `results` 전역 순위, bge-m3, RRF 상수, 파서·OCR·청킹, 활성 데이터는 변경하지 않았다. 분석 생성 packet이 pack 항목을 모두 포함하지 못하면 근거 부족으로 보류한다. 이번 평가에서는 생성 모델을 호출하지 않았다.

| 고정 개발 세트 | 기존 전역 top-5 | 최종 evidence pack 기준 |
|---|---:|---:|
| Paddle 재처리 후보 | 9/10 | **10/10** |
| 비재처리 활성 대조군 | 2/2 | **2/2** |
| 참고 합계 | 11/12 | **12/12** |
| 복합 근거 전체 coverage@5 | 0/1 | **1/1** |

기존 전역 top-5는 여전히 11/12로 **불변**이다. 단일 사실 질문의 top-5 ID·quote·table evidence 회귀는 0건, 개발 세트 pack complete rate는 1/1이다. POSCO 복합 질문에서 p1 원인 문단은 RRF **15위**, 물리 p1 `[622:934]`(“철강 부문 영업이익은 … 판가 상승 … 성수기 판매량 증가 … 원화 약세 및 중국 장가항 연결 제외 효과 … 개선 흐름”)를 pack에 포함했다. p2 표는 RRF **2위**(기존 최종 표 승격 1위)로, 물리 p2의 행 `철강` `[1286:1289]`, 지표 `영업이익` `[1232:1236]`, 기간 `2Q26F` `[449:454]`, 값 `424` `[1316:1319]`, 단위 `십억원` `[2092:2097]`을 함께 검증했다. 원시는 Git 제외 `evals/results/paddle/bundle-dev-safe.json`, 판정은 `evals/pinned-bundle-safe-reviewed.json` 및 `evals/results/paddle/bundle-dev-safe-metrics.json`에 묶였다.

사전 고정 `evals/holdout-cases.json` SHA-256 `aa377517abf5a9868cc6264a3d4680c3037b0606b2bf7bb87ef4a2e6f0b8ccfd`는 실행 전후 동일하다. 개발 게이트를 통과한 뒤 기아·SK하이닉스 원본 2개를 **각 1회만** 별도 shadow revision으로 처리했다. 두 문서 합계 20페이지, 1,194개 청크이며 Paddle page manifest 20/20, 활성 documents/pages/chunks(벡터 포함) 및 분석 데이터 hash는 전후 동일하다. 원시는 `evals/results/paddle/bundle-holdout-once.json`(SHA-256 `953d27b11f08d86fbf15d2d912b2128ef92f3d81c2be3d4f167638c69ffaba8a`), 직접 원문 페이지 2 렌더·저장 fact·검색 trace 대조 판정은 `evals/results/paddle/bundle-holdout-review.json`에 보관했다.

| 별도 holdout | 엄격한 묶음 성공 | 확인된 실패 단계 |
|---|---:|---|
| 기아 | 실패 | p1 전기차 영향 본문은 pack에 있다. p2 원본은 영업이익 발표치 `2,629`·컨센서스 `2,794` **십억원**인데 저장 표 fact의 단위가 `%`로 연결되고 비교 셀 fact가 없다. 최초 pack은 p1의 다른 numeric fact로 표 요구를 충족 처리한 거짓 양성이었다. |
| SK하이닉스 | 실패 | p1 AMD/NVIDIA 본문 chunk는 추출됐으나 RRF 25위라 후보 20개 밖이다. p2 원본의 `3Q26F` 영업이익 New `73.2`/Old `79.3` 조원은 텍스트에 있으나 검증된 table fact로 복원되지 않았다. pack은 비었고 `coverage_complete=false`다. |

따라서 holdout의 엄격한 `compound_evidence_coverage@5`는 **0/2**다. 기아에서 드러난 거짓 양성은 회사별 규칙 없이 **명시적 표 요구에는 table fact만 허용**하는 보수적 가드로 막고, 개발 세트를 다시 재검색해 10/10·2/2·복합 1/1을 유지했다. 이 수정 후 holdout 검색은 재실행하지 않았으므로 최종 코드의 holdout 성능은 미측정이다. 일반화 완료 또는 active 전환을 주장하지 않는다. 다음 한 단계는 holdout에서 드러난 표 헤더/단위/비교 셀 추출 무결성을 별도 작업으로 고치고, 미사용 새 holdout에서 다시 검증하는 것이다.

최종 검증: `./scripts/check.sh` backend **255 passed, 1 skipped**, frontend **7 passed**, lint/build 통과. `git diff --check` 통과. `docker compose up -d --build` 후 PostgreSQL/backend/OCR worker healthy, backend `/health` 정상, frontend HTTP 200. Compose 재기동 후 active 5개 테이블 hash도 위 pinned 기준과 동일하다.

## 표 evidence 무결성: 다단 헤더·혼합 단위·비교 셀 (2026-09-30)

### Before

현재 numeric-substitution guard가 들어간 코드에서 기존 `evals/holdout-cases.json`(SHA-256 `aa377517abf5a9868cc6264a3d4680c3037b0606b2bf7bb87ef4a2e6f0b8ccfd`)을 **수정 전에** 기존 shadow revision으로 읽기 전용 재검색했다. 기아는 p1 서술만 pack에 있고 p2 검증 표 후보 0개, SK하이닉스는 pack과 검증 표 후보가 모두 0개였다. 두 건 모두 `coverage_complete=false`, 엄격 판정 **0/2**다. 원시는 Git 제외 `evals/results/paddle/table-integrity-holdout-before-20260930.json`이다.

### Root cause

| 문서 | 재현 단계 | 근거 |
|---|---|---|
| 기아 p2 | 표 추출·단위 연결 | 원본의 `영업이익 / 2Q26P / 발표치 2,629 / 컨센서스 2,794`와 `(십억원, %)`가 Paddle 좌표 단어에는 모두 있다. 구조화 table 모델은 이 표를 빠뜨렸고, 기존 셀 경로는 직전 비율 행의 `%`를 금액 행에 넘겼다. 비교 열도 fact에 없었다. |
| SK하이닉스 p2 | 표 추출 후 단위 검증 | `3Q26F / New 73.2 / Old 79.3`과 행 이름은 좌표에 있으나 단위 선언이 `(원, 조원, %, %pt)` 혼합형이다. 해당 금액 행·열에 특정 단위가 직접 붙지 않아 `조원`을 안전하게 확정할 수 없다. |
| SK하이닉스 p1 | 검색 후보 제한 | AMD/NVIDIA 서술 chunk는 인덱스에 있다. 수정 전 RRF 25위, 새 revision에서는 BM25 23위·vector 108위로 전역 후보 20개 밖이다. 표 fact 자체가 없는 동안 전역 후보 수 증가로 해결되지 않는다. |

### Changes

`spatial_tables.py`는 구조화 table 결과에서 빠진 **표 제목·단위 선언·상단 기간·하단 열·둘 이상의 수치 행**이 좌표상 함께 확인될 때만 Paddle 단어로 grid fact를 만든다. 셀 x구간과 거리, 행 baseline, 기간 부모 헤더를 검증하며 가까운 다른 숫자를 빈 셀로 끌어오지 않는다. 혼합 단위에서 행·열이 하나의 단위를 지정하지 못하면 보류한다. `native_tables.py`의 단위 선택은 직전 행 우선에서 같은 행 셀 → 열 헤더 셀 → 표 머리 단위 순으로 바뀌었다. 비교 대상은 동일 기간·행의 별도 `comparison_cell`과 원문 bbox/span으로 보존한다. 저장된 fact는 `validated_stored_facts`가 원본 word 좌표에서 다시 산출해 값·기간·단위·비교 span 변조를 거부한다. 표 요청에 narrative numeric fact를 대신 쓰지 않는 가드는 유지했다. JSON 메타데이터와 선택적 응답 필드만 확장했으며 DB migration·active 전환·생성 호출은 없다.

### Regression

고정 개발 자료의 검증된 기존 Paddle 원시 관찰을 manifest hash와 대조해 새 shadow revision으로 재색인했다. 전역 top-5 근거 후보 **9/10**, pack 기준 **10/10**, 활성 삼성전자 대조군 **2/2**, 참고 합계 pack **12/12**, 복합 coverage **1/1**이다. 기존 revision을 현재 코드로 재검색한 단일 사실 10건의 **top-5 ID·quote·table evidence 변경은 0건**이다. 새 revision의 무작위 chunk ID는 기존 ID와 동일할 수 없으며, DB손해보험 한 문항에서 정답 아닌 후보 3~5위 순서가 바뀌었지만 정답 표 fact와 성공 판정은 유지됐다. 새 revision의 재처리 문항 8건은 두 차례 재검색에서 top-5·pack이 동일했다. 원시 산출물은 `evals/results/paddle/table-integrity-dev-new-20260930.json`, `table-integrity-dev-repeat-20260930.json`, `table-integrity-dev-existing-20260930.json`이다.

### Existing holdout after fix

원본 두 문서를 새 비활성 Paddle shadow revision으로 재처리했다. 기아 p2의 `영업이익 / 발표치 / 2Q26P / 십억원 / 2,629`와 같은 행 `컨센서스 / 2,794`가 각각의 bbox·span으로 검증되어 표 fact **복구**다. 그러나 pack의 p1 서술 span에는 골드가 요구한 인센티브 영향이 빠져 `coverage_complete=true`와 별개로 엄격 판정은 **실패(선택 단계)**다. SK p2 금액 단위는 계속 보류되어 표 후보 0개, p1 서술은 후보 20개 밖이므로 `coverage_complete=false`, 엄격 실패다. 따라서 표 fact 근거 단위는 **0/2 → 1/2**, 전체 엄격 묶음은 **0/2 → 0/2**다. 최종 코드의 동일 revision 재검색 두 번에서 top-5·pack 판정은 일치했다. 원시는 `evals/results/paddle/table-integrity-holdout-after-20260930.json`, `table-integrity-holdout-after-final-code-20260930.json`, 수동 원문 대조는 `table-integrity-holdout-review-20260930.json`에 있다.

### New unseen holdout

개선 코드를 작성한 뒤 처음 사용한 PDF 두 개의 질문·정답 원문 좌표·SHA-256을 `evals/table-integrity-unseen-cases.json`에 고정했다. fixture SHA-256은 실행 전후 `9b2da1d7a1cb54afffc4a105f5b45f31032f710a06942a7f77885196984d4a8b`로 동일하다. 원본 PDF는 Git/DB에 추가하지 않고 전체 페이지를 메모리에서 파싱·임베딩·검색했다. 원시는 Git 제외 `evals/results/paddle/table-integrity-unseen-20260930.json`에 있다. **엄격 성공은 0/2**이며 개발 12단위와 합산하지 않는다.

| 새 자료·원문 정답 | 검색·선택 결과 | 판정·단계 |
|---|---|---|
| 미사용 현대차 보고서 p1: HEV 확대·원가 절감 서술과 `영업이익 / 2026F / 십억원 / 11,491` 표 | 서술은 pack에 있다. p1 정답 표 fact는 검증된 span 5개와 함께 RRF 13위, 다른 p8에도 같은 값의 fact가 RRF 5위로 존재한다. 그러나 pack은 p1 `영업이익률 / 2026F / % / 5.9`(RRF 1위)를 선택하고 `coverage_complete=true`로 표시했다. | **실패: evidence selection/requirement 판별.** 지표가 다른 표를 완전한 근거로 승인한 거짓 양성이다. |
| 미사용 신용보증기금 요약본 p17: `신규 리스크인수율 / 2024년 / 3.30%`와 비교 `2023년 / 3.43%` | p17 원문 문장·인포그래픽을 PDF에서 확인했으나 검증된 table candidate 0개, pack 0개다. | **실패: table extraction.** 표 셀의 비교 관계가 구조화되지 않았다. 단일 질문 경로라 `coverage_complete`는 미설정(`null`)이고 엄격 판정은 실패다. |

첫 사례의 `coverage_complete=true`는 이번 새 자료에서 발견된 **추가 품질 결함**이다. 미사용 자료를 본 뒤 규칙이나 정답 fixture를 변경하지 않았다. 새 자료에 맞춘 점수 보정 없이 다음 작업의 회귀 대상으로 남긴다.

### Remaining failures

기아는 서술 evidence 선택, SK는 혼합 단위 표의 추출·검증과 서술 후보 컷오프가 남았다. 새 자료는 현대차의 **잘못된 지표 pack 선택을 complete로 표시하는 문제**와 신용보증기금의 비교 셀 추출 실패를 드러냈다. 다음 한 단계는 표 요구의 지표·기간·단위와 선택된 fact를 요구사항별로 정확히 대조하고, 불일치 시 `coverage_complete=false`로 보류하는 것이다. 현재 자료만으로 단위를 추정해 SK 값을 성공 처리하거나 후보 수를 무조건 늘리지 않는다. active documents/pages/chunks SHA-256은 각각 `90a528749fa287d8614fe5383fa6c8a37f67498e778206108d5796860565f8b4`, `1cf7866151671415c87cc90b8a439c48969ebdc7a95611ba289fc041179cb575`, `bce2ec67ef0b99dca798891b76998fedc9cbbe969c01a749906619198033bf0e`로 파싱 평가 전후 동일하다. 생성 LLM 호출은 0회다.

검증: `./scripts/check.sh`에서 backend **261 passed/1 skipped**, frontend **7 passed**, lint/production build 통과. `git diff --check` 통과. `docker compose up -d --build` 후 PostgreSQL/backend/OCR worker healthy, backend `/health`는 `{"status":"ok"}`, frontend HTTP 200. 재빌드 후 active documents/pages/chunks 해시도 위 값과 동일하다.


## Requirement matching과 false-complete 제거 (2026-10-02)

### Before와 원인

현재 작업 트리의 변경 전 선택 코드에서 문서 독립 fixture가 실패했다: 앞 서술의 `영업이익률`이 뒤 표의 `영업이익` 요구를 대신 충족했다. 실제 현대차 후보를 현재 `fact_matches_query`에 넣어도 true였다. 기존 requirement는 지표·단위 조건 없이 전체 질문의 기간 `2030`, `2026F`만 가지고, 전체 질문 문자열과 맞는 가장 높은 표 후보를 골랐다. `coverage_complete`도 requirement ID 개수만 세므로 metric mismatch를 발견하지 못했다.

`evidence_bundle.py`와 `search.py`의 변경 전 소스를 Git 제외 경로에 해시와 함께 동결한 뒤 실제 원본 두 문서를 다시 평가했다. 동결 runtime은 개선 코드를 읽지 않는다. 현대차는 실제로 `영업이익률 / 2026F / % / 5.9`를 선택하며 complete=true, strict=false였다. 신용보증기금은 table fact가 없어 이전 단일 질문 경로에서 coverage가 null이었다. 원시는 `evals/results/paddle/selection-before-20261002.json`, 소스·원인 증거는 `selection-baseline-proof-20261002.json`이다. 변경 전/후 공통 추출·임베딩 인덱스 SHA-256은 `eaeaa5ba90a03ecb33a2ef2b24a96b0df09267b33e3d931e2d0aaf5b66e7cd73`이다. 이후 OCR/재임베딩 없이 이 인덱스를 재사용했다.

### Requirement representation과 matching

표 요구를 해당 절에서만 `kind`, `metric(surface/normalized/modifier/is_rate/is_growth)`, `period`, `unit/unit_family`, `numeric_value_required`, `comparison_required/target`, 선택적 `entity`로 표현한다. 영업이익·영업이익률·영업이익 증가율은 서로 다른 metric이다. 매출/매출액, 당기순이익/순이익의 일반 표기만 canonical alias로 다루며 근거 값은 변경하지 않는다. FY/연간/분기와 F/E/A/P를 보존하고, 기간은 공백·대소문자·연도 뒤 `년` 외에 축약하지 않는다. 명시 단위는 그대로 요구하고, 미명시 단위는 금액/비율 family와 실제 원문 unit span을 대조한다. 금액에 `%`를 붙이거나 단위를 환산하지 않는다.

지표·기간·단위·수치·필수 비교 셀·source spans를 **동일 fact**에서 모두 확인한다. 비교 셀은 label/period/unit/value와 별도 원문 span이 있어야 한다. 한쪽 값만 있거나 다른 fact의 조건을 섞으면 거부한다. 기간이 여러 개면 각각 별도 requirement다. 동일 행·지표·기간·단위·값·비교 셀의 검증 fact가 여러 페이지에 반복되는 경우에만 이미 선택한 서술 페이지를 우선한다. 서로 다른 값에는 근접성 우선순위를 주지 않는다.

각 requirement의 coverage에는 required/matched/evidence_id/reason/checks를 기록하고, 모든 필수 check가 matched일 때만 complete=true다. 평가 diagnostics의 `selection.candidates`에는 candidate metric/period/unit/value, 각 check와 탈락 이유를 남긴다. 공개 API의 기존 results와 글로벌 순위는 그대로이고, 기존 선택적 JSON requirement/pack 필드만 확장했다. 표가 필요한 질문에 numeric prose를 대신 넣는 가드도 유지했다.

서술은 명시 factor를 분리하고, 회사 metadata를 제외한 focus 어휘를 모두 요구한다. 재무 영향 요청에는 재무 결과 어휘도 필요하다. 설명·결과 표현, boilerplate 제외와 원문 span을 검증한다. 이 결정적 lexical 판정을 모든 암묵적 원인의 의미적 증명이라고 취급하지 않으며, 엄격한 원문 gold 평가를 별도로 유지한다.

### 변경 전/후와 회귀

| 자료 | Before | After | 근거·남은 단계 |
|---|---|---|---|
| 현대차 regression | 다른 metric(영업이익률), complete=true, strict 실패 | **영업이익 / 2026F / 십억원 / 11,491**, complete=true, strict 성공 | 같은 p1 서술(RRF 11)과 표(RRF 13)를 선택. 표 source spans: 행/지표 `[1943:1948]`, 기간 `[1880:1885]`, 단위 `[1949:1954]`, 값 `[1976:1982]`; 각 bbox가 보존됐다. |
| 기아 기존 holdout | table fact는 정확하지만 인센티브 누락 서술을 선택, complete=true, strict 실패 | table fact 유지 + **인센티브/믹스·전기차의 단기 실적 영향과 중장기 경쟁력** 서술 선택, strict 성공 | 같은 후보 20개 중 p1 RRF 20의 `[1422:1693]`를 선택. 원본 p1 렌더와 대조했다. p2 RRF 1의 발표치 2,629/컨센서스 2,794십억원 및 2Q26P span은 그대로다. |
| SK하이닉스 기존 holdout | incomplete, strict 실패 | incomplete, strict 실패 | **extraction/unit validation + retrieval candidate cutoff**. 검증 표 fact 없음. p1 서술은 후보 20개 밖이며 풀을 확장하지 않았다. |
| 신용보증기금 regression | 표 비교 fact 없음, coverage=null, strict 실패 | **coverage=false**, strict 실패 | **extraction failure**. 2023/2024 비교 셀 fact를 selection에서 만들지 않았다. |

기존 기아/SK strict는 **0/2 → 1/2**, 기존 unseen에서 승격한 현대차/신용보증기금 regression strict는 **0/2 → 1/2**로 분리 보고한다. 위 고정 네 질문에서 complete=true이지만 선택 pack이 원문 gold를 뒷받침하지 못한 **false-complete는 2건 → 0건**이다. 새로운 미사용 자료를 추가하거나 일반화 성능을 주장하지 않는다.

개발 pinned shadow는 Paddle 후보 pack **10/10**, 활성 대조군 **2/2**, 참고 합계 **12/12**, 복합 coverage **1/1 → 1/1** 유지다. 기존 글로벌 top-5는 **11/12로 불변**, 단일 사실 10건의 top-5 ID/quote/table evidence 회귀 **0건**이다. 모든 기존 revision manifest를 원래 페이지·fact와 대조했으며 검증 규칙을 완화하지 않았다. 원시는 `selection-dev-release-20261002.json`, 지표는 `selection-dev-release-metrics-20261002.json`이다.

기아/SK 최종 재검색의 pack은 앞선 변경 후 검색과 동일하다(`selection-holdout-release-20261002.json`; 수동 원문 판정 `selection-holdout-release-reviewed-20261002.json`). 현대차/신용보증기금은 동일 동결 인덱스 두 재실행의 top-5/pack/requirements/strict 판정이 일치했다(`selection-unseen-after-20261002.json`, `selection-unseen-after-repeat-20261002.json`). 첫 after artifact의 신용보증기금 실패 stage는 coverage=false shortcut 때문에 selection으로 표시됐으나, classifier를 고쳐 최종 반복 artifact에서 **table_extraction**으로 기록했다. strict 판정과 선택 결과는 바뀌지 않았다. Gold fixture 파일은 변경하지 않았다. 표 라벨 공백만 typographic normalization하며 숫자·기간·단위·source span의 내용은 그대로 검증한다.

### 데이터 보호·검증과 remaining failures

active documents/pages/chunks(벡터 포함) SHA-256은 전후·Compose 재빌드 후 각각 `90a528749fa287d8614fe5383fa6c8a37f67498e778206108d5796860565f8b4`, `1cf7866151671415c87cc90b8a439c48969ebdc7a95611ba289fc041179cb575`, `bce2ec67ef0b99dca798891b76998fedc9cbbe969c01a749906619198033bf0e`로 동일하다. 기존 shadow/manifest/PDF/vector를 수정하지 않았고 DB migration·새 업로드·active 전환·생성 LLM 호출은 없다. OCR/파서/청킹/임베딩/RRF 상수도 변경하지 않았다.

지표·기간·단위 충돌, partial comparison, no valid fact, false-complete, factor 일부 누락, 동등 fact와 다른 값 구분 및 기업/정답 shortcut 방지 테스트를 추가했다. `./scripts/check.sh`: backend **285 passed/1 skipped**, frontend **7 passed**, lint/production build 통과. `git diff --check`, Compose build 통과; PostgreSQL/backend/OCR worker healthy, backend `/health` 정상, frontend HTTP 200. 원시 결과와 메모리 인덱스는 Git 제외 경로에 있다.

남은 실패는 SK의 혼합 단위 표 확정 및 서술 후보 컷오프, 신용보증기금의 비교 셀 extraction이다. 다음 한 단계는 **추출 단계에서 비교 셀의 기간·단위·값 source 연결을 보존**하는 것이며, selection에서 없는 값을 만들거나 후보 수를 전역으로 늘리는 우회는 하지 않는다.

## 구조화 비교 셀·혼합 단위 extraction (2026-10-02)

### Root cause — 수정 전 재현

현재 코드로 동결 인덱스/기존 shadow를 읽기 전용 재검색했다. 현대차·기아는 성공 유지, 신용보증기금·SK는 incomplete다. 원시는 `extraction-before-unseen-20261002.json`, `extraction-before-holdout-20261002.json`이다. PDF 물리 p17/p2 렌더를 직접 대조했다.

| 자료 | 관찰된 중간 구조 | 소실 단계 |
|---|---|---|
| 신용보증기금 p17 | 일반 가로 표가 아니라 metric 제목 아래 `'23년 / 3.43%`, `'24년 / 3.30%`가 세로로 나란한 비교 인포그래픽이다. native/Paddle 좌표 단어에 모두 존재한다. native table 4개는 이 영역의 셀 관계를 표현하지 않고 Paddle table은 0개다. 본문에는 전체 연도 2023년/2024년이 있다. | **row/column grouping → period association → fact construction**. 기존 fallback은 표 제목·괄호 단위·상단 기간·하단 비교 열·2개 metric 행만 지원한다. merged header 누락이 원인은 아니다. 축약 연도를 임의로 20xx로 채우면 안 된다. |
| SK p2 | 최초 decoded table은 목표주가 표 1개였다. 불변 원시 HTML을 추가 확인하니 Paddle는 표 2개(병합 셀 233개/일반 셀 21개)를 반환했으나 기존 decoder가 rowspan/colspan 표를 거부했다. 실적 변경표의 3개 기간·New/Old/변경율·수치는 좌표에 있다. 단위는 table-level `(원, 조원, %, %pt)`이고 영업이익 행에 특정 단위가 없다. | **cell detection 후 decoder grouping → unit association**. 모델이 표를 반환하지 않았다는 최초 해석은 정정한다. 병합 구조가 복원되어도 원·조원, %·%pt의 여러 선택지는 남는다. 선언 순서로 단위를 배정하지 않는다. 원시는 `extraction-sk-page2-before.json`이다. |

이번 수정은 관찰된 cell 관계와 명시 단위 scope를 보존하고 primitive cell에서 비교를 조립한다. 새 숫자나 축약 연도의 세기를 추정하지 않으며 selection/coverage 정책·후보 20개·OCR 설정은 유지한다.

### Changes

- `structured_cells.py`: 물리 cell/좌표 grid에서 `table_id/row_id/column_id/cell_fact_id`, 지표·기간·단위·값과 각 bbox/span을 보존한다. 검증은 원시 word/cell에서 재산출하여 ID·헤더·단위·비교 변조를 거부한다. 동일 표·행·지표·단위의 두 primitive 또는 같은 기간의 명시 benchmark에서만 comparison을 조립한다. 3개 이상 기간에서 상대 셀을 임의 선택하지 않는다.
- 단위는 해당 value cell → 같은 행 → 같은 열의 **헤더** → 명시 표 헤더 순이다. 금액/비율/주당/수량의 호환성을 확인한다. 혼합 목록의 순서·수치 크기로 단위를 추정하지 않는다. 마지막 검토에서 본문 셀의 단위가 뒤 metric의 열 헤더로 전파될 가능성을 독립 합성 fixture의 red/green 테스트로 차단했다. 추가 표를 본 뒤 unit 선택이나 인식 규칙을 맞추지 않았지만, 이 보수적 안전 수정은 최초 추가 표 실행 뒤였다. 따라서 최초 실행과 최종 관찰 재생을 별도 artifact로 기록한다.
- `paddle_tables.py`: 명시 rowspan/colspan, 물리 cell 개수와 bbox 순서가 일치하는 병합 표만 logical column으로 복원한다. SK p2 decoded 표는 **1 → 2**이며 실적 변경표의 24×10 구조가 보존됐다. 값·행의 OCR 문자열과 HTML이 다르면 여전히 거부한다.
- 세로 grid는 같은 metric 제목 아래 정렬된 기간/value 쌍이 있을 때만 후보화한다. 축약 연도는 동일 지표·동일 값을 적은 인접 원문의 전체 연도와 연결되는 경우만 채택한다. p17의 `2023년/3.43%`, `2024년/3.30%`는 각각의 chart bbox와 원문 확인 span을 유지한다. 원문에 있는 `신규` 주체도 별도 word span으로 보존했다.
- `fused_extraction.py`, `extraction_provenance.py`에 연결하고 parser를 `fact-fusion-paddle-v3`로 구분했다. API의 dict 메타데이터만 additive하게 확장했다. matcher에는 연도 `년`이 entity로 남던 token 경계 수정과, 좌표 검증된 `row_subject`의 **정확 일치** 지원만 추가했다. 부분 일치 허용·coverage 정책 변경은 없다. `table_evidence.py`의 신규 structured cell에만 연도 접미사 표기를 정규화했다.
- 평가 재생은 기존 pinned raw HTML/words를 보존하고 새 decoder로 재해석한 **메모리 인덱스**다. 원래 manifest를 검증했고, 새 parser의 source hash/input artifact hash를 별도로 남겼다. 이를 새 pinned OCR run이라고 주장하지 않는다. 거부된 old fact의 ghost anchor를 제외하고 신규 ingestion과 동일한 지원 span으로 색인했다. 배열 벡터 직렬화와 numeric span의 boxes/bbox 차이도 평가 script에서 처리했다. DB migration/재적재/active 전환은 없다.

### Regression과 Holdout

| 구분 | Before | After | 판정 방식·단계 |
|---|---:|---:|---|
| 기존 pinned 개발 revision Paddle pack | 10/10 | **10/10** | 원래 manifest 유지·원문 source 검증 |
| 활성 삼성전자 대조군 | 2/2 | **2/2** | Paddle 후보와 분리 |
| 개발 참고 합계 / 복합 coverage | 12/12 / 1/1 | **12/12 / 1/1** | 글로벌 top-5는 11/12 유지 |
| 단일 사실 10건 | 회귀 0 | **회귀 0** | 기존 revision top-5 ID/quote/table evidence 동일 |
| 기아·SK 기존 holdout | 1/2 | **1/2** | 기아 원문 수동 엄격 리뷰 성공, SK 단위 미확정 실패 |
| 현대차·신용보증기금 추가 regression | 1/2 | **2/2** | 같은 동결 OCR 원문에서 새 facts/임시 색인·엄격 판정 |
| 고정 네 질문 false-complete | 0 | **0** | SK false, 나머지 원문 gold와 일치 |

기아 p1 인센티브/믹스·전기차 영향 서술(RRF 20)과 p2 발표치 `2Q26P/영업이익/십억원/2,629`, 컨센서스 `2,794`(RRF 1)는 유지됐다. fixture의 서술 gold는 자연어 `required_facts`이고 자동 evaluator가 의미 판정을 할 수 없어 `narrative_review_required`로 출력한다. 자동 0/2를 성공으로 바꿔 덮지 않고 **수동 원문 엄격 리뷰 1/2**를 분리한다.

신용보증기금 p17 pack은 RRF 2의 `리스크인수율/2024년/%/3.30%`, 비교 `2023년/3.43%`다. 행 제목 `[2600:2609]`, native 지표 `[1265:1271]`, 주체 `[1262:1264]`, chart 기간 `[2675:2679]`, 전체 연도 `[1190:1195]`, 값/단위 `[2680:2685]`, 비교 chart 기간 `[2633:2637]`, 전체 연도 `[1176:1181]`, 비교 값/단위 `[2638:2643]`가 원문과 각각의 bbox로 검증됐다. 퍼센트 suffix를 별도 unit으로 표현한 gold와 literal `3.30%`를 비교할 때만 suffix representation을 맞춘다. 반올림·환산·숫자 교정·gold 변경은 없다.

SK p2 New `73.2`, Old `79.3`의 3Q26F/영업이익 셀은 동일 표·행·열 ID와 source spans를 갖는 **unit_ambiguous 관찰**로 남고 retrieval fact가 되지 않는다. 기존 잘못된 metric/unit 조합 9개도 새 메모리 색인에서 제외했다(해당 p2 stored fact 44 → 35; 정답 표 fact 0 유지). 필요한 p1 HBM 서술은 인덱스에 있지만 후보 제한이 남는다. 최종 rank는 원시 diagnostics에 기록했으며 전역 후보 20·RRF 60·bge-m3 1024는 변경하지 않았다. monetary unit이 미확정인 동안 cutoff 조정으로 성공을 만들지 않는다.

원시: `extraction-dev-release-20261002.json`, `extraction-dev-release-metrics-20261002.json`, `extraction-holdout-release2-20261002.json`, `extraction-holdout-release-reviewed-20261002.json`, `extraction-unseen-release2-20261002.json`. 같은 메모리 인덱스 두 실행과 최종 보수적 guard 재검증은 `extraction-holdout-repeat-release2-20261002.json`, `extraction-holdout-final-20261002.json`, `extraction-unseen-repeat2-20261002.json`, `extraction-unseen-final-20261002.json`에 있다. 검색·pack·source spans·판정은 일치했다. 기존 pinned 개발 두 재실행도 일치했다.

### New unseen tables — 문서 미사용과 구분

코드 작성 뒤 정답 평가에 쓰지 않은 표 3개를 `extraction-unseen-table-cases.json`에 고정했다. **서로 다른 PDF 2개지만 완전히 미사용인 문서는 1개**다. 기존 삼성전자 corpus의 미사용 재무표 두 개는 새로운 문서 holdout이라고 부르지 않는다. 새 문서 자료를 보고 인식/단위 규칙을 조정하지 않았다. 마지막 독립 안전 가드 이후에는 동일 원시 관찰을 최종 코드로 재검증했다.

| 추가 표 | 원문·검증 결과 | 엄격 결과·실패 단계 |
|---|---|---|
| 기존 corpus의 미사용 현금흐름 표 p6 | `영업활동으로 인한 현금흐름/2025/십억원/85,315`, `2026F/344,784`의 **primitive 2/2** 생성. 각 셀의 period/value bbox/span이 있다. 2027F/2028F도 있어 자동 comparison pair는 만들지 않았다. | **실패: fact construction**. 명시한 비교 대상 두 개를 다기간 graph에서 선택하는 기능 미지원 |
| 같은 p6 미사용 valuation 표 | `EPS/2026F/원/46,469`, `배당성향/2026F/%/22.1`이 각각 **같은 label cell의 row+unit span**으로 복원된다. 원본 렌더와 대조했다. metric별 unit은 섞이지 않는다. | **원문 component 엄격 리뷰 성공**. raw 행 이름 `EPS(원)`/`배당성향(%)`과 단위가 분리된 저장 row 이름의 문자열 채점은 실패했으며, 동일 셀의 원문 row+unit을 그대로 재구성한 리뷰를 분리한다. fixture는 수정하지 않았다. |
| 완전히 미사용 교통사고 표 p1 | 건·명·%의 상위/하위 헤더와 값이 원문에 있지만 기간은 미표기다. 기대 `계/노인사고/건/42,369`, `계/사망/명/761`을 확정된 period fact로 만들지 않았다. | **실패: header/period association**. 기간을 만들어 붙이지 않는다. |

자동 literal-row strict **0/3**, 원문 row+unit component 재구성 리뷰 **1/3**을 별도로 남긴다. 새 문서만의 엄격 결과는 **0/1**이므로 미사용 문서 일반화 검증은 통과하지 못했다. 최초 OCR 실행 `extraction-new-tables-20261002.json`, 동일 관찰 최종 코드 재검증 `extraction-new-tables-release-20261002.json`, 원문 리뷰 `extraction-new-tables-reviewed-20261002.json`이다. gold의 좌표는 수동 render 영역이며 실제 반환 fact의 precise source spans/bbox는 리뷰 artifact에 저장했다.

추가로 p6 `자산총계/2026F`는 원문 렌더 `1,027,525`를 Paddle이 `21,027,525`로 읽은 사례가 관찰됐다(**parsing/OCR 인식 실패**). 고정 표 점수에 포함하지 않았고 정확한 값으로 복구했다고 주장하지 않는다. 전체 반환 fact 335개가 정확하다는 의미로 해석하지 않는다. OCR 문자열·bbox의 연결 검증은 OCR 자체의 인식 정확성을 증명하지 못한다.

### Data protection, QA와 Remaining

active documents/pages/chunks(벡터 포함) 해시는 변경 전후·Compose 배포 후 각각 `90a528749fa287d8614fe5383fa6c8a37f67498e778206108d5796860565f8b4`, `1cf7866151671415c87cc90b8a439c48969ebdc7a95611ba289fc041179cb575`, `bce2ec67ef0b99dca798891b76998fedc9cbbe969c01a749906619198033bf0e`로 동일하다. 생성 LLM 호출 0, 원본 PDF Git 추가 0, DB migration/삭제/active 전환 0이다.

최종 `./scripts/check.sh`: backend **297 passed/1 skipped**, frontend **7 passed**, lint/production build 통과. 단위 scope 전파의 red/green, 기간 비교 양쪽 source, 명시 단위 열·주당·수량·금액/비율 호환성, 병합 셀, 축약 연도 확인, source 변조 및 fake 신규 업로드 → metadata → 임베딩 → 검색 테스트를 추가했다. `git diff --check`, Docker Compose build/up 통과; backend `/health` 정상, frontend HTTP 200이다.

완료 기준을 전부 달성한 것으로 보고하지 않는다. SK 정답 monetary unit은 아직 **unit association/validation**, 다기간 중 명시 비교 대상 선택은 **fact construction**, 기간 없는 상위 헤더 표는 **header/period association**, 추가 잘못된 OCR 값은 **parsing** 단계다. 다음 한 단계는 **이미 검증된 다기간 primitive cell graph에서 요청된 두 기간의 비교 edge를 정확히 선택하는 것**이다. SK unit을 추정하거나 후보 수를 늘리는 우회는 하지 않는다.

최종 재개 검증: 중단 뒤 Docker Desktop을 시작하고 `./scripts/check.sh`, `docker compose up -d --build`를 다시 실행해 모두 통과했다. backend/PostgreSQL/OCR worker healthy, frontend HTTP 200, backend `/health`는 `{"status":"ok"}`다. 배포 후 읽기 전용 전체 snapshot도 before와 동일하며 `extraction-active-final-20261002.json`에 저장했다. 검사·Compose 로그는 각각 `extraction-check-resume-20261002.log`, `extraction-compose-resume-20261002.log`다. 최종 추가 표 component 리뷰는 `extraction-new-tables-release-reviewed-20261002.json`이며 최종 관찰 재생 source hash와 고정 fixture hash를 검증했다. 기존 holdout·추가 regression의 두 실행은 cases 전체(search/pack/span/판정 포함)가 동일하다.

## Query-scoped primitive graph (2026-10-02)

### Before / Root cause matrix — production 수정 전

고정 추가 표 3개를 같은 원시 OCR/text로 재실행했다. `graph-before-tables-20261002.json` 자동 literal strict **0/3**; 메모리 bge-m3/BM25/vector/RRF 재검색 `graph-before-search-20261002.json`도 **0/3**. 완전 신규 문서는 이 3개 중 교통사고 문서 1개이며 **0/1**이다. 새로운 4번째 문서인 것처럼 합산하지 않는다. 모든 원시는 Git-ignored `evals/results/paddle/`다.

| 요구 지표·기간 | primitive A/B 및 validation | graph link / retrieval / selected / complete | 최초 실패 및 추가 결함 |
|---|---|---|---|
| 영업활동으로 인한 현금흐름, 2025·2026F | 두 primitive 모두 존재·검증됨: 십억원/85,315 및 344,784. 표에는 총 4개 기간 | query-specific link 없음; 일반 표 후보는 있지만 pack comparison 선택 없음 / false | **comparison linking**. 파서가 정확히 2개 기간일 때만 비교를 만들며 4개 기간에는 만들지 않는다. requirement parser에도 현금흐름 metric 요구가 없어 requirement matching 결함이 함께 있다. |
| EPS·배당성향, 2026F | EPS/원/46,469, 배당성향/%/22.1의 원문 구성요소는 검증됨. literal gold 행 `EPS (원)`·`배당성향 (%)`과 저장 metric/별도 unit의 표기가 다름 | 비교 질문 아님; literal requirement와 저장된 분리 component 연결이 안 됨 / false | **requirement matching**. primitive 누락으로 잘못 분류하지 않는다. 기존 자동 literal 결과와 component manual review 1건은 별도 유지한다. |
| 계/노인사고·사망, 기간 없음 | 해당 primitive A/B 없음. 원문에 기간 자체가 미표기 | link 없음 / 필요한 표 후보 없음 / 선택 없음 | **period association**, 상·하위 metric header association 미지원. 다른 날짜를 붙이지 않는다. |

설계 범위: PDF cells→이미 검증된 primitive→명시 관계 graph→질문의 정확한 period pair→comparison assembly. 기존 parser/OCR/청킹·후보 수·RRF는 바꾸지 않는다. 기존 단일 기간·benchmark 경로는 유지하며 새로운 graph는 명시 다기간 comparison 질의에만 적용한다.

### Design / Existing regression

- 신규 `primitive_graph.py`는 저장 page에서 `validated_stored_facts`를 통과한 structured cell만 node로 만든다. parser가 과거에 붙인 comparison은 제거하고, nested second cell을 검증 없이 가져오지 않는다. 문서/물리 페이지/table ID, canonical metric/modifier(`metric_form` 재사용), label provenance+row geometry, 단위의 정확한 일치, 원문 period identity를 검증한 edge만 연결한다. row ID 단독 판정·단위 환산·OCR 보정은 없다.
- period identity는 raw/year/quarter/fiscal/qualifier/status를 보존한다. `2024`, `2024A/F/P`, `FY2024`, `4Q24/F/P`는 다르다. 기존 검증된 chart의 축약 연도는 full-year confirmation span이 있는 경우에만 date alias로 다루고 New/Old facet과 구분한다.
- `table_requirements`는 명시한 두 기간 각각을 독립 requirement로 유지하고 pair 전체를 `requested_periods`로 남긴다. 표에 4개 이상 기간이 있어도 해당 두 개만 query-time assembly한다. 현금흐름의 표준 지표 표현을 기존 canonical matcher에 추가했으며 metric 의미를 부분 일치로 완화하지 않았다. consensus/단일 기간은 기존 경로다.
- `verified_table_candidates`에서 query-specific graph fact를 후보화하고 pack의 source validator가 원문 node/edge를 재검증한다. 같은 검증 셀 쌍은 pack 하나로 묶되 양쪽 table evidence, 독립 requirement IDs/checks, 원문 source spans를 모두 보존한다. 여러 하위 열(New/Old 등)에 다른 값이 있으면 명시 facet 없이는 선택하지 않는다. parser/OCR/청킹/임베딩/RRF/전역 후보 수는 그대로이며 새 DB migration이 없다.
- 기존 추가 표 동일 메모리 평가 자동 strict **0/3 → 1/3**. 현금흐름 2025/십억원/85,315와 2026F/344,784는 모두 validated primitive이고 요청 pair graph+pack을 통과했다. EPS·배당성향 primitive의 metric/unit/period/value는 그대로 존재하지만 literal row와 composite requirement 문제로 incomplete 유지(**requirement matching**); 기간 미표기 신규 교통사고 문서는 primitive가 없고 **period association** 실패를 유지한다. 기존 component manual review 1/3을 자동 성공으로 변경하지 않는다.
- 현대차/신용보증기금 고정 regression **2/2 유지**. 신용보증기금의 native full-year confirmation과 chart bbox 양쪽은 그대로다. 최초 구현의 short-year alias/facet 회귀 1/2는 development 중 발견·수정했으며 최종 두 실행 2/2의 cases(search/pack/span 포함)가 동일하다. 기아/SK도 이전 최종 코드와 search 전체가 동일: 기아 원문 리뷰 성공, SK unit association/validation 보류. 기존 네 질문 false-complete **0 유지**.
- 기존 pinned 개발 revision의 원본 manifest를 검증한 재검색: 후보 pack **10/10**, 활성 대조군 **2/2**, 참고 합계 **12/12**, 복합 coverage **1/1**, global top-5 **11/12**, 단일 사실 회귀 **0**. 새 parser OCR run으로 표현하지 않는다. 원시는 `graph-dev-run1-20261002.json`, `graph-dev-run1-metrics-20261002.json`이다.

### Unseen after — 단계별 상태

| 고정 요구 | primitive A/B 존재·검증 | query graph link | retrieval/selection | complete / strict | 최초 실패 |
|---|---|---|---|---|---|
| 현금흐름 2025 ↔ 2026F | true/true → true/true | 없음 → 검증된 요청 pair | 원문 두 셀을 포함하는 pack 선택 | true / 성공 | 없음 |
| EPS·배당성향 2026F | 분리된 row+unit component는 true/true | 비교 요구 아님 | 표 원문 후보는 있으나 composite requirement 미충족 | false / 실패 | requirement matching |
| 계/노인사고·사망, 기간 미표기 | false/false | 없음 | 필요한 primitive/table 후보 없음 | null(기간 질의 성립 안 함) / 실패 | period association; header association도 미지원 |

`graph-before-tables-20261002.json`, `graph-before-search-20261002.json`, `graph-after-final-search-20261002.json`, `graph-after-final-repeat-20261002.json`, `graph-existing-stage-matrix-20261002.json`에 요청·primitive validation·graph relation·RRF 후보·선택·coverage를 남겼다. 두 최종 검색 cases는 동일하다. 페이지 검색 성공을 primitive 성공으로 세지 않는다.

### New unseen — implementation freeze 이후 선정

backend production 전체 39개 파일의 hash를 `graph-production-freeze-20261002.json`에 먼저 고정했다. 로컬 미사용 기업 소개 자료는 필요한 다기간 표가 없었고, 기존 삼성전자 broker PDF들은 evals/fixtures에서 사용됐음을 확인해 제외했다. 완전 미사용 공식 **삼성전자 2024 지속가능경영보고서 p56**, **현대차 2024 지속가능성보고서 p97** 두 문서를 선정했다. 서로 다른 PDF/표이며 기존 기업의 새 문서이므로 미사용 기업 검증이라고 표현하지 않는다. 공식 Kia 후보 URL은 사이트로 redirect되어 보고서가 아니므로 제외했다. 그 파일을 정답/점수에 사용하지 않았다.

정답은 parser 실행 전에 `primitive-graph-unseen-cases.json`에 PDF SHA-256/물리 page/metric/두 기간/원문 unit/value/원문 native word bbox/연결 기준을 고정했다. 삼성: 영업이익 2022년/조원/43.4 ↔ 2023년/조원/6.6(원문에는 2021년까지 3개 기간). 현대차: 연결 기준 영업이익률 2022/%/6.9 ↔ 2023/%/9.3(merged section header 및 십억원/%/대가 함께 있는 표). 골드는 원본 렌더와 직접 대조했으며 추가 관찰을 보고 production 로직은 수정하지 않는다. PDF는 Git 제외 results 경로에만 저장하고 DB에 업로드하지 않는다.

신규 2문서 원문·query graph 엄격 결과는 **0/2**다. 실제 Paddle worker가 두 페이지 모두 성공했고 fallback 없음(`primary_engine=paddle_structure`, `paddle_error=null`). 현재 worker 이미지/의존성/모델 fingerprint는 `graph-new-worker-20261002.json`, 원시 관찰은 `graph-new-observations-20261002.json`, 검색·span은 `graph-new-search-20261002.json`이다. 이번 판정은 기존 정답 재사용이 아니라 새 frozen gold와 원본 렌더 직접 대조다. 두 문서 source URL은 고정 fixture에 있다.

| 새 문서 요구 | primitive A/B | graph/retrieval/selection | complete / strict | first failing stage 및 직접 근거 |
|---|---|---|---|---|
| 삼성 p56 영업이익 2022년 ↔ 2023년 | 2022년/조원/43.4는 있음. 2023년/조원/6.6은 없음. native는 두 기간 모두 잘못된 `원`을 저장 | 잘못된 단위 `원`의 native 두 primitive를 graph가 연결하고 pack 선택 | **true / 실패** | **unit association**, 후속 primitive validation도 원문 compound unit을 놓침. `조 원` 두 token 중 suffix `원`만 unit으로 선택. Paddle는 영업이익/조원/43.4/6.6을 모두 정확히 인식했지만 마지막 cell bbox가 value region을 충분히 감싸지 않아 2023 후보가 제외됨(**cell geometry**). 원문 6.6을 교정·추정한 것이 아니다. |
| 현대차 p97 연결 기준 영업이익률 2022 ↔ 2023 | 둘 다 없음. 원문 및 Paddle words에 6.9/9.3/%가 정확히 있음 | 필요한 primitive graph 없음, pack 없음 | false / 실패 | **row grouping → metric association → primitive construction**. native 표의 merged section `재무성과` 아래 연결/별도·영업이익률 행을 logical metric으로 복원하지 못했고 저장 6 facts는 모두 `재무성과`. Paddle words는 있지만 유효 decoded table이 없음. OCR 수치 인식 실패로 뭉뚱그리지 않는다. |

**기존 네 질문 false-complete 0은 유지되지만 새 unseen에는 false-complete 1건이 있다.** 이것을 숨기거나 기존 지표와 합쳐 0이라고 표현하지 않는다. Graph의 `validated`는 현재 source/cell validator 통과를 뜻하며 OCR 또는 unit association 자체의 완전한 정확성 보증이 아니다. 새 문서에서 production 로직을 다시 조정하지 않았고 최초 freeze의 39 production 파일 hash가 여전히 동일하다. 일반화/전체 완료 조건은 미달이다.

다음 단 하나의 병목은 **cell-local compound unit 전체를 복원하고 validator에서 suffix unit만 선택하는 경우를 거부하는 것**이다. SK 금액 단위를 크기로 추정하거나 OCR/전역 cutoff를 튜닝하는 작업으로 넘어가지 않는다. 그 다음에만 merged logical metric/header 복원을 별도 실험으로 다룬다.

### Reproducibility note

개발 run1/run2의 단독 manifest 검증과 성능은 모두 통과했지만 working-tree hash(개발 중 docs/평가 script 변경)가 달라 `compare_runs`는 두 실행 비교를 **FAIL** 처리했다. 검증기를 완화하지 않았다. 최종 수정/원문 fixture/감사 내용을 고정한 상태에서 다시 두 실행을 수행하며 원래 manifest를 그대로 검증한다.

최종 고정 개발 run3/run4는 원래 pinned 검증기의 `compare_runs`와 binding 검증을 그대로 통과했다. evaluation working-tree hash `c56d9464a58f1aa07ecfedac0a274645a01a3329f20e0d6ba0c254a665d5ee41`가 같고 manifest/top-5/evidence pack/source spans/판정도 동일하다. 후보 pack **10/10**, 대조군 **2/2**, 참고 합계 **12/12**, 복합 coverage **1/1**, single-fact 회귀 **0**이다. `graph-dev-run3/4-20261002.json`, `graph-dev-final-metrics-20261002.json`, `graph-dev-final-binding-20261002.json`에 남겼다. 개발 중 hash가 달랐던 run1/run2를 재현성 통과로 소급하지 않는다.

신규 두 문서도 동일 원시 관찰의 두 graph 검색 cases(search/pack/span/판정 포함)가 일치했다(`graph-new-search-repeat-20261002.json`). 고정 fixture SHA-256은 `93cd5cd114e722ce716619cde1b96eb9e46f8d74d615f8720235ea61c3a39990`이고 실행 전후 동일하다. 두 실제 Paddle 출력 fingerprint도 `graph-new-worker-20261002.json`의 fingerprint와 일치한다. 이 신규 결과는 개발 점수와 합산하지 않는다.

### QA / Data protection / Remaining

`./scripts/check.sh` 최종: backend **316 passed/1 skipped**, frontend **7 passed**, lint·production build 통과. `git diff --check`, `docker compose build` 및 `docker compose up -d` 통과. backend/PostgreSQL/OCR worker healthy, `/health`는 `{"status":"ok"}`, frontend HTTP **200**. 로그는 `graph-full-check-20261002.log`, `graph-compose-build-20261002.log`, `graph-compose-up-20261002.log`이다. source/matcher/table candidate/pack API 메타데이터에 대해서만 수정했고 parser·OCR·청킹·bge-m3·RRF 상수·후보 cutoff는 그대로다. 생성 LLM 호출 **0**, DB migration/active 전환/업로드/기존 PDF 또는 벡터 삭제 **0**.

활성 snapshot은 변경 전/최종 배포 후/개발 평가 전후 모두 동일하다. documents **10** (`90a528749fa287d8614fe5383fa6c8a37f67498e778206108d5796860565f8b4`), pages **75** (`1cf7866151671415c87cc90b8a439c48969ebdc7a95611ba289fc041179cb575`), chunks·vectors **231** (`bce2ec67ef0b99dca798891b76998fedc9cbbe969c01a749906619198033bf0e`); analysis_runs와 page_extractions도 동일하다. 최종 snapshot은 `graph-active-final-20261002.json`이다. 새 PDF는 gitignore 확인된 results 경로에만 있다.

재현 명령(출력 경로는 아직 존재하지 않는 이름을 사용):
```bash
.venv/bin/python scripts/audit_primitive_graph.py --cases evals/extraction-unseen-table-cases.json --observations evals/results/paddle/graph-before-tables-20261002.json --output evals/results/paddle/graph-existing-replay.json
.venv/bin/python scripts/audit_primitive_graph.py --cases evals/primitive-graph-unseen-cases.json --observations evals/results/paddle/graph-new-observations-20261002.json --output evals/results/paddle/graph-new-replay.json
```
두 명령은 localhost PostgreSQL/bge-m3가 필요하며 원문 관찰·gold hash를 유지하는 메모리 평가다. OCR·생성·DB ingestion을 실행하지 않는다. 신규 PDF 관찰의 새 추출이 필요할 때만 `audit_new_cells.py --cases evals/primitive-graph-unseen-cases.json --pdf-dir evals/results/paddle/graph-new-pdfs --output <새 결과 경로>`를 실행한다.

남은 최초 실패: 기존 valuation **requirement matching**, 기간 없는 counts **period association/header**, SK **unit validation**(안전한 보류), 신규 삼성 **unit association + cell geometry/primitive validation**(새 false-complete **1**), 신규 현대차 **row grouping/metric association/primitive construction**. OCR 숫자 자체를 graph로 수정하지 않았다. 정확한 requested pair graph는 구현·회귀 검증했지만 신규 문서 precision gate는 **실패**이며 일반화 완료/활성 promotion을 주장하지 않는다. 다음 한 단계는 위에서 기록한 compound unit의 전체 source span 및 suffix-only reject 검증이다.

## Compound unit precision gate (2026-10-06)

1. **False-complete:** 기존 회귀 네 사례 **0→0**, 신규 문서 두 사례 **1→0**. 삼성은 잘못된 `원` fact가 `unit_suffix_conflict`로 거부되어 `coverage_complete=false`, 현대차도 false 유지다. 신규 문서 strict는 **0/2 유지**다. 원시는 `evals/results/paddle/unit-precision-final-20261006.json`, 요약은 `evals/unit-precision-reviewed.json`이다. 이 평가는 immutable 원문/manifest와 기존 BM25/vector 순위의 **검증·selection 재생**이며 새 retrieval/임베딩/DB 재검색이 아니다.
2. **삼성 p56 원문 위치:** 2022년 값 `43.4`, char `[444,448)`, bbox `[320.474457,101.289589,334.021698,111.182091]`; 2023년 값 `6.6`, char `[600,603)`, bbox `[398.654449,101.289589,408.194458,111.182091]`. 전체 단위 `조 원`, char `[31,34)`, 두 native word bbox의 union `[162.471924,101.289589,176.849426,111.182091]`. 기존 선택은 `원`, char `[33,34)`, bbox `[170.474426,101.289589,176.849426,111.182091]`였다. full compound와 suffix span/bbox가 겹쳐 두 값 모두 거부한다. `조 원→원` 보정이나 숫자 추정은 없다.
3. **정상 단위:** 같은 셀의 단일/분할 token `1.2조 원`은 전체 surface `조 원`, canonical `조원`으로 승인한다. `억원`, `천원`, `%`의 정상 연결, 원문 value suffix, 검증된 동일 열 header와 metric 셀의 `(십억원)` row 선언을 유지한다. 다른 행/값 열·불명확 header·merged unit/value cell은 보류한다. bbox는 관측 word box이며 글자별 좌표를 추정하지 않는다. 최종 target **97 passed**. 기존 comparison의 중첩 metadata 호환성 회귀는 발견·수정했고 bbox 위변조 차단 테스트도 유지한다.
4. **개발 세트:** 원래 manifest를 검증한 frozen-rank 재생에서 후보 pack **10/10**, 보관된 활성 대조군 **2/2**, 참고 합계 **12/12**, POSCO 복합 coverage **1/1**, global top-5 **11/12**, 단일 사실 top-5 ID/quote/table evidence 회귀 **0**. 대조군 두 건은 immutable baseline을 보존했으며 live active 재검색으로 표현하지 않는다.
5. **Challenge set과 회귀 분리:** 이미 관찰한 추가 표 3개와 신규 문서 2개는 **5개 challenge set**이다. 현금흐름 pair complete/strict true; valuation complete false(requirement matching); counts는 기간 요구가 성립하지 않아 coverage null/strict false(period/header association); 신규 삼성·현대차 complete false/strict false. 기존 현대차·신용보증기금 회귀는 각각 complete/strict true 유지. 기아 complete true이며 기존 strict review의 narrative quote와 table source spans/bbox가 정확히 동일함을 확인했다(자동 strict는 원래처럼 `narrative_review_required`; 새 자동 성공으로 바꾸지 않음). SK는 complete false 유지다. 기아 기존 review 원시는 `selection-holdout-release-reviewed-20261002.json`이며 source artifact hash도 대조했다.
6. **Active 무변경 검증 한계:** 평가 코드의 DB/OCR/embedding/generator 호출은 0이며 원본 PDF·평가 vector index/manifest hash, UI/Compose 파일은 불변이다. **현재 PostgreSQL active hash 불변은 확인할 수 없습니다.** 실행 전 localhost PostgreSQL 연결이 거부됐고 최종 Compose 확인도 Docker daemon unavailable였다. 과거 artifact의 active hash 또는 빈 로컬 SQLite 파일 hash를 현재 PostgreSQL hash 증거로 사용하지 않는다. 서비스 시작·재처리·revision 전환은 하지 않았다.
7. **변경 범위:** `backend/app/unit_validation.py`, `structured_cells.py`, `numeric_evidence.py`, `extraction_provenance.py`, `fused_candidates.py`, `evidence_requirements.py`, `evidence_bundle.py`; `backend/tests/test_unit_validation.py`, selection fixture의 `test_evidence_bundle.py`; `scripts/audit_primitive_graph.py`, `scripts/audit_unit_precision.py`; `api-contract.md`, `acceptance.md`, `qa-rules.md`, 본 보고서, `evals/unit-precision-reviewed.json`. Paddle/native parser, OCR 설정/DPI, 청킹, bge-m3, RRF, top-k, primitive graph 연결 규칙, DB schema, UI는 변경하지 않았다. 기업·PDF·질문 ID·정답값에 따른 production 분기는 없다.
8. **남은 실패:** unit association/validation: SK 보류, 삼성 suffix 선택은 거부됨. cell geometry: 삼성의 올바른 2023년 Paddle value/unit 셀은 기존 bbox 문제로 부족함. row grouping·metric association: 신규 현대차 merged logical metric/header 연결 부족을 그대로 유지한다. valuation requirement matching과 counts period association도 이번 범위 밖의 기존 보류다. 최종 `./scripts/check.sh`: backend **334 passed/1 skipped**, frontend **7 passed**, lint/build 통과. `git diff --check` 및 신규 파일 whitespace 검사 통과. Compose health와 live PostgreSQL hash는 미검증이다.
9. **Sealed holdout:** 아직 보지 않은 서비스 범위의 증권사 리포트 또는 DART 문서 **2개 이상**을 새 sealed holdout으로 마련해야 한다. 이번에 다운로드하거나 새 기능을 구현하지 않았다. 관찰된 5개 challenge를 sealed holdout으로 재명명하지 않는다.
10. **다음 작업:** row grouping·metric association을 별도 범위로 다룬다. 이번 precision 수정의 결과를 OCR·검색·RRF 튜닝으로 보완하지 않는다. live active hash와 Compose health가 미확인인 상태에서는 전체 운영 검증 완료를 주장하지 않는다.
