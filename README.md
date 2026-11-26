# Stock Brief AI

증권사 기업분석 리포트와 공시 PDF를 바탕으로 기업의 핵심 내용과 호재·악재를 원문 근거와 함께 확인할 수 있는 RAG 기반 분석 서비스다.

PDF에서 텍스트와 표 데이터를 추출하고, BM25와 벡터 검색을 결합해 관련 근거를 찾는다. 검색된 근거는 원문 PDF 페이지와 함께 제공하며, 필요한 근거가 부족하거나 값과 단위를 확인하기 어려운 경우에는 답변 생성을 제한한다.

증권사 기업분석 리포트 PDF와 DART 공시 PDF를 바탕으로 기업의 핵심 내용과 긍정·부정 요인을 초보자에게 근거와 함께 설명하기 위한 독립형 포트폴리오 프로젝트다. 모든 핵심 주장은 원본 파일명, 발행일, PDF 페이지 번호, 근거 문장을 요구한다. 투자 권유, 매수·매도 추천 및 자동매매는 범위 밖이다.

## 주요 기능

- 증권사 리포트와 공시 PDF의 텍스트·표 데이터 추출
- 스캔 페이지 OCR 처리
- BM25 + pgvector cosine + RRF 기반 하이브리드 검색
- 질문에 필요한 복수 근거 검색 및 coverage 검증
- 표의 행·열·헤더 구조 복원과 값·단위 검증
- 분석 결과별 원문 PDF 페이지와 인용 근거 제공
- 근거가 부족한 경우 불완전한 답변 생성 제한(`확인할 수 없습니다`)
- 기본은 로컬 Ollama 생성(`LOCAL_ONLY`), 외부 Gemini는 요청별 명시적 동의가 있을 때만 사용
- 개발 평가셋을 이용한 검색·근거 품질 회귀 검증

## 기술 스택

| 영역 | 기술 |
| --- | --- |
| Frontend | Next.js 16, TypeScript, Tailwind CSS |
| Backend | FastAPI, Python |
| Database | PostgreSQL 16, pgvector |
| Retrieval | BM25, Vector Search, RRF |
| Embedding | bge-m3 |
| LLM | Ollama `gemma3:4b`(기본), Gemini Flash(요청별 동의 시) |
| PDF / OCR | PyMuPDF, Tesseract, PaddleOCR PP-StructureV3(`ocr-worker`) |
| Infra | Docker Compose |

## 처리 흐름

```text
증권 리포트 / 공시 PDF
        |
        v
PDF 텍스트 추출
        |
        +------ 추출이 어려운 페이지 ------+
        |                                  |
        |                                  v
        |                                OCR
        |                                  |
        +---------------+------------------+
                        |
                        v
                페이지 / 표 구조 처리
                        |
                        v
                    Chunk 생성
                        |
                        v
             PostgreSQL + pgvector
                        |
             +----------+----------+
             |                     |
             v                     v
           BM25               Vector Search
             |                     |
             +----------+----------+
                        |
                       RRF
                        |
                        v
              Evidence Requirement
                        |
                        v
               Evidence Bundle
                        |
                        v
                 LLM 분석 생성
                        |
                        v
             답변 + 원문 페이지 근거
```

단계별 코드 위치, 설계 결정과 알려진 한계는 [`docs/architecture.md`](docs/architecture.md)에 정리했다.

## 개발하면서 해결한 문제

### 1. 스캔 페이지와 표에서 필요한 근거가 검색되지 않는 문제

초기에는 PDF에서 추출한 텍스트를 그대로 청크로 나누어 검색에 사용했다. 일반 문장은 비교적 잘 추출됐지만 스캔 페이지와 복잡한 표에서는 수치나 문장이 빠지면서 실제 PDF에 있는 근거가 검색 결과에서는 나타나지 않는 경우가 있었다.

원문 PDF, 추출 결과, 생성된 청크와 검색 결과를 페이지 단위로 대조해 어느 단계에서 근거가 사라지는지 확인했다.

기본 텍스트 추출이 어려운 페이지에는 OCR을 적용하고, 페이지마다 처리 결과와 오류를 별도로 기록했다. 한 페이지 처리에 실패해도 전체 문서 적재가 중단되지 않고 다음 페이지를 계속 처리하도록 구성했다.

표는 일반 문장과 같은 방식으로 처리하면 행·열 관계와 단위가 사라지는 문제가 있어 별도의 표 처리 로직을 추가했다. 이후 셀, 행, 헤더와 단위를 연결해 수치가 어떤 지표와 기간에 해당하는지 확인할 수 있도록 개선했다.

### 2. 의미가 비슷한 문장은 찾지만 정확한 수치 근거를 놓치는 문제

벡터 검색만 사용할 경우 질문의 의미와 비슷한 문장은 찾을 수 있었지만 `2026F 영업이익`, `2Q26F`처럼 정확한 표현과 수치가 중요한 질문에서는 필요한 근거가 상위 검색 결과에 포함되지 않는 경우가 있었다.

기업 리포트 질의는 의미적 유사성과 함께 정확한 기업명, 지표명, 기간 표현이 중요하다고 판단했다.

따라서 BM25 키워드 검색과 pgvector cosine 기반 벡터 검색을 함께 실행하고 RRF로 순위를 결합하는 하이브리드 검색 구조로 변경했다.

이를 통해 정확한 표현이 필요한 표·수치 근거와 의미적으로 연관된 서술 근거를 함께 검색할 수 있도록 했다.

### 3. 하나의 질문에 필요한 근거가 여러 개인 경우 일부만 검색되는 문제

단일 근거만 필요한 질문과 달리 일부 질문은 여러 페이지나 서로 다른 형태의 근거가 함께 필요했다.

예를 들어 POSCO 관련 평가에서는 한 페이지의 전망 서술과 다른 페이지의 `2Q26F 영업이익 424십억원` 표 수치(원문 값, 고정 개발 질문 `evals/audit-cases.json`)가 함께 있어야 질문을 충분히 설명할 수 있었다.

검색 결과에 관련 문장이 하나 포함됐다는 이유만으로 답변을 생성하면 필요한 근거 일부가 빠진 상태에서도 완성된 답변처럼 보일 수 있었다.

이를 해결하기 위해 질문별로 필요한 근거 조건을 정의하는 `evidence_requirements.py`와 검색된 근거를 묶어 충족 여부를 확인하는 `evidence_bundle.py`를 추가했다.

복수 근거가 필요한 평가 케이스의 coverage@5는 `0/1`에서 `1/1`로 개선됐다(고정 개발 세트의 POSCO 복합 질문 1건, bge-m3 + hybrid RRF, 생성 호출 없음. 출처 `evals/audit-report.md` 2026-09-30 evidence-bundle 절).

### 4. 검색된 숫자의 값은 맞지만 단위를 신뢰할 수 없는 문제

표에서 숫자를 찾았더라도 해당 숫자의 단위가 어느 행이나 열에 적용되는지 명확하지 않은 경우가 있었다.

SK하이닉스 문서에서는 행·열 구조 자체는 복원했지만 서로 다른 단위가 혼합된 표에서 특정 수치의 단위를 안정적으로 연결할 수 없었다.

이 경우 수치를 추측해서 답변하지 않고 근거 사용을 보류하도록 했다.

`structured_cells.py`와 `paddle_tables.py`에서 셀·행·헤더 단위 연결과 검증을 보완했으며, 값뿐 아니라 해당 값의 지표, 기간, 단위를 함께 확인할 수 있을 때만 표 근거로 사용하도록 했다.

### 5. 일부 근거만으로 답변이 완성된 것처럼 생성되는 문제

초기 평가에서는 필요한 근거를 모두 확보하지 못했는데도 모델이 답변을 완성하는 false-complete 사례가 있었다.

현대차와 기아 사례를 원문과 대조하면서 검색 결과 존재 여부만으로는 답변 가능 여부를 판단할 수 없다는 것을 확인했다.

질문별 필수 근거와 실제 검색된 evidence bundle을 비교하고, 요구사항을 충족하지 못하면 해당 내용을 생성하지 않도록 검증 단계를 추가했다.

false-complete는 기존 회귀 네 사례에서 `0 → 0`, 신규 문서 두 사례에서 `1 → 0`이 됐다(evidence bundle의 `coverage_complete` 판정, 생성 호출 없음. 출처 `evals/audit-report.md` 2026-10-06 compound unit precision 절).

## 품질 결과

### 근거 검증 개선 (2026-09~10, 개발 세트)

현재는 단순히 검색 결과가 존재하는지를 보는 것이 아니라 실제 PDF 원문에서 필요한 근거를 다시 확인할 수 있는지를 기준으로 평가하고 있다.

| 평가 항목 | 이전 (전역 top-5) | 현재 (evidence pack) |
| --- | ---: | ---: |
| 재처리 대상 근거 검증 | 9/10 | 10/10 |
| 활성 대조군 | 2/2 | 2/2 |
| 참고 합계 | 11/12 | 12/12 |
| 복합 근거 coverage@5 | 0/1 | 1/1 |
| False-complete (기존 회귀 4 / 신규 문서 2) | 0 / 1 | 0 / 0 |

측정 조건: 고정 개발 세트 11질문 / 12근거 단위(`evals/audit-cases.json`, `evals/pinned-gold.json`), bge-m3 임베딩과 hybrid RRF 검색, 생성 모델 호출 없음. 출처는 `evals/audit-report.md`의 2026-09-30 evidence-bundle 절이며 False-complete 행만 2026-10-06 compound unit precision 절이다. 튜닝에 쓴 개발 세트 수치이므로 일반화 성능이 아니다.

모든 문서를 성공으로 처리하는 것을 목표로 하지 않는다. 값이나 단위를 원문에서 확실하게 확인할 수 없는 경우에는 답변에 사용하지 않는 것을 우선한다.

현재 SK하이닉스 혼합 단위 표는 구조 복원까지는 가능하지만 unit association을 안정적으로 검증하지 못해 보류 상태로 두고 있다.

### RAG 보강 평가 (2026-11, dev 기준)

면접 대비 보강 플랜([`docs/plans/rag-보강.md`](docs/plans/rag-보강.md))에서 평가셋을 dev/test로 나누고 검색 방식(BM25 / vector / hybrid RRF / 승격 포함), 한국어 토큰화, 청킹 크기, RRF 가중치를 비교했다. 수치와 측정 조건, 채택·미채택 이유는 [`docs/architecture.md`](docs/architecture.md)의 평가 절에 출처 단계와 함께 정리했다.

생성 근거 충실도 (2026-11-26, 플랜 6단계):

| 항목 | 결과 |
| --- | ---: |
| citation 유효율 (저장된 페이지 원문 범위와 일치) | 16/16 |
| 근거 부족 케이스 올바른 거절 | 5/5 |
| 답변 가능 케이스 잘못된 거절 | 4/12 |
| 실패 단계 (검색 / 생성 / 인용) | 7 / 0 / 0 |

측정 조건: 삼성전자 증권사 리포트 5개, 17케이스(답변 가능 12, 근거 부족 5, `evals/fixtures/`), Ollama `gemma3:4b`, `LOCAL_ONLY`, fallback 꺼짐, 1회 실행. fixture 3문항이 dev셋과 겹치므로 dev 기준이다. 출처 `docs/plans/rag-보강.md` 6단계.

## 평가 방식

평가용 질문마다 실제 PDF를 확인해 기대 근거를 미리 정의한다.

검증 과정에서는 다음 항목을 확인한다.

- 필요한 내용이 검색 후보에 포함되는지
- 필요한 페이지가 Top-K에 포함되는지
- 복수 근거가 필요한 경우 모든 조건을 충족하는지
- 표 수치의 지표·기간·값·단위를 확인할 수 있는지
- 생성된 내용이 실제 검색 근거와 연결되는지
- 근거가 부족한 질문에서 내용을 임의로 생성하지 않는지

실패 원인은 검색과 생성 단계를 구분해 확인한다.

```text
retrieval_candidate_excluded
검색 단계에서 필요한 근거가 후보에 포함되지 않은 경우

analysis_filter_excluded
기대 페이지의 문장이 분석 필터(품질·관점·질문 단어)에서 제외된 경우

retrieval_wrong_perspective
근거는 검색됐지만 질문에서 필요한 관점으로 분류되지 않은 경우

generation_not_selected
필요한 근거가 모델에 전달됐지만 답변 생성에 사용되지 않은 경우

output_validation_removed
모델이 선택한 내용이 근거 검증 과정에서 제거된 경우
```

검색 결과와 최종 답변만 비교하지 않고 어느 단계에서 근거가 누락됐는지를 확인할 수 있도록 평가 구조를 만들었다.

## 빠른 실행

Docker와 Docker Compose가 필요하다.

```bash
cp .env.example .env
docker compose up --build
```

실행 후 다음 주소에서 확인할 수 있다.

```text
Frontend    http://localhost:3000
Backend     http://localhost:8001
API Docs    http://localhost:8001/docs
PostgreSQL  localhost:5432
```

임베딩과 기본 분석 생성은 맥 호스트 Ollama를 사용한다.

```bash
ollama pull bge-m3
ollama pull gemma3:4b
```

기본 요청은 `execution_mode=LOCAL_ONLY`이며 외부 Gemini는 `.env`의 `ANALYSIS_EXTERNAL_ENABLED=1`과 요청별 명시적 동의가 모두 있을 때만 호출한다. API 키 등 실제 환경값은 `.env`에만 저장하며 저장소에는 포함하지 않는다.

전체 테스트와 정적 검증, RAG 평가셋 실행:

```bash
./scripts/check.sh
python3 scripts/evaluate.py
```

평가 fixture에는 실제 문서 UUID를 저장하지 않고 파일명, 기업명, 발행일과 문서 유형을 기준으로 문서를 찾는다.

검색과 생성 결과는 실제 PDF 원문 페이지와 대조해 평가한다.

env 전체 설명, Ollama 설치 전후, 마이그레이션, PDF 적재, 검색·분석 수동 검증 curl, fixture 추가 절차는 [`docs/local-setup.md`](docs/local-setup.md)에 있다.

## 상세 문서

README에는 프로젝트의 전체 흐름과 주요 문제 해결 과정을 정리하고, 세부 구현 내용은 별도 문서로 분리했다.

- `api-contract.md` — API 요청·응답 구조
- `acceptance.md` — 기능 및 품질 완료 기준
- `qa-rules.md` — 인용, 근거 및 분석 결과 검증 규칙
- `product.md` — 서비스 화면과 사용자 흐름
- `AGENTS.md` — 개발 원칙과 데이터 모델 계약
- [`docs/local-setup.md`](docs/local-setup.md) — 저장소 구조, 자세한 실행·검증 절차
- [`docs/architecture.md`](docs/architecture.md) — 파이프라인, 설계 결정, dev/test 검색 평가 결과와 알려진 한계
- [`docs/plans/rag-보강.md`](docs/plans/rag-보강.md) — 2026-11 RAG 보강 플랜과 단계별 측정 기록
- [`evals/audit-report.md`](evals/audit-report.md) — 2026-09~10 실제 코드·실행 진단과 품질 개선 기록
- [`docs/history.md`](docs/history.md) — README에서 옮긴 날짜별 기록(2026-08-23 4차 단계, 2026-09-22 진단)
