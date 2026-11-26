# LLM provider 실행 전략·서비스 검증 — 2026-10-13

**구조 구현·동의/모의 검증 완료. 실제 외부 성능은 NOT_VERIFIED.** 이번 작업은 실제 Gemini 요청0회, 실제 Ollama 생성0회다. 기존108~304초 로컬 측정과119.608초 최종 분석 기록을 보존했다. 외부 성능이 빨라졌다고 주장하지 않는다. Production DB와 sealed holdout을 변경하지 않았다.

## 1. 기존 provider 구조

기존 factory는 환경변수로 Gemini(default) 또는 Ollama를 선택하고 optional Gemini→Ollama fallback을 구성했다. 요청별 동의가 없어 키/환경 설정만으로 외부 adapter가 선택될 수 있었다.

Gemini 모델 기본 ID는 `gemini-3.7-flash`, Ollama는 `gemma3:4b`, 임베딩은 기존 `bge-m3`다. Gemini ID는 [공식 모델 문서](https://ai.google.dev/gemini-api/docs/models/gemini-3.7-flash)에서도 확인했다. 키별 실제 이용 가능 여부는 호출하지 않아 NOT_VERIFIED다. 모델을 임의 업그레이드하지 않았다.

기존 stateless GenerateContent·JSON schema·retry/fallback·factual validation을 재사용했다. 호재/악재는 하나의 prompt packet으로 generate1회 성공 호출이다. SDK attempts1은 최초 요청을 포함하며 application retry가 기본 최대2회다. 429/500/502/503/504·network·timeout만 retry/fallback 대상이고, 인증/설정/404/safety/JSON/schema/citation 오류는 fallback으로 숨기지 않는다. Ollama fallback은1회다.

Gemini timeout 기본30초/attempt, 현재 루트 `.env`에는45초/attempt·최대2회가 설정돼 있다. 실제 프로세스 적용값은 서버 실행 환경에 달려 있으며 이번에는 실 호출하지 않았다. 기본 retry delay1초 exponential backoff, Ollama timeout600초를 유지한다. 이 수치는 전체 요청의 엄격한 wall-clock deadline을 의미하지 않는다.

## 2. 구현·변경 파일

- Backend: `app/schemas.py`, `generation.py`, `analysis_service.py`, `main.py`; 신규 `tests/test_provider_consent.py`, 기존 `test_analysis.py` 계약 보완.
- Frontend: `app/page.tsx`, `types.ts`, `api.ts`, `analysis-view.tsx`, `api.test.ts`, 신규 `provider-consent.test.tsx`.
- Config: `.env.example`, `docker-compose.yml`, `scripts/run_service_e2e_api.py`, `.gitignore`, frontend `eslint.config.mjs` 및 Next build가 갱신한 `tsconfig.json`/`next-env.d.ts`의 생성 타입 경로.
- Docs: README, api-contract, acceptance, qa-rules, 이 보고서와 checkpoint.

DB migration/모델 변경 없음. 기존 dirty tree·RAG 검색/RRF/기존 품질 코드를 보존했다. build용 `.next-provider`를 git/lint 생성물 제외 목록에 추가했다. 이전 E2E/check 생성물 제외는 유지한다.

## 3. 외부 전송 동의

| 요청 모드 | 실제 선택 | 요청 동의 | 서버 정책 |
|---|---|---|---|
| LOCAL_ONLY(default) |Ollama|false|외부 정책 불필요|
| EXTERNAL_WITH_CONSENT |Gemini|strict true|ANALYSIS_EXTERNAL_ENABLED=1|
| FALLBACK_ALLOWED |Gemini, transient 실패 시 Ollama|strict true, fallback도 선택|external=1 및 ANALYSIS_OLLAMA_FALLBACK_ENABLED=1|

두 서버 flag는 default0이며 실제 `.env`를 수정하거나 외부 정책을 활성화하지 않았다. API 키·기존 ANALYSIS_LLM_PROVIDER/ANALYSIS_LLM_FALLBACK_PROVIDER는 동의를 부여하거나 기본 LOCAL_ONLY를 바꾸지 않는다. 기존 local E2E launcher는 두 정책 flag를0으로 고정한다.

미동의/문자열 true/숫자1 등은422, 서버 정책·provider 불일치·금지 fallback은403으로 차단한다. factory 및 서비스 계층이 확인하며 run 생성/검색/외부 호출보다 먼저 검사한다. Dependency override나 direct analyze_document 호출도 동의 경계를 우회하지 못하도록 검사한다.

동의 범위는 이번 document_id/question/검색된 검증 evidence packet 및 설정된 retry다. UI는 문서·질문·모드·메타데이터 변경 후 동의를 해제하고, 제출 시 소비한다. 실패 후 새 요청도 다시 동의해야 한다. API의 boolean은 요청별 선언이며 사용자 인증·서명된 동의 증명·재사용 토큰은 아니다.

Gemini 전송 내용: 질문, 기업명/종목코드/문서 유형/발행기관/날짜, 선택된 검증 원문 발췌·페이지·청크 UUID·section·사실 수치/기간/단위/범위/추정·실제 구분, system/분석 지시문과 출력 schema. PDF/이미지/embedding/전체 provenance·geometry proof graph는 보내지 않는다. 선택 발췌의 민감 정보가 익명화된다고 주장하지 않는다.

`execution` 메타데이터는 requested_mode/consent/external_request_attempted/final_provider/fallback_used를 기존 analysis_runs.result JSON에 저장한다. 과거 결과는 execution=null을 허용해 옛 동의를 추측하지 않는다. 요청 시도는 외부 서버 수신 증명이 아니다. LLM 전 HOLD면 final_provider=null/attempted=false다.

## 4. Gemini mock 검증

실제 설치 SDK + httpx.MockTransport에서 success/schema/usage/safety, 429/500/502/503/504의 application2/HTTP2를 재확인했다. SDK 중첩 retry를 재도입하지 않았다. 기존 fake SDK client로 timeout/network retry와 분류도 검사했다. 실제 Google 네트워크 요청은 없다.

신규 API 검사: JSON/stream에서 동의 누락 시 Gemini adapter 구성0/run0, 서버 정책 off면 calls0/run0, local request에 Gemini provider를 주입하면403. 외부 provider 응답도 똑같은 schema/citation/card 검증을 통과해야 한다.

Focused backend 결과는 **87passed**이며 기존 analysis·transport 검사와 신규 consent 검사를 포함한다. `targeted-final.log` 참조.

## 5. Ollama fallback 검증

기존 mock Gemini timeout/network/rate limit/transient retry 소진 후 mock Ollama generate1회, 성공 시 fallback0회, schema/safety/auth/citation 실패 시 fallback0회를 유지했다. 별도 API stream test에서 요청 FALLBACK_ALLOWED 및 server policy를 둘 다 허용한 경우만 fallback status→검증→결과가 발생한다. 하나의 analysis_run에 final Ollama/fallback=true를 기록한다.

이는 mock adapter 검증이다. 이번 작업에서 실제 gemma3:4b 생성 또는 실제 Gemini→Ollama fallback을 실행하지 않았다.

## 6. Provider별 출력 정확성

LOCAL_ONLY/mock Gemini/mock fallback 모두 같은 검증 pipeline을 사용한다. 동일 synthetic DB 원문을 사용하는 API mode tests에서 citation quote가 동일하고 호재 카드가 원문에 grounding되며 임의999 수치가 최종 summary/card/citation에 남지 않는 것을 확인했다. 외부 출력을 이유로 source/period/unit/scope 검증을 완화하지 않았다.

호재/악재 최대3, UUID candidate membership, polarity, 원문 literal spans·source ownership, 사실 중복 제거·기간/단위/범위·HOLD 계약은 기존 code/tests를 유지한다. 모든 mode의 ambiguous requirement는 정확히 `확인할 수 없습니다`/HOLD이고 provider calls0이다. 출처 UUID가 잘못되면502로 실패하며 다른 모델로 다시 생성하지 않는다.

## 7. Browser UI

실제 Chrome 브라우저 + 별도 build `.next-provider`/localhost13004에서 **명시적 UI MOCK** fixture를 사용했다. Fixture는 기존 실제 accepted run의 quote/citation/image를 표시하며 DB·키·Gemini·Ollama에 접속하지 않는다. API18004는600초 후 자신의 server.should_exit로 종료하며 시스템 프로세스에는 신호를 보내지 않는다.

관측 완료: 기본local, 외부 동의 전 버튼 disabled, 전송 범위 표시, 질문 변경 후 consent=false, 제출 후 consent=false, local 생성/external 생성/fallback/사실·citation 검증/완료/HOLD/실패. 오류 화면에는 결과 카드가 남지 않는다. fallback 안내는 검증 중에도 유지되고 완료 결과에도 표시된다.

Mock UI에서 citation2/bbox9/원문 이미지2 loaded를 관측했다. 실제모델 E2E 성공이나 새로운 citation 생성으로 계산하지 않는다. 브라우저 DOM 상태 기록은 browser-local/external-mock/fallback-mock/hold-mock/error-mock.json이다. 5개의 mock 요청 모드·동의는 browser-requests.jsonl에 남고 실제 외부 전송은0회다.

UI는 NDJSON lifecycle만 읽는다. 미검증 모델 텍스트/token streaming은 없다. stream은 독립 worker Session을 사용해 요청 read connection을 먼저 반환한다. 중간 schema/citation 오류는 safe error event이며 최종 verified result를 보내지 않는다. 연결 종료는 이미 실행된 모델 호출을 취소하지 않으므로 재접속 시 자동 재요청하지 않는다.

## 8. 성능 비교 가능 여부

| 항목 | 결과 |
|---|---|
| 기존 local 반복 기준 |108.706~304.054초, 보존|
| 기존 최종 질문 local |119.608초, 보존|
| 신규 local latency |NOT_MEASURED, 반복 생성0회|
| 실제 Gemini latency/정확성 |NOT_VERIFIED, 별도 명시적 승인 필요|
| 실제 external→local fallback latency |NOT_VERIFIED|

Mock fixture의 단계 대기나 unit test 실행시간을 provider latency로 계산하지 않는다. 외부 속도 개선·원인 해결 주장은 없다.

## 9. Regression

최종 `./scripts/check.sh`: **backend700/frontend17/lint/build PASS**,22warnings. Focused backend87 PASS. 처음695/17 검사도 통과했으나, 후속 검사에서 새 `.next-provider` 생성물을 lint가 소스로 검사해 실패했다. 생성 directory만 추가 제외한 뒤700/17 전체 검사를 다시 통과했다. 소스/테스트를 생략하지 않았다. `check-accepted.log`가 최종이다. `git diff --check` PASS.

Offline Hyundai/Samsung17/17 재실행 결과가 이전 JSON과 동일하다. 기존 audit-only cache wrapper를 새 artifact directory에 복사해 재사용했다. Latest challenge5를 현재 validator로 replay했다. 전체20 selected pack/coverage/strict state 비교도 동일하며 fixed15는 기존 결과 재사용임을 구분한다. Review-aware false-complete는 기존 manual review 정책을 적용해 다시 계산하여0. Kia REVIEW, SK/Counts HOLD 유지. Sealed 재실행 없음.

## 10. 데이터 무결성

고정 E2E DB READ ONLY + database/user guard로 시작/종료 snapshot 비교: source/pages/page_extractions/chunk UUID/provenance 및 embedding hash unchanged,583 finite/nonzero vector(1024),missing0. 기존 accepted run result JSON unchanged. 현재 validator로 citation2/source_boxes9의 trusted literal span·chunk coverage·supported_claim도 재확인했다.

Sealed114파일 SHA256/immutable flags 시작/종료 unchanged. gold/first-run 재채점·봉인 변경 없음. Production DB/volume 접근·migration·OCR·재임베딩 없음. macOS 프로세스 종료·재시작 명령0회. DB 과거 exit2 원인은 여전히 UNKNOWN이며 이번 기능 작업으로 해결됐다고 주장하지 않는다.

## 11. 미검증 항목

실 Gemini access/timeout/retry/fallback/latency/응답 정확성, 실제 외부 호출을 사용하는 브라우저 E2E는 NOT_VERIFIED. 8GB Ollama 편차/메모리 문제는 해결하지 않았다. Streaming 경로는 로컬/mock 기능 검증이며 배포 reverse proxy의 장시간 buffering/disconnect 동작은 미검증이다. 이전 새 PDF upload/citation 새 탭 navigation 제한도 유지한다.

## 12. 다음 작업

실제 비교는 문서·질문·전송할 verified packet·모델·retry/timeout 및 비용 범위를 먼저 고정한 뒤 별도 명시적 승인에서1회의 Gemini 분석으로 시작한다. 승인 전에는 서버 flag를 켜거나 실 전송하지 않는다. 동일 citation/기간/단위/범위/HOLD 계약으로 local 기존 run과 비교하고 provider latency와 전체 retrieval/validation latency를 구분한다. 배포 환경에서는 lifecycle stream buffering·disconnect를 검증한다.

Artifact: `.e2e-persistent/service-quality/provider-strategy-20261013/`, development replay는 `evals/results/provider-strategy-20261013/`. 키·원문 prompt는 새 runtime 로그에 기록하지 않는다.
