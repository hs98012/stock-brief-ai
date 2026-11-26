# Gemini 503 이후 재검증 준비 — 2026-10-14

**PREPARED_NOT_APPROVED. 이번 작업의 Gemini 실제 API 호출 0회, 신규 승인 발급·소비 0회.** 공개 공식 문서만 웹으로 조회했다. 모델 목록·토큰 계산·프로젝트·billing 인증 API도 호출하지 않았다. 실행 가능한 승인은 만들지 않았다.

이전 요청은 2026-10-14 19:22:55~19:23:01 KST에 HTTP 503 UNAVAILABLE로 종료됐다. 전체 6.144582초, HTTP 6.044037초, 요청 1회/retry 0/fallback 없음/timeout 없음. Google 응답의 사유는 모델 수요 급증이다. **서비스 가용성 실패**로 유지하며 schema 오류나 모델 출력 실패로 재분류하지 않는다. 생성 결과와 토큰 사용량·실제 응답 모델은 없고 schema/citation/사실 정확성은 NOT_VERIFIED다.

기존 승인 `f164640e-751f-472e-9467-9739a194ce8f`는 소비 완료다. ledger의 `CONSUMED_BEFORE_SEND_OUTCOME_UNKNOWN` marker는 기존 계약대로 유지하며 실제 HTTP 503은 기존 execution.json에서 확인한다. 이전 보고서·실행기·응답·실행 기록·payload·소비 marker는 수정하지 않았다.

## 원인과 지원 상태 확인 범위

- [공식 모델 문서](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash)는 stable 모델 코드 `gemini-3.8-flash`, structured output, thinking low/medium/high 지원을 명시한다. 이는 문서상 지원 확인이며 해당 API key의 접근 권한·실시간 가용성 확인은 아니다.
- [공식 troubleshooting](https://ai.google.dev/gemini-api/docs/troubleshooting)은 503을 재시도 대상인 일시적 오류로 다룬다. 실제 저장 응답의 high demand 설명과 부합한다. 일반적인 backoff 권고는 이번 retry 0 계약에 적용하지 않는다.
- 실제 응답에는 추가 error details, modelVersion, usageMetadata가 없었다. trace의 request_id도 null이며 응답 헤더는 이전 실행에서 저장하지 않았다. 이전 Retry-After·서버 추적 ID는 사후 복원할 수 없다. 프로젝트별 장애 원인, quota, 과금 문제와의 관계는 확인할 수 없습니다.
- [공식 상태 페이지](https://aistudio.google.com/status)를 조회했으나 조회 도구에서 상태 본문을 얻지 못했다. 전역 장애·복구 여부는 NOT_VERIFIED. 다른 사용자의 게시글을 이번 요청의 원인 증거로 사용하지 않았다.
- 호환성 참고: 공식 troubleshooting은 Gemini 3.6 이상에서 temperature/top_p/top_k를 무시하며 향후 400 처리될 수 있다고 안내한다. 기존 body의 temperature=0은 그대로 보존한다. 결정론을 보장한다고 주장하지 않으며, 이를 이번 503 원인으로 단정하지 않는다. 삭제하려면 payload hash가 바뀌므로 별도 변경·승인이 필요하다.

## 과금 확인

**UNKNOWN.** 로컬 .env에 API key는 존재하지만 프로젝트·billing·tier 관련 필드가 없고 gcloud 실행 파일과 ADC 인증 파일도 없다. 키 값은 출력·저장·외부 전송하지 않았다. 인증된 계정 조회는 하지 않았다.

[Google billing 안내](https://ai.google.dev/gemini-api/docs/billing)에 따르면 API key는 소속 프로젝트의 billing 상태를 따른다. 사용자가 AI Studio에서 해당 key의 프로젝트를 확인한 후 Projects의 Billing Tier/Status와 Billing 화면의 요금제·잔액을 확인해야 한다. 키 문자열이나 503 응답으로 무료/유료 여부를 추론할 수 없다. UNKNOWN 상태를 유지하면 다음 승인에도 비용 발생 가능성을 명시한다. 과금 설정·티어·결제수단은 변경하지 않는다.

## 신규 실행 계획

| 항목 | 고정 조건 |
|---|---|
| Payload | `.e2e-persistent/service-quality/provider-safety-final-20261014/gemini-request-body.json` |
| SHA-256 | `ace5ad27d706e4f31e2744d58488a1e6635bdfbcb1512f44d138dcf7404cea08` |
| 크기 | 3,350 bytes, 이번 재검증 일치 |
| 전송 내용 | 기존 독립 synthetic fixture만; LG 및 실제 문서 전송 금지 |
| 모델 | `gemini-3.8-flash` |
| Endpoint | `POST https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent` |
| 출력 | 최대 2,048 tokens / thinking LOW |
| 요청 한도 | 최초 요청 포함 최대 1회 |
| Timeout | 요청 30초; 엄격한 전체 wall-clock deadline 아님 |
| Retry / fallback | application·SDK·HTTP retry 모두 0 / fallback 없음 |
| 신규 승인 | 별도 명시적 승인 후 새 UUID 발급; 지금 approval_id=null, approved=false |
| 승인 소비 | 기존 consume_approval의 배타적 파일 생성 및 file/directory fsync 후 send |
| 실패·중단 | timeout·연결 오류·503·검증 오류·응답 불명확 모두 자동 재실행 금지; 소비 rollback 금지 |
| 새 결과 경로 | `.e2e-persistent/service-quality/gemini-live-revalidation-20261014/` — 실행 시에만 배타적으로 생성 |

현재 기존 fixture executor의 모델/timeout/attempts1/HTTP retries0 및 원자적 소비 코드를 읽기 전용으로 확인했다. 코드를 다시 구현하거나 payload를 재생성하지 않았다. 계획 JSON은 승인 파일로 사용하지 않는다.

## 다음 실행 방법 — 새 승인 이후에만

1. 사용자가 위 동일 body/model/endpoint/최대 1회 및 UNKNOWN 과금·비용 가능성에 대해 새로 명시적으로 승인한다. 기존 승인은 사용하지 않는다.
2. 새 UUID와 별도 approved-consent.json을 만든다. 기존 ledger에 ID가 없는지, 새 출력 디렉터리가 없는지 검사한다. 실행 직전에 body 크기/hash·설정·보호 파일 및 격리 E2E DB 해시를 재확인한다.
3. 기존 `scripts/prepare_provider_fixture.py`의 `execute_approved(scope, packet)`를 사용한다. 이전 run_once.py는 이전 출력 경로를 고정하므로 그대로 재실행하지 않는다. 신규 실행 위치에서 기존 계측 방식을 재사용해 raw response/status/time/modelVersion/usage/finish reason과 실패 결과도 저장한다. API key는 루트 .env에서 메모리로만 읽고 이 프로세스에만 외부 정책을 허용한다.
4. transport가 URL/method/body hash를 확인하고 신규 승인을 원자적으로 소비한 뒤 1회 전송한다. 실제 HTTP 전달은 1회를 넘을 수 없으며 성공·실패 모두 동일 승인 재사용 금지다.
5. 생성 JSON에 기존 schema 및 validate_response를 적용하고, 허용 citation `9cc9be12-219e-57a8-8965-8cba774a2139`와 “합성 테스트 장치의 처리시간은 기준 대비 20% 감소했습니다.”를 대조한다. 근거 없는 절대 시간·추가 지표·주장이 없는지 검토한다. 응답/검증 실패를 성공으로 기록하지 않는다.
6. 전후 무결성을 비교하고 새 결과만 보존한다. LG E2E 검증이나 기존 Ollama와 동일 조건 비교로 확대하지 않는다.

Production DB/volume 변경·접속, OCR/embedding/analysis 재생성, sealed 재실행·재채점은 이번 준비에서 수행하지 않았다. 앱 코드/API/데이터 모델도 변경하지 않았다. 보호 파일은 내용을 평가하지 않고 바이트 해시와 flags만 비교한다.

준비 artifact: `.e2e-persistent/service-quality/gemini-revalidation-preparation-20261014/`의 execution-plan.json, billing-local-check.json, protected-before.json 및 검사/최종 무결성 기록. 이전 결과와 신규 준비 기록을 분리했다.

최종 검증: 이전 호출 기록·소비 ledger·고정 payload·봉인/보호 파일을 포함한 130개 파일의 전후 SHA-256/flags 동일. `./scripts/check.sh` backend 720 passed / frontend 17 passed / lint·build PASS, `git diff --check` PASS. 이번 신규 실제 호출·승인 ID·소비 marker는 모두 0개다. DB 자체를 재조회한 검증은 아니며 기존 DB 검증 기록의 보존과 보호 파일 불변을 확인했다.
