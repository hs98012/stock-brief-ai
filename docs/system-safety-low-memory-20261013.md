# macOS 보호 및 8GB 실행 안정성 — 2026-10-13

**판정: PARTIAL.** 시스템 프로세스를 변경하지 않고 보호 규칙과 읽기 전용 감사 도구를 추가했다. 기존 성능 자료에서 편차가 발생한 단계를 분리했다. 추가 LLM 호출은 0회이며, 이번 작업으로 분석 속도 편차가 감소했다는 증거는 없다. 원인이 불명확한 사항을 PASS로 처리하지 않는다.

## 1. replicatord 현재 상태

21:19 KST 최초 관측: 실행 PID 없음, `gui/501/com.apple.replicatord` 등록, `state=not running`, 마지막 종료 사유 `JETSAM_REASON_MEMORY_IDLE_EXIT`. system domain에서는 등록을 찾지 못했으나 사용자 GUI domain에서는 등록을 확인했다.

21:20:09 KST launchd 자동 실행 이후 PID3228/PPID1을 관측했다. 21:22 및 21:23 관측은 `state=running`, `runs=2`, 실행 경로 `/System/Library/PrivateFrameworks/ReplicatorCore.framework/Support/replicatord`다. 프로세스 실행과 등록 확인은 완료했지만 실제 기기 간 동기화 기능 정상 여부는 **NOT_VERIFIED**다.

종료 사고의 PID12080은 16:24:16 자동 실행, 16:24:35 service inactive 기록이 있다. 이후 16:30:24 PID13129, 17:26:59 PID16064, 17:58:59 PID17849, 21:14:16 PID505 자동 실행 기록을 확인했다. 사고 당시 프로세스에는 MallocStackLogging 오류, 임시 디렉터리 정리 권한 오류(NSCocoaError513/POSIX1), QUIC 오류가 있지만 시작 직후부터 기록됐다. 이를 TERM 사고로 발생한 지속 장애라고 판정할 근거는 없다. TERM 발신자·정확한 신호 종료 사유는 이 로그에서 **확인할 수 없습니다**.

근거: `.e2e-persistent/service-quality/system-safety-20261013/{replicatord-events.log,launchd.txt,launchd-current.txt,replicatord-current.txt}`. 관측 사이 상태가 달랐으므로 최초 idle 상태와 이후 running 상태를 구분한다.

## 2. 시스템 프로세스 보호 조치

- 이번 작업에서 kill/pkill/killall/sudo/launchctl bootout/kickstart 실행 0회. 강제 복구·서비스 재시작·모델 unload 요청 없음.
- AGENTS.md에 명시적 승인, 직접 실행한 개발 프로세스 소유권, 부모·사용자·시작 시각·명령 및 PID 재사용 확인 규칙을 추가했다.
- 새 `scripts/audit_e2e_processes.py`는 읽기 전용이며 종료 기능이 없다. 쉘 검색 문자열을 실제 개발 프로세스로 오인하지 않는다. PID·명령 일치만으로 소유권을 부여하지 않는다.
- 현재 감사에서 replicatord는 `system_protected`, cleanup은 **BLOCKED**다. 소유권을 증명하지 못한 개발 프로세스도 BLOCKED로 기록한다. 현재 API 실행 프로세스는 관측되지 않았다. 기존 checkpoint의 API/UI 실행 상태를 현재 상태로 승계하지 않는다.

사용: `.venv/bin/python scripts/audit_e2e_processes.py`. ps 접근이 거부되면 `NOT_VERIFIED`를 출력하며 다른 수단으로 종료하지 않는다. 프로세스 관측은 종료 승인을 대신하지 않는다.

## 3. 119~304초 편차 분석

| 항목 | 짧은 질문 A | 동일 짧은 질문 A 반복 | 최종 기존 질문 B |
|---|---:|---:|---:|
| 전체 시간 |108.706s|304.054s|119.608s|
| generation stage |76.624s|272.327s|89.452s|
| model loading |7.487s|7.075s|6.469s|
| prompt evaluation |6.894s|7.987s|6.726s|
| token generation |61.973s|256.619s|75.074s|
| context 설정 |4096|4096|4096|
| prompt/generated tokens |1408/602|1408/602|1419/624|
| 생성 속도 |9.714t/s|2.346t/s|8.312t/s|
| load 상태 |cold/reload|cold/reload|cold/reload|

A 두 실행은 같은 후보·generated selection·validated selection임을 JSON 비교로 확인했다. gemma3:4b/low-memory/keep_alive60s/ctx4096, prompt_chars2554와 토큰 수가 동일하다. 당시 trace에 num_batch가 없어 모든 옵션의 완전한 동일성은 **NOT_VERIFIED**다. B는 질문/prompt가 달라 A와 엄격한 동등 비교가 아니다.

A의 전체 차이195.348초 중 token generation 차이194.646초가 약99.6%다. 모델 로딩 증가나 출력 토큰 증가로 설명되지 않는다. 반복 실행의 압박·swapout 증가가 동반됐지만 CPU contention, unified memory, scheduler, swapping 각각의 인과 기여 시간은 **UNKNOWN**이다. 실제 warm 성공 사례가 없어 cold/warm 성능 효과를 정량 비교할 수 없다. keep_alive60s라는 설정만으로 warm이라고 판정하지 않는다.

## 4. Swap·메모리·CPU·Docker

| 항목 | A 최초 | A 반복 | B 최종 |
|---|---:|---:|---:|
| swap 시작→종료 MiB |3857→7891.75|4867.12→7806.50|4618.06→7368.44|
| swap delta MiB |+4034.75|+2939.38|+2750.38|
| swap peak MiB |8056.81|7971.75|7418.81|
| memory_pressure free 최저 |7%|5%|8%|
| Swapouts delta pages, 16KiB |2,407,631|10,778,434|3,661,604|
| Pageouts delta pages |3214|11699|4233|

표의 swap/counter는 기존 run에 포함된 전체 계측 samples/metrics 기준이다. 별도 `*-memory.json` monitor-only 창의 counter delta는 마지막 샘플 범위가 달라 약간 작다. `historical-pressure.json`은 이 monitor 창을 별도로 표시한다. Swapouts 누적 이동량은 swap 사용량의 순증과 다르다.

과거 process RSS peak: Ollama 약3.4~3.5GiB, Chrome 약0.85~1GiB, Codex 약0.95~1.26GiB, Docker 호스트 프로세스 약0.47~0.51GiB(A 기준). 각 peak는 같은 시점이 아니며 합산해 시스템 peak로 주장하지 않는다. 과거 Docker VM MemTotal은3.827GiB, B 분석 완료 시 E2E PG는74.42MiB/CPU0.01%였다. 생성 중 container peak와 전체 Docker VM 실제 사용량은 **NOT_VERIFIED**다.

ps %CPU 합계 평균은 A 약245.7%, 반복 약279.1%, B 약229.2%다. 이는 프로세스 수명 기준 ps 값의 표본 합계이며 순간 CPU load/utilization이나 단독 병목 증거가 아니다. 과거 load average는 수집되지 않았다.

현재 관측(21:20~21:23 KST): swap6369.81→6577.19MiB(+207.38), 중간6340.38MiB, free31~32%, load averages8.24/25.52/18.15→2.77/16.61/15.68. 이 창에는 시스템 로그 검사·테스트 등 작업이 포함되며 분석 실행은 없다. 따라서 분석 swap delta나 개선 효과로 사용하지 않는다. Ollama `/api/ps`는 models0. 전용 E2E PG는54.76→67.54MiB/3.827GiB, CPU0.04→0.00%의 두 읽기 전용 표본이다.

## 5. 이번 실제 수정 파일

- `AGENTS.md`: 시스템 및 E2E 프로세스 보호 규칙.
- `scripts/audit_e2e_processes.py`: 종료 기능 없는 프로세스 감사.
- `backend/tests/test_process_safety.py`: PID 재사용·미확인 소유권·쉘 문자열 오인 회귀3개.
- 이 보고서 및 `docs/e2e-improvement-checkpoint.md`: 관측 결과와 재개 상태.

기존 대규모 dirty tree를 보존했다. 이번 작업은 API/DB 모델을 변경하지 않아 계약3문서 수정은 필요하지 않다. 새 `evals/results/system-safety-20261013`은 기존 개발 replay 도구 사본과 결과를 담는 artifact directory이며 이전 결과를 덮어쓰지 않는다.

## 6. Low-memory 설정 검토 및 변경

**runtime 설정 변경 없음.** 기존 bge-m3 embed keep_alive0, gemma3:4b keep_alive60s/ctx4096, process-local inference RLock, FastAPI E2E worker1, PostgreSQL application pool2/overflow0/timeout30/recycle300을 유지한다. 이 lock은 공유 호스트 또는 여러 API process 사이의 전역 동시성 제한이 아니다. 과거 runner np1 관측만 있으며 공유 Ollama 설정을 변경하지 않았다.

OCR 전용 container는 이전 Exited 기록을 재사용한다. 현재 전용 OCR 중복 실행과 생성 중 다른 클라이언트 동시 추론은 **NOT_VERIFIED**다. production/다른 프로젝트 container를 조사·정리하지 않았다.

실제 개발 provenance 최대 JSON15,438,168bytes의 fingerprint probe: 기존 임시 Python 할당 peak69,391,901bytes(66.18MiB),1.279초. 스트리밍 hash는16,941bytes,3.053초, hash 동일이었다. tracemalloc을 켠 단일 microbenchmark이며 전체 RSS/분석 성능 측정이 아니다. 메모리는 절감하지만 반복 호출의 CPU 시간이 증가하므로 **수정 미채택**. 결과는 `fingerprint-probe.json`. 요청 내 cache deepcopy는 source mutation 및 호출자 mutation 격리 테스트가 있어 증거 없이 제거하지 않았다. prompt packet과 trace 후보 보관도 감사·검증에 필요하며 불필요한 중복으로 단정하지 않는다.

## 7. DB worker 종료 원인 및 현재 상태

과거 마지막 server process exit2: **2026-10-13 15:37:54.852 KST**, PID1031. 이후15:38:13 recovery 완료. 이는 logical replication launcher와 동일 worker라고 입증되지 않았으므로 PostgreSQL server process라고 기록한다. Container OOMKilledfalse/RestartCount0 기록만으로 개별 backend OOM을 배제할 수 없다. exit2 원인은 **UNKNOWN**이다.

현재 container는21:18:38 KST 시작, healthy/OOMKilledfalse/ExitCode0/RestartCount0. 로그의18:15:30 KST 종료는 fast shutdown 요청 및 administrator command,18:15:31 logical replication launcher exit1을 동반한 정상 shutdown lifecycle이다. 이를 과거 exit2의 원인으로 연결하지 않는다. 현재 startup은 기존 data directory 재사용 및 정상 ready 기록이며 새 exit2는 tail150에서 관측되지 않았다.

Pool exhaustion/timeout을 직접 원인으로 지목하는 로그, kernel OOM 증거, crash stack/core는 없다. 복구나 pool 재설정을 시행하지 않았다.

## 8. 분석 성능 전후 비교

기존 374.374→119.608초, generation344.496→89.452초 관측은 이전 작업 결과로 유지한다. 이번 신규 실제 분석은0회이므로 **이번 변경 이후 latency/variance 개선은 NOT_MEASURED**다. 새 실험 없이 좋아졌다고 주장하지 않는다. warm 보장을 위한 keep_alive 연장은 8GB 메모리 압박을 함께 검증해야 하므로 채택하지 않았다.

## 9. 전체 및 targeted 검증

`./scripts/check.sh` 호스트 검사: **backend678/frontend11/lint/build PASS**, warnings20. 최초 sandbox 검사674passed/1failed는 기존 합성 OS sandbox fixture의 중첩 sandbox 시작 실패였으며 테스트를 약화하지 않고 호스트에서 재실행했다. 실제 sealed 재평가를 실행하지 않는 synthetic fixture다.

Targeted: process safety + 기존 low-memory payload/직렬화/private telemetry/transport + request-cache 검증 **14passed**. `git diff --check` PASS. 로그는 artifact directory의 `check-host.log`, `targeted.log`다.

## 10. 기존 데이터·citation·판정 무결성

전용 E2E READ ONLY transaction + database/user guard로 확인: pages/page_extractions/chunks UUID·원문·provenance hash와 embedding hash가 `snapshot-optimization-closeout.json`과 동일하다. 583개 finite/nonzero vector(1024), missing0. Sealed114파일 SHA256/immutable flags unchanged, 재실행·재채점 없음. Production DB 미접속·미수정.

기존 최종 run을 READ ONLY로 재확인했다: 저장 result JSON 동일, 호재2/악재0/citation2/source_boxes9, literal source span·source chunk coverage·trusted span·현재 supported_claim validator PASS. 새 브라우저 E2E를 수행한 것으로 계산하지 않는다. 기존 브라우저 HOLD/새 탭 미관측 제한은 유지한다.

개발 latest challenge5 replay 결과는 이전 결과와 byte-identical(SHA256 `63cd5d049b268bd5ab913d3b25c5fc452dc4eb5878bb0e2cd0bab95fa6f0aa1f`). Offline Hyundai/Samsung17/17을 현재 validator로 재실행해 이전 결과와 동일함을 확인했다. DB/OCR/embedding/LLM 호출은 모두0회다. 이전 전체 개발12/12/POSCO1/1/selected20/20 보고서는 재사용했으며 이번에 전체20개를 새로 재실행했다고 주장하지 않는다. Kia REVIEW, SK/Counts HOLD 유지. Sealed 및 기존 HOLD/REVIEW를 승격하지 않는다. `regression-summary.json`, `regression-latest.log`, `regression-offline.log`에 근거를 저장했다.

## 11. 남은 문제

8GB에서 실제 swap 압박 및 느린 토큰 생성이 남는다. 원인별 인과 비중, 통제된 실제 warm 반복, 전역 Ollama 동시성, 생성 중 Docker peak, 과거 DB exit2 원인은 미확인이다. replicatord의 실제 동기화 기능 정상 여부도 실행 PID만으로 PASS 처리하지 않는다. 기존 실 Gemini/fallback·새 PDF upload·citation 새 탭 제한을 유지한다.

## 12. 다음 작업

새 프로세스는 시작 시 직접 실행한 핸들·명령·사용자·부모·시작 시각을 함께 기록하고, 불명확한 정리는 BLOCKED로 남긴다. 다음 성능 실험은 동일 질문 B·후보·모델 옵션·토큰 수를 고정하고 host load와 생성 중 Docker stats를 수집해야 한다. 추가 LLM 호출은 필요한 최소 비교로 제한한다. 공유 Docker 메모리/다른 앱/공유 Ollama 조정은 별도 승인 없이 하지 않는다. 이번 자료로 DB exit2 원인을 확정할 수 없으므로 crash 순간의 backend 및 kernel 로그 수집이 우선이다.

Artifact 접두사: `.e2e-persistent/service-quality/system-safety-20261013/`.
