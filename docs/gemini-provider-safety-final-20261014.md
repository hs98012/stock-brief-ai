# Gemini synthetic 1회 실행 안전 설정 — 2026-10-14

**설정·로컬 검증만 승인됨. 실제 Gemini/Ollama 생성0회, 외부 payload 전송0회. 과금 tier UNKNOWN.** 이 문서가 기존 준비 문서의3.7모델/무제한 output/재사용 가능한 승인 설명보다 우선한다. 기존 payload·보고서는 과거 기록으로 보존했다. LG 전송 보류 유지.

## 최종 요청

- 모델: `gemini-3.8-flash` 직접 지정. [공식 모델 ID](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash).
- Endpoint: `POST https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent`.
- Body SHA256: `ace5ad27d706e4f31e2744d58488a1e6635bdfbcb1512f44d138dcf7404cea08`.
- 로컬 최종 body: `.e2e-persistent/service-quality/provider-safety-final-20261014/gemini-request-body.json`.
- 전송 필드: 기존 contents(질문·합성 사실1개·source 설명·공개 fixture citation 라벨), systemInstruction, generationConfig(temperature0, JSON MIME/schema, **maxOutputTokens2048**, thinkingConfig).
- 설치 SDK2.18.1은 thinkingConfig를 `{"thinking_level":"LOW"}`로 직렬화했다. MockTransport가 실제 body bytes를 포착했으며 실 서버 수용 여부는 NOT_VERIFIED.
- prompt/source/evidence/schema는 기존과 동일. 새로 만든 기업 재무 수치가 아니라 독립 가상 장치 처리시간 데이터다. LG/PDF/다른 보고서/개인정보/연락처/local path/내부 DB UUID/embedding/bbox 없음. 모델 ID는 URL에 있으므로 모델만 바꾸면 body hash가 바뀌지 않지만, 이번 token/thinking 설정으로 hash가 변경됐다.

## Token 상한 선택

1,024를 검토했으나 **2,048 + thinking LOW**를 선택했다. 이 작은 응답의 literal summary·카드1개·UUID를 담는 JSON은 짧지만 thinking도 생성 예산을 사용할 수 있고,1,024에서 잘릴 경우 재시도가 금지된1회를 소모한다.2,048은 JSON 완성 여유를 위한 보수적 선택이며 측정된 최적값이 아니다. [공식 thinking 문서](https://ai.google.dev/gemini-api/docs/thinking)는 thinking을 낮춰 비용/latency를 줄이되 작은 output 한도로 truncated/empty output이 발생할 수 있음을 설명한다.3.8은 LOW를 지원하고 minimal은 지원하지 않는다.

출력 한도가 JSON 완성을 보장하지 않는다. 잘린/잘못된 JSON은 기존 parser/schema와 fixture validation에서 오류로 처리하고 재시도하지 않는다. 입력 토큰·thinking·실제 과금 규칙 등이 있으므로 **maxOutputTokens가 전체 비용의 절대적 상한은 아니다**. 무료 또는 특정 금액 이하라고 가정하지 않는다. 실제 token usage/latency/출력 완성 가능성은 승인 후1회 측정 전까지 NOT_VERIFIED.

## 요청 한도 및 일회성 승인

- application attempts1/SDK attempts1 = 최초1회 포함, **추가 retry0**. HTTPTransport retry0, fallback없음, per-request timeout30초. Strict 전체 wall-clock deadline은 아니다.
- 기존 AnalysisRequest/외부 서버 정책/explicit consent 검사 유지. scope는 model/body hash/fixture/output limit/thinking/max attempts/fallback에 묶인다. endpoint/method도3.8 POST로 검사한다.
- 새 승인에는 고유 UUID `approval_id`가 필요하다. 외부 승인 파일을 이번 작업에서 만들지 않았다. 기존 consent=false 검토용 approval-scope.json은 실행 승인이 아니다.
- wire URL/body hash가 맞는지 확인한 다음 **send 직전에** 고정 로컬 ledger `.e2e-persistent/provider-approval-consumption/<approval_id>.json`을 O_CREAT|O_EXCL|O_NOFOLLOW/0600으로 생성한다. marker 내용과 directory를 fsync한 후에만 외부 transport로 넘긴다.
- 같은 approval_id는 파일복사/프로세스 재실행/새 output directory에서도 재사용 불가. 동시 소비 race에서도1개만 성공한다. timeout/crash/응답 validation 실패/부분 marker도 소비된 상태로 취급하며 marker를 삭제·rollback하지 않는다. 결과 불확실 시 재사용하지 않는다.
- marker를 삭제하거나 approval_id를 바꿔 같은 승인을 재사용하지 않는다. 새 ID 발급은 새로운 명시적 사용자 승인을 요구한다. 로컬 승인 파일/ledger는 사용자 신원 인증이나 악의적 로컬 관리자에 대한 변조 방지 시스템은 아니다.

## 과금 프로젝트 확인

결과 **UNKNOWN**. 로컬 root .env에 key 존재 여부만 확인했으며 값을 출력·외부 전송하지 않았다. key-project 연결 정보, tier 기록, gcloud 실행 파일 및 ADC 인증 파일이 없어 해당 key 소속 프로젝트/활성 billing을 확인할 수 없었다. 외부 account/keys/billing API 조회0회. 키 문자열만으로 tier를 추론하지 않는다.

[Google Billing 문서](https://ai.google.dev/gemini-api/docs/billing)에 따르면 key는 프로젝트의 billing/tier를 상속한다. 실제 실행 전에 사용자/프로젝트 관리자가 AI Studio Projects의 Billing Tier와 해당 key 소속 프로젝트를 비밀키 공개 없이 확인해야 한다. 미확인 상태를 무료로 취급하지 않는다. [데이터 처리 약관](https://ai.google.dev/gemini-api/terms)의 무료/유료 구분도 현재 key에는 확정 적용할 수 없다.

## 검증 및 변경

변경: `scripts/prepare_provider_fixture.py`의 fixture-only SDK config overlay/모델/atomic consumption, `backend/tests/test_provider_fixture.py`의 설정·중복 소비·동시 소비·uncertain timeout·partial marker 검증, 이 문서 및 이전 준비 문서의 최신 링크. Shared Gemini adapter/서비스 API/schema/config/.env/DB는 변경하지 않았다.

Focused48 passed: 기존 success/timeout/rate-limit/schema/fallback/consent/citation/숫자 검증 유지. Live executor 검사는 synthetic key+MockTransport+pytest temporary ledger만 사용. 실제 승인/소비 ledger는 생성하지 않았다. 전체 검사·회귀·무결성은 아래 최종 기록에 기재한다.

승인 전 재실행/모델 최적화는 추가로 하지 않는다. 향후 승인은 위3.8 endpoint/body hash/2,048 LOW/1회30초/retry0/fallback없음/독립 fixture에 한정돼야 한다. UNKNOWN 과금과 실제 출력 검증 미완료를 먼저 고지하고 승인받는다. LG나 다른 자료의 전송으로 확대하지 않는다.

최종 검증: `./scripts/check.sh` backend720 passed/frontend17 passed/lint/build PASS; focused48 passed. Offline17/17과 최신 challenge5 replay JSON은 이전과 byte-identical, fixed15 재사용/false-complete0/Kia REVIEW/SK·Counts HOLD 유지. 기존 source/pages/extraction/chunk UUID 및583vectors/missing0 hash, accepted result hash, sealed114파일 hash·flags는 이전 및 이번 before/after 동일. 최종 body3,350bytes의 prompt/system/schema가 이전과 동일하고 token/thinking 설정만 추가됐음을 비교했다. 실제 승인/소비 ledger 생성0회, 실제 호출0회. `git diff --check` PASS.
