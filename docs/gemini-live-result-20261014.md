# Gemini synthetic 실제 1회 호출 결과 — 2026-10-14

최종 판정 **FAIL**. 승인된 외부 요청 1회가 HTTP 503 UNAVAILABLE로 종료됐다. Google 오류 응답은 모델의 높은 수요를 사유로 제시했다. 생성 응답이 없어 속도·출력 정확성 성공 기준은 충족하지 못했다. 재시도하지 않았다.

| 항목 | 실제 결과 |
|---|---|
| 사용자 승인 | 이 대화에서 고정 조건으로 1회 호출 명시 승인 |
| 승인 ID | `f164640e-751f-472e-9467-9739a194ce8f` |
| 승인 소비 | 기존 원자적 ledger로 send 직전 소비; 재사용 불가 |
| 실제 외부 요청 | 1회; HTTP 응답 수신 |
| Payload | 3,350 bytes; SHA-256 `ace5ad27d706e4f31e2744d58488a1e6635bdfbcb1512f44d138dcf7404cea08` 일치 |
| 전송 범위 | 독립 synthetic fixture만; LG·다른 실제 문서·개인정보·로컬 경로·내부 DB ID 없음 |
| Provider / 요청 모델 | Google Gemini / `gemini-3.8-flash` |
| Endpoint | `POST https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent` |
| 실제 응답 모델 | 응답에 modelVersion 없음 — 확인할 수 없습니다 |
| HTTP status | 503 / UNAVAILABLE |
| 전체 실행 소요 시간 | 6.144582초; 실행기 초기화·검증 포함, DB 해시 검사 제외 |
| HTTP 요청·응답 본문 수신 | 6.044037초 |
| Input / output / thinking tokens | 모두 미제공 — 확인할 수 없습니다 |
| Finish reason | 생성 candidate 없음, 미제공 |
| Output 설정 | maxOutputTokens 2,048 / thinking LOW |
| Timeout | 발생하지 않음; 설정 30초, 엄격한 전체 wall-clock deadline 아님 |
| Retry / fallback | 0회 / 없음 |
| 응답 JSON | 유효한 오류 JSON; 생성 결과 schema 검증 NOT_VERIFIED |
| Citation / 사실 정확성 | NOT_VERIFIED; 생성 결과 없음 |
| Hallucination | NOT_VERIFIED; 발생하지 않았다고 판정하지 않음 |
| 과금 티어 / 확정 비용 | UNKNOWN / UNKNOWN; 청구 정보 없음, 비용 추정하지 않음 |

검증 대상 원문은 “합성 테스트 장치의 처리시간은 기준 대비 20% 감소했습니다.”이며 허용 citation ID는 `9cc9be12-219e-57a8-8965-8cba774a2139`다. 응답에 생성 주장이 없어 20% 감소 반영, 절대 처리시간·추가 지표·근거 없는 수치 생성 여부, fixture 출처 연결을 검증할 수 없다.

## 무결성

격리 E2E DB에 REPEATABLE READ READ ONLY 트랜잭션으로 접근했다. 호출 전후 pages·page_extractions·chunk UUID/provenance·583 vectors(missing 0) 해시가 동일하며 이전 안전 검증 snapshot과도 일치했다. documents와 analysis_runs 전체 행 해시도 전후 동일하다. Sealed holdout의 gold/manifest/first-run을 포함한 114개 파일은 바이트 해시와 flags만 비교했으며 전후·이전 기록과 동일하다. 보호 대상 PDF 및 로컬 stock_brief.db 파일 해시도 전후 동일하다.

Production DB 및 volume은 접근·수정·재시작하지 않았다. **Production PostgreSQL volume 자체의 전후 DB 해시는 NOT_VERIFIED**이며 격리 E2E 검증을 Production 검증으로 표현하지 않는다. OCR/extraction/embedding/분석 재실행, sealed 재채점 없음.

## 실행 기록

영구 경로: `.e2e-persistent/service-quality/gemini-live-20261014/`

- `approved-consent.json`: 사용자 승인 범위와 승인 ID
- `run_once.py`: 기존 execute_approved 및 consume_approval을 재사용한 일회 실행·응답 계측; 재실행 금지
- `execution.json`: 실제 시간·상태·시도 횟수·provider trace
- `response-body.json`: 실제 Google 오류 JSON; 인증 헤더·API key 미저장
- `integrity-before.json`, `integrity-after.json`, `integrity-comparison.json`: 무결성 관측
- `check.log`: 프로젝트 전체 검사 로그

소비 ledger: `.e2e-persistent/provider-approval-consumption/f164640e-751f-472e-9467-9739a194ce8f.json`. marker의 `CONSUMED_BEFORE_SEND_OUTCOME_UNKNOWN`은 기존 계약의 영구 소비 상태다. 실제 HTTP 503 결과는 execution.json에 별도로 기록했다. marker는 삭제하거나 되돌리지 않았다.

이번 6.145초는 실패 응답까지 걸린 시간이며 성공한 생성 지연시간이 아니다. 기존 Ollama 108~304초와 동일 조건 비교를 하지 않는다. LG 기업 분석 전체 E2E 성능은 검증되지 않았다.

검사 완료: `./scripts/check.sh` backend 720 passed / frontend 17 passed / lint·production build PASS. `git diff --check` PASS. 애플리케이션 코드나 API/데이터 모델은 변경하지 않았으며 기존 사용자 변경을 보존했다. 이 검사는 HTTP 503 결과나 미검증된 생성 정확성을 PASS로 바꾸지 않는다.
