# 안전한 Gemini 실호출 준비 — 2026-10-14

최신 설정은 [Gemini 안전 설정 최종 기록](gemini-provider-safety-final-20261014.md)을 따른다. 아래3.7 endpoint/body hash/재사용 승인 설명은 이전 준비 기록이다.

**로컬 준비·mock 검증 완료. 실제 Gemini 성능/모델 이용 가능 여부 NOT_VERIFIED. 외부 전송 승인 없음, 실제 Gemini/Ollama 생성0회.** 기존108~304초 로컬 측정을 유지하며 synthetic mock 시간을 실제 성능과 비교하지 않는다.

## 1. 독립 fixture와 이용 범위

`scripts/prepare_provider_fixture.py`의 독립 synthetic fixture v1을 사용한다. 질문은 가상 테스트 장치의 처리시간 변화이며, 합성 사실은 “합성 테스트 장치의 처리시간은 기준 대비20% 감소했습니다.”다. 실제 관측/기업/재무 실적으로 표시하지 않는다. 제3자 PDF에서 발췌하지 않아 보고서 라이선스를 전제하지 않는다. 외부 테스트용으로 독립 작성했지만 실제 전송은 별도 사용자 승인 전까지 금지한다.

LG PDF·원문·chunk·embedding·bbox·DB UUID를 재사용하지 않았다. 별도 문서 ingestion/embedding/DB run 생성도 없다. 기존 schema가 UUID를 요구하므로 `9cc9be12-219e-57a8-8965-8cba774a2139`를 fixture 전용 공개 인용 라벨로 사용한다. DB document/chunk UUID가 아니며 wire schema를 바꾸지 않았다.

LG 원본 hash `3489541bb393c16772ba3ed5d31c3f34a035ba36a472eabc884fa6ad60209808`는 sealed v1 manifest의5문서에 없다. 기존 audit-documents에는 prior_upload=true/blind_holdout=false다. LG 결과는 사용 이력이 있는 개발 LOCAL_ONLY 결과이며 독립 holdout 성능으로 평가하지 않는다. LG 외부 전송 권한 UNCERTAIN/전송 보류 유지. Sealed gold를 읽어 재채점하거나 sealed RAG를 재실행하지 않았다.

## 2. 직렬화 payload

로컬 artifact directory: `.e2e-persistent/service-quality/provider-preparation-20261014/`.

- `fixture.json`: 질문, source(title/origin/terms), evidence(citation_id/quote/metric/direction/value/unit/comparison_basis/scope).
- `gemini-request-body.json`: 설치된 SDK와 기존 GeminiGenerationProvider를 통과한 **실제 HTTP body bytes**. MockTransport에서 포착했으며 외부 서버로 보내지 않았다.
- wire 필드는 `contents`, `systemInstruction`, `generationConfig`(temperature, JSON MIME type, 기존 responseJsonSchema)다. URL에 model ID가 포함된다.
- body SHA256: `203551114e22e5118cd757e8d96b2ea7d29e7b35678e15196993b4c9982d62e3`.
- provider/model: Gemini / `gemini-3.7-flash`. 기존 ID 유지, 실제 이용 가능 여부 미검증.
- endpoint: `https://generativelanguage.googleapis.com/v1beta/models/gemini-3.7-flash:generateContent`.
- 실행 한도: timeout30초, application/SDK attempts1, HTTP retry0, fallback없음. 재시도/실패 후 추가 실행도 새 사용자 승인 필요. timeout은 엄격한 전체 wall-clock deadline을 보장하지 않는다.

개인 연락처, 사람 이름, 실제 기업명·종목코드, 로컬 경로, 파일 hash, 내부 document/chunk/run ID, PDF/이미지/embedding/bbox/provenance를 포함하지 않는다. API key/HTTP headers는 payload artifact에 저장하지 않는다. 향후 실제 인증에는 key 등 필수 transport header가 추가되며, body 검토가 provider의 데이터 보관/이용 조건을 대신하지 않는다. 새 synthetic packet용 검사는 LG 원문용 자동 DLP 필터를 구현한 것이 아니다.

## 3. Mock 검증과 출력 계약

기존 provider factory/정책/SDK/timeout/retry/fallback/schema와 서비스 citation 검사를 재사용한다. 별도 public API·DB 모델·RAG pipeline 변경 없음.

- 기존 LOCAL_ONLY 기본 선택 및 mock 서비스 grounding/citation 정상.
- 서버 외부 정책 off, 요청 동의 누락/비boolean, local 요청에 external adapter 주입은 호출/run 생성 전 차단.
- 독립 fixture SDK mock success, timeout/429→Ollama mock fallback, schema 오류→fallback 금지.
- 실제 설치 SDK 직렬화, schema 및 usage/safety/429/5xx 기존 회귀 포함.
- fixture 응답은 기존 GeneratedAnalysis/schema와 supported_claim을 사용. 알려진 fixture citation만 허용하며 quote/source를 로컬 원문에서 복원한다. 각 관점 최대3개, 중복/관점 오류 차단. summary는 literal source 또는 `확인할 수 없습니다`만 허용하는 보수적인 smoke gate다.
- 근거 없는999, 잘못된 기간·단위·범위, unknown/empty citation, 중복 citation 차단. 근거 없는 빈 응답은 HOLD. 실제 금융 RAG의 정확성이나 bbox를 검증했다고 주장하지 않는다.
- 승인 경로도 인메모리 transport로 검사: 승인/정책/hash 불일치에서는 live transport를 열지 않으며, 요청 URL/method/body가 승인 hash와 다르면 send 이전에 차단한다.

Focused45 passed. 전체 검사와 보호 결과는 아래 최종 기록을 따른다. mock 호출 횟수는 외부 호출 횟수가 아니다.

## 4. 승인 후 최소 실행 절차

현재 `approval-scope.json`은 consent=false/server_policy_enabled=false/actual_calls=0인 **검토용 기록**이며 실행 승인이 아니다. CLI 기본 동작은 offline mock capture뿐이다.

1. 사용자가 위 fixture, 질문·body hash, Gemini/model/endpoint,1회/30초/fallback없음 범위에 명시적으로 승인해야 한다. 모델·본문·범위가 바뀌면 다시 승인받는다. 실제 서비스 이용조건/과금 tier도 실행 전 확인한다. LG 전송 승인으로 확대하지 않는다.
2. 승인 후에만 운영자가 별도 `approved-consent.json`에 provider/model/fixture/payload_sha256/maximum_external_attempts=1/fallback=false 및 approved=true/external_consent=true를 기록한다. 이 로컬 파일은 사용자 신원을 증명하는 인증/서명 토큰이 아니다. 지금은 이 승인 파일을 만들지 않았다.
3. 실행 프로세스에 기존 `ANALYSIS_EXTERNAL_ENABLED=1`과 루트 .env의 Gemini key를 제공한다. .env 파일/공유 서버 정책은 이번 작업에서 변경하지 않았다. CLI는 .env를 자동 로드하지 않는다. 기존 AnalysisRequest/정책 검사를 통과해야 하며 LG DB에 접속하지 않는다.
4. 명시적 `--execute --approval`을 사용한다. 아래 명령은 **승인 후에만** 실행한다. `approved-consent.json`은 현재 존재하지 않으며, 사전 준비 명령에 이 옵션을 붙이지 않는다.

```sh
# 승인 후, key 및 해당 실행에 한정한 서버 정책이 환경에 제공된 경우에만:
PYTHONPATH=backend .venv/bin/python scripts/prepare_provider_fixture.py \
  --execute \
  --approval .e2e-persistent/service-quality/provider-preparation-20261014/approved-consent.json \
  --output .e2e-persistent/service-quality/provider-approved-run-20261014
```

5. transport는 승인 endpoint/body hash와 최대1회를 전송 직전 강제한다. 환경 temperature/SDK 직렬화가 달라져도 hash 불일치로 차단한다. 승인 후 성공한 검증 결과·latency·usage trace는 별도 approved-result.json에 저장한다. 오류 또는 HOLD는 성능/정확성 PASS로 승격하지 않는다. 실패 시 디렉터리를 덮거나 자동 재실행하지 않는다. 이1회 synthetic smoke를 기존 LG108~304초와 동일 조건 비교로 표시하지 않는다.

승인 없는 준비 재현 명령(새 output directory 필요):

```sh
PYTHONPATH=backend .venv/bin/python scripts/prepare_provider_fixture.py \
  --output .e2e-persistent/service-quality/provider-preparation-next
```

## 5. 변경 및 보호

신규: `scripts/prepare_provider_fixture.py`, `backend/tests/test_provider_fixture.py`, 이 보고서. 기존 application/API/config/.env 및 계약3문서는 변경하지 않았다. 별도 ignored payload/log와 개발 replay artifacts만 새로 작성했다. Production DB 미접속, LG extraction/embedding/OCR 재생성0, 시스템 종료/재시작0, sealed 재실행·재채점0.

검증 기록: targeted.log, check-final.log, offline.log, latest.log, regression-summary.json, integrity-before/after.json. Offline17/17과 최신 challenge5는 현재 validator로 재실행해 기존 JSON과 byte-identical. Fixed15는 기존 결과 재사용임을 유지한다. 기존 review-aware false-complete0/Kia REVIEW/SK·Counts HOLD는 결과 동일성으로 보존하며 새 독립 holdout PASS를 만들지 않는다.

최종 결과: `./scripts/check.sh` backend717 passed/frontend17 passed/lint/build PASS, focused45 passed, `git diff --check` PASS. E2E READ ONLY source/pages/extraction/chunk UUID 및583 finite/nonzero vectors(1024)/missing0의 hash가 이전 조사와 일치하고 이번 before/after도 동일하다. 기존 accepted run result hash도 동일. 봉인114파일의 before/after hash·flags 동일,64개 bundle 파일은 manifest hash와도 일치한다. 이번 작업에서 기존 PASS/HOLD/REVIEW를 수정하지 않았다.
