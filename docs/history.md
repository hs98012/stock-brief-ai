# 날짜별 기록

README에서 옮긴 시점별 기록이다. `변경 파일 목록`, `검증 결과`, `다음 단계`는 2026-08-23 4차 단계 기준이며 현재 상태와 다를 수 있다. 이후 기록은 `docs/`의 날짜별 문서와 [`docs/plans/rag-보강.md`](plans/rag-보강.md)에 있다.

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

## 2026-09-22 실제 코드·실행 진단

[진단 보고서](../evals/audit-report.md), [고정 질문](../evals/audit-cases.json), [측정 명령](../scripts/audit_rag.py)을 참고한다. OCR은 새 적재부터 300dpi이며 기존 DB 원문·임베딩은 유지한다. BM25는 영속 인덱스를 별도 적재하지 않고 검색 시 필터된 청크로 재구성한다.
