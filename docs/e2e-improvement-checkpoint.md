# E2E improvement checkpoint — 2026-10-13

재개 기준 HEAD: `28061c6`. 기존 대규모 미커밋 변경을 보존했다. Git 상태와 diff 통계는 `.e2e-persistent/service-quality/resume-git-status.txt`, `resume-diff-stat.txt`에 기록했다. Production 접속·migration·OCR·embedding 재처리 및 sealed 재채점은 실행하지 않았다.

| Phase | 상태 | 근거 / 남은 검증 |
|---|---|---|
| 1 Embedding | COMPLETED | 9 pages, 583 chunks/vectors, 1024차원 finite/nonzero; 중단 후 snapshot 완전 동일 |
| 2 성능 | COMPLETED | 동일 질문 검색 88.068 → 15.705초, 결과 동일; 688초 기록은 다른 질문이라 직접 비교 불가 |
| 3 Requirement | COMPLETED | strict analysis resolver와 legacy search 분리; unsupported/ambiguous/error HOLD; 빈 requirement 자동 PASS 금지 |
| 4 LLM | IMPLEMENTED_NOT_VERIFIED | timeout/429/schema/fallback mock 검증; 실제 Ollama 완료; 실제 Gemini 외부 근거 전송 승인 차단 |
| 5 UI | IMPLEMENTED_NOT_VERIFIED | 오류/상태/원문 page viewer/관측 bbox 구현·이전 브라우저 검증; 실제 새 PDF upload 경로 미검증 |
| 6 브라우저 | IN_PROGRESS | 이전 summary 완료, numeric/unit HOLD; 최신 중복 카드 수정 후 최종 실행 예정 |
| 7 Regression | IN_PROGRESS | 개발12/12, POSCO1/1, selected20/20, offline17/17 동일; sealed114 hash/flags 동일; 전체 최종 검사 진행 |

이번 재개: 카드 중복 테스트에 누락된 valid/perspective/span 메타데이터 추가, 문서 간 카드 병합 차단. 중복 판정은 원문 fact/수치/기간/범위 동일성에 한정한다. 테스트 fixture 보완 후 2 passed.

기존 artifacts: `search-baseline.json`, `search-optimized.json`, `regression-summary.json`, `runs.json`, `lg-cns-unit.json`, `sealed-before.json`. 경로 접두사는 모두 `.e2e-persistent/service-quality/`다. 기존 결과를 덮어쓰지 않았다.

중단 후 Docker와 로컬 서버가 종료돼 Docker를 다시 열었다. E2E container/volume은 남아 있었고 port55433 healthy. Production PostgreSQL은 Exited 상태를 유지했다. 재개 snapshot은 `snapshot-resumed-final.json`; 원문/vector hash는 이전 `snapshot-after-restart.json`과 동일하다. OCR/embedding 재호출 없음.

전체 검사 `./scripts/check.sh` sandbox 실행: 665 passed/1 failed. 실패는 OS file sandbox 합성 fixture가 중첩 sandbox에서 시작되지 않은 것. 테스트를 약화하지 않고 호스트 검사로 재실행: `check-resumed-host.log`. Sealed 실제 gold/first-run을 읽거나 실행하지 않는 synthetic test다.

최종 결과: 호스트 전체 검사 backend666/frontend11, lint/build PASS. 최신 브라우저 run `dbcbcff7-2d1e-4465-9d7f-7955c3bb9734` completed, 374.374초, 중복 없는 호재2/악재0/citation2. 원문 이미지2개 loaded, 관측 bbox9개와 p3 링크 확인. Artifact `browser-resumed-final.json`, `run-resumed-final-trace.json`. 실행 중 DB 자동 recovery가 재발했다. 안정적 latency는 미완료다. 재실행으로 속도를 좋게 보이게 하지 않았다.

분석 후 snapshot 완료: 원문/provenance/UUID/vector 전체 동일, vectors583/missing0. 실제 단계: retrieval25.975초, generation344.496초, validation2.651초. 마지막 검사 `git diff --check` 오류 없음.

다음 재개: E2E DB worker 종료/호스트 자원 문제 원인 규명 → 실제 Gemini 근거 전송 승인 후 실 fallback → 새 PDF 브라우저 upload 검증. API 실행 `scripts/run_service_e2e_api.py`는 항상 local Ollama only. Production 접속 또는 다른 프로젝트 container 중지는 승인 없이 실행하지 않는다. 최종 보고 `docs/service-quality-e2e-20261013.md` 참고.

## 성능 안정화 통합 작업 중간 기록 (2026-10-13; 아래 최종 기록이 우선)

- 기존 HEAD/dirty tree와 583 vectors를 재사용. `snapshot-optimization-before.json` 생성, 원문/UUID/provenance/vector unchanged. OCR/재임베딩/migration/production/sealed 재실행 없음.
- 과거 344.496초는 Gemini0/Ollama1이며 native load8.068s/prefill8.033s/generation327.262s/624 tokens(1.907t/s). Gemini3회 가설은 해당 run에서 기각.
- 실제 RAM8589934592, swap 초기3248.5MiB, Docker MemTotal4109152256. 첫 저메모리 분석 동안 swap3857→7966.75MiB. OOM 확정 아님; thermal warning 기록 없음.
- 구현: single-process local inference lock, embedding keep_alive0, generation60s/ctx4096/batch128, PG pool2/overflow0, 호출별 private-safe telemetry, reversible evidence-ID alias(opt-in), Next distDir 분리.
- SDK2.18.1 Interactions retry count 매핑 때문에 중첩 retry 가능. Stateless GenerateContent 및 attempts1로 수정, 실제 SDK MockTransport429/503/504 테스트에서 외부 요청 없이 application2 HTTP2 확인. API key/원문/응답 전문 로그 제거. Gemini 실호출/실 fallback NOT_VERIFIED 유지.
- 첫 계측108.706s/generation76.624s, 반복304.054s로 안정성 미완료. 두 질문은 과거 질문보다 짧으므로 참고 비교. low-warm label은 실제 load7.075s로 **cold**였음. 압박/host load가 큰 변동 요인. 세 번째는 과거 질문 정확히 사용, batch128/alias 적용83.722s. 현재 compact-warm 순차 실행 중; native timing으로 warm 판정 예정.
- 변경: backend/app/{generation,embeddings,database,analysis_service,local_inference}.py, backend/tests/{test_analysis,test_low_memory,test_generation_transport}.py, scripts/{run_service_e2e_api,measure_e2e_generation}.py, frontend/next.config.ts, .env.example/.gitignore 및 계약3문서.
- focused tests67 PASS(HTTP500/502 확장 전). 전체 check 및 브라우저 최종 검증 대기. E2E API 재시작은 사용자 명시적 허용 받음. 기존 dev13002 화면은 문서 loading에 머물러 성공으로 계산하지 않음. 분리된 production E2E build로 검증 예정.
- 당시 실험 명령은 폐기했다. 현재 실행 명령은 아래 최종 기록을 사용한다. Gemini 호출하지 않음.

## 통합 작업 최종 checkpoint — 2026-10-13

**PARTIAL.** 구현·전체 검사·로컬 실제 브라우저·회귀·무결성 검증을 완료했다. 안정적 latency/메모리 운영, 실제 Gemini fallback, 과거 DB crash 원인은 미완료다. 자세한 18개 항목/질문 답변은 `docs/runtime-optimization-20261013.md`.

- 채택: Gemini stateless GenerateContent/SDK retry1+application retry loop, HTTP500/502 transient 분류, private-safe 호출 telemetry, run ID/context/native timing 및 prompt 구성 시간. Local inference 순차 실행, embed keep_alive0/generation60s/ctx4096, PG pool2/overflow0 및 단일 E2E worker. 기본/Production 설정은 덮지 않았다.
- **제거한 실험**: UUID alias와 num_batch128. 83.72/69.11초였으나 카드2→1, batch128 단독도1개였으므로 source code에서 모두 제거. 이전 checkpoint의 compact flag를 사용하지 않는다. 전체 UUID, 기본 batch, evidence와 output schema 유지.
- 최종 run `032a7521-91c6-4cdc-891d-f6b95023ba6e`: server elapsed119.608s, generation89.452s, load6.469s/prefill6.726s/generation75.074s,1419/624tokens,8.312t/s. 이전374.374s와 질문/candidates/validated selection/토큰 수 동일. 관측 감소68.1%; host load 통제가 없고 다른 반복108.71→304.05s이므로 안정화/인과 개선으로 계산하지 않는다.
- 최종 메모리: swap4618.06→7368.44MiB(+2750.38), peak7418.81MiB, free percentage 최소8%, Ollama RSS peak3.51GiB. 실제 pressure/swap 확인; OOM/thermal throttle 확정 없음. 모든 warm 라벨 native load>5s여서 cold/reload로 분류.
- production UI13003 실제 문서선택583/583/분석/진행/호재2·악재0/citation2/이미지2 loaded/bbox9 확인. source viewer3→4와 loaded image 확인. IAB citation 새 탭 navigation은 미관측, 관측 href 직접 열어 viewer 검증. Numeric HOLD coveragefalse, unit HOLD ambiguous_requirement, `확인할 수 없습니다` 확인. 새로운 PDF 업로드는 범위 밖.
- 전체 최종 check `optimization-check-accepted.log`: backend675/frontend11/lint/build PASS. generated E2E/check build dirs의 lint 제외를 설정해 dev/serving cache와 검사 cache를 분리했다.
- 최신 재실행: 개발12/12, POSCO1/1, selected20/20, offline Hyundai/Samsung17/17 동일, Kia REVIEW, SK/Counts HOLD, false-complete0. `evals/results/runtime-optimization-20261013/regression-summary.json`. Sealed v1 재실행/재채점 없음.
- 원문/UUID/provenance/583vector hash 전후 동일/missing0. Sealed114 files hash/flags 동일. Production DB/volume 접근, migration, active revision, gold/manifest/first-run/immutable 변경 없음.
- E2E DB worker 과거 exit2/recovery 원인 UNKNOWN, OOMKilledfalse/RestartCount0. 계측 중 재발 미관측. 연결 pool 제한을 crash 원인 해결로 주장하지 않는다.
- 실행 사고: 잘못된 PID12080 TERM으로 macOS replicatord 종료. 이후 E2E port/start log 검증 후 PID 처리. launchctl 등록/종료상태0/대기 확인; 재실행 PID는 NOT_VERIFIED. Production DB 사고로 연결하지 않는다.
- 현재 E2E API18002와 UI13003이 실행 중이다. 사용자 허용은 E2E API 재시작에 한정했다. Shared Ollama/Docker 또는 다른 프로젝트 서비스 조정과 실제 Gemini 전송은 별도 승인 필요.

재개 명령:

```sh
PYTHONPATH=backend .venv/bin/python scripts/run_service_e2e_api.py --low-memory
# frontend directory, existing E2E build reuse
NEXT_DIST_DIR=.next-e2e npm run start -- --hostname 127.0.0.1 --port 13003
# root directory; new label prevents overwriting artifacts
PYTHONPATH=backend .venv/bin/python scripts/measure_e2e_generation.py --label NEW_LABEL --low-memory
NEXT_DIST_DIR=.next-check NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:18002 ./scripts/check.sh
```

Artifact 접두사는 `.e2e-persistent/service-quality/optimization-*`. accepted-run/accepted-metrics, browser-final.json/png, browser-numeric/unit, source-page4, metrics, old-sdk-retry, check-accepted.log, db.log/state/stats, sealed-integrity를 보존했다. snapshot 파일은 `snapshot-optimization-before.json`, `snapshot-optimization-final.json`. 기존 artifacts는 덮어쓰지 않았다.

HOLD/페이지 viewer 검증까지 끝난 closeout snapshot도 시작 snapshot과 완전 동일했다: `snapshot-optimization-closeout.json`. 최종 sealed114 hash/flags unchanged: `optimization-sealed-closeout.json`; E2E DB 최종 로그 `optimization-db-closeout.log`. 최종 `git diff --check` PASS.

## macOS 보호·저메모리 조사 checkpoint — 2026-10-13 21시 KST

**PARTIAL 유지.** 최종 보고서는 `docs/system-safety-low-memory-20261013.md`다. 추가 Gemini/Ollama 생성0회, 시스템 종료·강제 재시작0회, runtime low-memory 설정 변경 없음. 새 성능 개선 또는 편차 감소는 측정하지 않았다.

- replicatord: 최초 사용자 launchd 등록/idle, 이후 자동 실행 PID3228/PPID1 및 running 확인. 사고 이후 자동 실행 기록도 존재. 동기화 기능 정상 여부 NOT_VERIFIED, 사고로 인한 지속 오류는 확인할 수 없습니다.
- 안전 조치: AGENTS.md 보호 규칙, 종료 기능 없는 `scripts/audit_e2e_processes.py`, safety 회귀3개. PID/포트/명령만으로 소유권을 부여하지 않으며 확인 불가한 정리는 BLOCKED.
- 동일 짧은 질문108.706→304.054초의 차이195.348초 중 token generation 차이194.646초. 최종119.608초는 다른 질문. 모두 cold/reload이며 warm 효과/인과 기여 UNKNOWN. 압박 최저7→5%, Swapouts 약2.41→10.78million pages 동반.
- 실제 provenance 최대15.44MB의 hash 임시 할당 peak66.18MiB 확인. 스트리밍 probe는 hash 동일/메모리 감소지만1.279→3.053초로 느려 미채택. 모델 keep_alive/context/batch 및 cache 격리 유지.
- 전체 check: backend678/frontend11/lint/build PASS. 최초 nested sandbox fixture 실패 후 호스트에서 전체 재검증. targeted14 PASS, 최종 safety3 PASS.
- E2E READ ONLY 무결성: 583vectors/UUID/source/provenance/hash unchanged, sealed114 hash/flags unchanged. 기존 최종 run result 동일, citation2/bbox9/호재2의 literal source·현재 claim validator PASS. Production/ sealed 재채점 없음.
- 현재 E2E PG healthy,21:18:38 KST startup.18:15:30 fast shutdown/administrator lifecycle은 과거 exit2와 구분. 마지막 과거 server process exit2는15:37:54.852 KST, 원인 UNKNOWN.
- 현재 API 프로세스는 관측되지 않았으며 이전 API/UI 실행 상태는 승계하지 않는다. 서비스 재개·공유 자원 조정·정리 없이 읽기 전용 조사로 완료한다.

Artifact: `.e2e-persistent/service-quality/system-safety-20261013/`, 개발 replay 사본/결과는 `evals/results/system-safety-20261013/`. Latest challenge5 재검증 결과가 이전 결과와 byte-identical. Offline Hyundai/Samsung17/17 재검증 결과도 이전 결과와 동일. 전체 개발12/12/POSCO1/1/selected20/20은 이전 보고서 재사용. Kia REVIEW, SK/Counts HOLD 유지. 종료 직전 E2E source/vector 및 sealed114 hash/flags도 다시 동일함을 확인했다. HOLD/REVIEW를 승격하지 않는다.

## Provider 실행·동의 checkpoint — 2026-10-13

구조/모의 검증 완료, 실제 외부 성능 NOT_VERIFIED. 보고서: `docs/provider-strategy-20261013.md`.

- 기본 요청 LOCAL_ONLY/external_consent=false. EXTERNAL_WITH_CONSENT는 strict true + server ANALYSIS_EXTERNAL_ENABLED=1, FALLBACK_ALLOWED는 추가 ANALYSIS_OLLAMA_FALLBACK_ENABLED=1을 요구. 두 flag default0, 실제 .env 미변경. 기존 provider 환경변수/키로 동의를 추론하지 않는다. local E2E launcher는 외부 flag0 고정.
- 기존 Gemini3.7 Flash/Ollama gemma3:4b/timeout/retry/schema 및 RAG validator 재사용. API/서비스 두 층의 동의·provider 검사가 retrieval/run 생성 전 차단. 실행 mode/동의/attempt/final provider/fallback은 기존 result JSON에 기록, 과거 result execution=null 허용. DB migration 없음.
- GET analysis-options, POST analyses/stream 추가. 상태는 검색/생성/fallback/검증이며 최종 검증 전 모델 내용을 노출하지 않는다. 기존 JSON 분석 API 유지. UI 전송 범위/요청별 체크/변경·제출 후 해제 및 완료/실패/HOLD 표시.
- 실제 Gemini0/Ollama 생성0. Mock success/timeout/rate limit/schema/allowed fallback 및 모든 mode HOLD 검사. Focused87 PASS, 전체backend700/frontend17/lint/build PASS(check-accepted.log). 생성 .next-provider lint 제외 보완, 소스검사 유지.
- Chrome13004의 명시적 UI MOCK fixture로 local/external/fallback/HOLD/error/동의 상태 관측. 기존 실제 citation2/bbox9/image2 표시. 실제 외부 E2E/성능으로 계산하지 않는다. Mock API18004는600초 후 스스로 종료한다.
- Offline17/17 JSON 동일, challenge5 replay/selected20 pack·strict·coverage 비교 동일(fixed15 재사용), review-aware false-complete0/Kia REVIEW/SK·Counts HOLD 유지.
- E2E READ ONLY snapshot/source/UUID/provenance/583vector hash unchanged, 기존 accepted result/citation grounding 동일. Sealed114 hash/flags unchanged. Production/sealed 재채점/system kill/재시작 없음. DB 과거exit2 UNKNOWN 유지.
- 성능: 기존108~304초/최종119.608초 보존, 신규local NOT_MEASURED, 실제Gemini/fallback NOT_VERIFIED·별도 승인 필요. 다음 단계는 승인된 고정 verified packet1회 실 비교 및 배포 stream 검증.

Artifact: `.e2e-persistent/service-quality/provider-strategy-20261013/`, `evals/results/provider-strategy-20261013/`. 새 공개 API 계약은 api-contract/acceptance/qa-rules에 동기화했다.
