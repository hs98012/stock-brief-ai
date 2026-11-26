# 현황 재확인 및 과제 ①~③ 조사 결과 — 2026-11-13

**판정: PARTIAL.** Claude Code 세션에서 기존 문서·코드·artifact를 대조하고 과제 ①~③을 조사했다. 기존 문서는 수정하지 않았으며, 이 문서가 기존 기록과 다를 때는 아래에 근거 artifact를 명시했다. 재개 기준 HEAD는 `28061c6`이고 커밋은 하지 않았다.

실행하지 않은 것: Gemini 등 외부 API 호출 0회, Production DB/volume 접속, migration, OCR·재임베딩, sealed holdout 재실행·재채점, gold/manifest 변경, 시스템 프로세스 종료.

## 1. 기존 문서와 실제 상태의 차이

| 항목 | 기존 문서 | 실제 확인 |
|---|---|---|
| Gemini 실호출 횟수 | 1회(HTTP 503), 이후 신규 승인 0회 | **2회.** 2026-10-14 19:38 KST에 2차 호출이 있었고 HTTP 504 DEADLINE_EXCEEDED로 실패 |
| 소비된 승인 | `f164640e…` 1개 | `f164640e…`, `fe9835b5-b3a8-40f9-9aed-23dc757505c7` 2개 |
| 재검증 결과 경로 | `gemini-live-revalidation-20261014/`는 실행 시에만 생성 | 이미 존재하며 2차 실행 기록이 들어 있음 |
| DB exit2 건수 | 마지막 1건만 기록 | 총 **8건** |
| `generation60s` 표기 | 저메모리 설정 항목 | timeout이 아니라 `keep_alive=60s`. Ollama 생성 timeout 기본값은 600초 |
| Gemini 모델 | 문서마다 3.7 또는 3.8 | 앱 기본값은 `gemini-3.7-flash`, 실호출 fixture는 `gemini-3.8-flash`. `.env`에 `GEMINI_MODEL` 키 없음 |

2차 호출 근거: `.e2e-persistent/service-quality/gemini-live-revalidation-20261014/{approved-consent,execution,response-body}.json`, `.e2e-persistent/provider-approval-consumption/fe9835b5-….json`. 요청 본문 해시, 모델, 재시도 0, fallback 없음은 1차와 동일하다. 소요 29.457초, 생성 결과 없음. 이 호출을 누가 승인했는지는 `approved-consent.json`의 서술 외에 **확인할 수 없습니다**.

그 밖에 E2E 컨테이너 로그에 문서에 없는 2026-10-14~10-18 기동·정상 종료 기록이 있고, 2026-10-22 22:37에 pytest 캐시가 갱신됐다. 수행 주체와 내용은 기록이 없다.

## 2. ① E2E DB worker exit2

**원인 UNKNOWN 유지. 2회 재현 시도에서 미재발.**

### 과거 8건 (KST)

| 시각 | PID | 당시 상황 |
|---|---|---|
| 10-12 22:57:28 | 2986 | 분석 실행 중(Ollama 생성 358초) |
| 10-12 22:59:51 | 3029 | 같은 실행 중 |
| 10-12 23:04:13 | 3267 | 분석 완료 후. `api.log`에 embedding-status 조회 실패 |
| 10-12 23:05:01 | 3291 | 위와 같음. recovery 도중 `issuing SIGKILL to recalcitrant children` |
| 10-12 23:06:35 | 3341 | 위와 같음 |
| 10-13 15:35:33 | 939 | 분석 실행 중(Ollama 생성 344초) |
| 10-13 15:37:32 | 1020 | 같은 실행 중 |
| 10-13 15:37:54 | 1031 | 같은 실행 중 |

분석 시작 시각은 `generated_at`에서 소요 시간을 뺀 추정이다. 근거: `optimization-db.log`, `db-resumed-final.log`, `system-safety-20261013/db-current.log`, `api.log`, `runs.json`, `browser-resumed-final.json`.

### 좁혀진 사실

- 8건 모두 로그가 `exited with exit code 2`다. 신호 종료(`terminated by signal 9`)가 아니므로 커널 OOM kill과는 로그 형식이 맞지 않는다. 기존 문서의 "개별 backend OOM을 배제할 수 없다"보다 좁힐 수 있다. 다만 PostgreSQL 로그 관례에 대한 해석이며 소스로 재확인하지 않았다.
- postmaster(PID 1)는 유지됐고 RestartCount 0, OOMKilled false다. 죽은 backend는 종료 전 로그를 남기지 않았다.
- 10-12에는 embedding-status가 chunk 583개를 벡터까지 읽는 쿼리가 실행 중이었다. 이 쿼리는 10-12 23:07에 count 쿼리로 수정됐으나 10-13에 수정된 코드로 3건이 재발했으므로 단독 원인이 아니다.
- 10-13 15:38 이후에는 swap이 8GB 가까이 오른 계측 실행에서도 재발이 없었다.
- 헬스체크(`pg_isready`, 2초 간격)는 매번 인증된 backend 세션을 만든다. 과거 로그의 "server process"가 API 연결인지 헬스체크 세션인지 구분할 근거가 없다.

### 재현 시도 (2026-11-13 19:47~19:50 KST)

조건: 저메모리 모드 없이 API(18002) 실행, 10-13과 같은 질문, JSON 엔드포인트 `/api/v1/analyses`, 3초 간격 embedding-status 폴링, 최대 2회. DB에는 `log_connections`, `log_disconnections`, 확장 `log_line_prefix`를 일시 적용했다가 원복했다.

| | 1회차 | 2회차 |
|---|---|---|
| 전체 | 96.9초 | 77.1초 |
| 결과 | completed, 호재2/악재0/citation2 | 동일 |
| DB exit2·recovery | 없음 | 없음 |

호스트: swap 사용 5.0→최대 9.15GB, 메모리 여유 최저 9%, load 최대 6.56. E2E PG는 70~155MiB, CPU 최대 26.7%. 실행 전후 pages/page_extractions/chunks/583 vectors 해시와 보호 파일 130개는 10-14 기준과 동일하다.

계획과 달라진 점: dev UI(13002)는 미리보기 실행기의 폴더 접근 권한 오류로 뜨지 않아 같은 요청을 curl로 대신 보냈다. 따라서 브라우저와 Next dev 서버의 메모리 부담은 재현되지 않았고, `qa-rules.md` 기준으로 이 2회는 브라우저 E2E로 계산하지 않는다. 문장 전체 기록과 Docker VM 커널 로그 수집은 하지 않았다.

### 미검증 단서: pgvector HNSW

`README.md`와 `backend/app/analysis_retrieval.py` 주석은 첫 커밋부터 "로컬 ARM Docker 환경에서 관찰된 pgvector HNSW backend-process 종료"를 피하려고 분석 경로가 인덱스 스캔을 끄고 정확 스캔을 쓴다고 기록한다. E2E DB에는 `ix_chunks_embedding_hnsw`(pgvector 0.8.6)가 있고, 일반 검색 경로는 이 회피 없이 HNSW를 쓴다. 10-12에는 장애 직전인 22:48~22:52에 검색 프로파일링이 실행됐다. 현재 통계상 HNSW 인덱스 사용 횟수는 0이며, 이 통계는 crash recovery 때 초기화된다.

이는 **가설**이다. 10-13의 3건은 생성 단계 도중이라 HNSW 질의와 시각이 바로 맞지 않는다. 검증하려면 HNSW를 쓰는 검색 경로를 반복 실행하는 재현이 필요하며 승인 대상이다.

Artifact: `.e2e-persistent/service-quality/exit2-repro-20261113/`.

## 3. ② latency/메모리

**안정화 미완료. 편차의 발생 단계와 구조적 원인 일부를 확인했다.**

같은 질문·프롬프트 1419토큰·출력 624토큰인 실행 5회:

| 실행 | 전체 | 검색·검증 | 모델 로드 | 프롬프트 처리 | 토큰 생성 | 속도 |
|---|---:|---:|---:|---:|---:|---:|
| 10-12 | 72.0초 | 24.5초 | 6.5초 | 6.5초 | 33.8초 | 18.5 t/s |
| 10-13 15:34 | 374.4초 | 26.0초 | 8.1초 | 8.0초 | 327.3초 | 1.9 t/s |
| 10-13 16:28 저메모리 | 119.6초 | 약 25초 | 6.5초 | 6.7초 | 75.1초 | 8.3 t/s |
| 11-13 19:47 | 96.6초 | 24.8초 | 7.4초 | 11.0초 | 52.7초 | 11.8 t/s |
| 11-13 19:49 | 77.0초 | 24.5초 | 6.4초 | 7.6초 | 38.3초 | 16.3 t/s |

- 고정 비용(검색·검증, 로드, 프롬프트 처리)은 약 38~43초로 안정적이다. 변동은 토큰 생성 한 단계에서만 나며 약 10배 차이다.
- **매 분석은 구조적으로 cold다.** Ollama 서버 로그에 따르면 검색 단계에서 `bge-m3`를 로드할 때 `gemma3:4b`가 `predicted to exceed available memory, evicting`으로 내려가고, 생성 단계에서 `gemma3:4b`(예측 3.8GiB)를 로드하려고 `bge-m3`를 내린다. 2회차는 1회차 종료 19초 뒤였고 서버 keep_alive가 5분인데도 로드에 6.4초가 걸렸다. keep_alive를 늘려도 warm 실행은 만들어지지 않으며, 기존 문서의 "warm 라벨 실행이 전부 cold"가 이것으로 설명된다.
- Ollama 서버 기본 context가 4096이라 저메모리 모드의 `num_ctx=4096`은 기본값과 같다.
- 토큰 생성 속도를 떨어뜨리는 요인별 비중은 여전히 **UNKNOWN**이다. 11-13에는 swap 9.15GB·여유 9%에서도 11.8~16.3 t/s가 나왔으므로 swap 사용량만으로는 설명되지 않는다.

### 검색·검증 단계 프로파일

분석 경로 근거 수집을 프로파일러와 함께 측정했다(45.2초, 실제 실행에서는 약 24.5초).

| 구간 | 시간 | 비중 |
|---|---:|---:|
| 저장 표 사실 재검증 실제 계산(8페이지) | 29.7초 | 66% |
| 캐시 적중 시 지문 계산·깊은 복사 | 약 5.5초 | 12% |
| DB 로드(8회 조회) | 4.6초 | 10% |
| 질의 임베딩 3회 | 1.3초 | 3% |

분석 1회가 하이브리드 검색을 3번 실행하고 `validated_stored_facts`는 56회 호출된다(48회 캐시 적중). 재검증은 질문과 무관하지만, 요청 간 재사용은 `api-contract.md`(검증 cache는 요청 내에서만 유지), `qa-rules.md`, 테스트가 금지한다.

### 구현한 변경 (미커밋)

한 요청 안에서 같은 페이지 객체의 지문을 한 번만 계산한다.

- `backend/app/verification_cache.py`: `object_fingerprint` 추가.
- `backend/app/extraction_provenance.py`: `validated_stored_facts`가 이를 사용.
- `backend/tests/test_verification_performance.py`: 테스트 2개 추가.

재사용 조건은 페이지·원문·추출 객체·provenance·사실 목록이 같은 객체이고, 식별 스칼라와 provenance 항목 수·사실 목록 길이가 같을 때다. 지문 입력과 캐시 키는 이전과 같고 요청이 끝나면 사라진다. **한계:** 같은 요청 안에서 provenance나 사실의 내부 값만 제자리에서 바꾸면 감지하지 못한다. 조회 경로에 그런 변경 코드가 없음을 확인했고, 추출 데이터를 변경하는 `index_admission.py`와 감사 스크립트는 요청 캐시 밖에서 실행된다.

측정(각 1회, 프로파일러 포함): 45.30→41.98초, CPU 41.14→37.87초, 지문 계산 2.94→0.56초. 근거 수집 결과 해시와 DB 스냅샷은 전후 동일하다. 프로파일러 없는 실제 단축과 반복 측정은 **NOT_MEASURED**다.

검증: 관련 14개 파일 192 passed, `./scripts/check.sh` backend 722/frontend 17/lint/build PASS, `git diff --check` PASS. 개발 12·selected 20·offline 17 회귀 재생은 실행하지 않았다.

### 채택하지 않은 것

- 캐시 반환값의 깊은 복사 생략: 대상 비용이 프로파일 기준 2.47초뿐이고, 얕은 복사 뒤의 중첩 구조 공유와 하위 코드의 제자리 변경 패턴 때문에 안전을 끝까지 증명하지 못했다.
- 요청 간 캐시, DB 저장, 재검증 알고리즘 최적화, 3회 검색의 후보 행 재사용은 착수하지 않았다.

Artifact: `.e2e-persistent/service-quality/evidence-analysis-path-20261113.*`, `evidence-analysis-path-step1-20261113.*`, `retrieval-dedup-20261113/check-step1.log`, `exit2-repro-20261113/run-timings-readonly.json`.

## 4. ③ Gemini 재검증

**NOT_VERIFIED 유지. 이번 세션의 실호출 0회, 신규 승인 0회.**

- 2차 실패(504)는 29.4초에 돌아왔다. 설치된 google-genai 2.18.1은 클라이언트 timeout을 `X-Server-Timeout` 헤더로 전달하고 실행기 timeout은 30초로 고정돼 있다. 따라서 Google이 30초 기한 안에 생성을 끝내지 못한 것으로 읽는 것이 기록과 가장 잘 맞는다. 실행 기록의 `timeout: false`는 클라이언트 쪽 timeout이 발동하지 않았다는 뜻이다. 끝나지 않은 이유는 **확인할 수 없습니다**.
- 동일 조건(같은 본문 해시 `ace5ad27…`, `gemini-3.8-flash`, 30초, 1회, 재시도 0) 재시도의 사전 점검을 마쳤다. 본문 3,350바이트와 해시, 실행기 고정값이 10-14과 같고, 새 결과 경로 후보 `gemini-live-revalidation-20261113/`는 비어 있다.
- 사용자가 호출을 **보류**했다. 과금 티어는 UNKNOWN이며 실패한 2회의 과금 여부도 알 수 없다.
- 다음 호출 전 필요한 것: 새 명시적 승인, 과금 티어 확인, 새 결과 경로, 기준 모델(3.7/3.8) 결정. 동일 30초 조건은 같은 이유로 다시 실패할 수 있다.

## 5. 이번 세션의 변경 사항

- 코드: 3절의 3개 파일(미커밋).
- DB: 격리 E2E DB의 `analysis_runs` 13→15행(재현 실행 2회분). 로그 설정 3건은 적용 후 `ALTER SYSTEM RESET`으로 원복했고 `postgresql.auto.conf` 잔여 항목은 0개다.
- 새 파일: `.claude/launch.json`(미리보기 실행 설정), 이 문서, 위 artifact.
- 프로세스: 이 세션에서 시작한 API(PID 5606)는 PID·부모·시작 시각·명령·포트를 대조한 뒤 종료했고, 멈춘 dev UI 시작 프로세스는 실행 도구의 핸들로 중지했다. 표본 수집기와 폴러는 정지 파일로 스스로 종료했다.
- `check.sh` 빌드가 바꾼 자동 생성 파일 `frontend/next-env.d.ts`는 실행 전 상태로 되돌렸다.
- Docker Desktop은 세션 중 이미 실행 상태였고(컨테이너 시작 19:38:23 KST), E2E PG와 다른 프로젝트 컨테이너 5개는 그대로 두었다.

## 6. 남은 과제

| 과제 | 상태 |
|---|---|
| ① DB exit2 | 원인 UNKNOWN. HNSW 단서 미검증 |
| ② latency/메모리 | 토큰 생성 편차 미해결. 검색 단계 지문 중복 제거만 구현 |
| ③ Gemini 재검증 | 보류, NOT_VERIFIED |
| ④ 새 PDF 브라우저 업로드 | 미착수 |
| ⑤ 배포 스트림 검증 | 미착수 |

답이 필요한 사항: 10-14 19:38 2차 호출의 승인 주체, Gemini 기준 모델, 이번 코드 변경의 유지 여부(위 한계 포함), `.claude/launch.json` 유지 여부.
