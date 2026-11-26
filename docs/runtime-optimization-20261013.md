# Stock Brief AI 성능·안정화 결과 — 2026-10-13

**판정: PARTIAL.** 기존 근거 품질을 유지한 최종 브라우저 분석은 119.61초로 완료했다. 과거 374.37초 대비 관측 시간은 68.1% 감소했지만, 이번 반복 실행도 108.71→304.05초로 흔들렸고 실제 swap이 증가했다. 안정적인 8GB 운영이 확보됐다고 주장하지 않는다. Gemini 실전송과 실 fallback은 승인 없이 실행하지 않았다.

## 1. 이전 작업 재사용

HEAD `28061c63186020b3302b5918fda49f34ff42ab63`와 기존 dirty tree를 보존했다. persistent E2E PostgreSQL(port55433), PDF 9페이지, extraction9, chunks/vectors583, bge-m3 vector(1024), retrieval·requirement·UI·source-owned bbox를 재사용했다. OCR·chunk 재생성·재임베딩·migration을 실행하지 않았다. 대규모 기존 미커밋 변경을 이번 변경이라고 계산하지 않는다.

## 2. Mac 8GB 메모리 분석

물리 RAM 8,589,934,592 bytes, Docker VM MemTotal4,109,152,256 bytes(약3.827GiB). 시작 시 Ollama 적재 모델은0이었다. 분석 중 gemma3:4b 한 모델만 관측했다. 최종 분석의 Ollama runner 최대 RSS는3,766,927,360 bytes(약3.51GiB); GPU/unified memory와 RSS를 더해 총량이라고 주장하지 않는다. 호스트 전체 메모리 peak와 정확한 Available memory는 NOT_VERIFIED.

## 3. Memory pressure·swap

최종 분석 계측창: swap4618.06→7368.44MiB, **+2750.38MiB**, peak7418.81MiB. Pageouts+4233, Swapouts+3,661,604 pages(16KiB page size). `memory_pressure -Q`의 free percentage 최저8%. 첫 분석의 swap peak8056.81MiB도 기록했다. 실제 swapping과 메모리 압박은 확인됐지만 과거344초 중 메모리만의 기여 시간은 확인할 수 없습니다. `pmset -g therm`은 경고 기록 없음; 실제 thermal throttling 여부는 NOT_VERIFIED.

프로세스별 RSS/%CPU와 /api/ps는 분석 전·적재·생성·완료 구간을 샘플링했다. FastAPI/Next/Chrome/Codex/Docker를 구분하는 원시 자료는 `optimization-*-memory.json`에 있다. PostgreSQL과 OCR는 호스트 ps에서 직접 구분되지 않는 container 서비스다. OCR 전용 container는 기존 Exited 상태를 유지했다. 최종 E2E PostgreSQL Docker stats는74.42MiB/CPU0.01%; 이는 생성 중 peak가 아니다. 다른 프로젝트 container를 중지하지 않았다.

## 4. Ollama 로딩·토큰 속도

호스트 버전0.40.3, gemma3:4b Q4_K_M, context4096, native runner np1 관측. 최종 load6.469초, prefill6.726초/1419tokens, generation75.074초/624tokens, **8.312tokens/sec**. 과거는1.907tokens/sec였다. 모든 `warm` 라벨 실험도 native load5.6~7.1초를 보여 실제로는 cold/reload였으며 warm 성공으로 계산하지 않았다. 60초 keep_alive의 cold-start tradeoff가 남는다.

공식 [Ollama FAQ](https://docs.ollama.com/faq), [Generate API](https://docs.ollama.com/api/generate), [Embedding API](https://docs.ollama.com/api/embed), [option 정의](https://github.com/ollama/ollama/blob/main/api/types.go)를 확인했다. 공유 호스트의 MAX_LOADED_MODELS/NUM_PARALLEL 설정을 임의 변경하지 않았다.

## 5. Gemini 실제 호출 구조

분석 서비스는 호재·악재를 함께 담은 packet으로 **generate1회**를 호출한다. 별도 호재/악재 Gemini 요청은 없다. 과거344초 run은 Gemini0/Ollama1/fallback없음으로 trace에서 확인됐다. Gemini3회 가설은 이 실행에서 기각된다. 외부 Gemini 실요청의 횟수·시간은 NOT_VERIFIED.

## 6. Timeout·retry·fallback

기존 google-genai2.18.1 Interactions는 attempts1을 내부 retry1로 매핑했다. 실제 SDK+MockTransport429 실험에서 application call1이 HTTP2회가 됨을 확인했다(`optimization-old-sdk-retry.json`). application 최대2회와 겹치면 primary HTTP최대4회가 가능한 구조였다.

공식 [Google SDK GenerateContent](https://googleapis.github.io/python-genai/)로 변경하고 SDK attempts1(최초 요청 포함), application retry loop만 유지했다. 실제 SDK MockTransport429/500/502/503/504에서 application2/HTTP2를 확인했다. 정상 JSON/schema, usage, safety 차단도 실제 SDK를 통해 mock 검증했다. 기본 timeout30초/최대2회/대기1초이며 Ollama timeout은600초다. timeout/network/rate limit/일시 서버 오류 후 configured fallback, unavailable/양쪽 실패/단일 run 기록은 기존 provider 테스트로 검증했다. 인증·모델 설정·safety·schema 실패는 자동 retry/fallback으로 숨기지 않는다. 실 Gemini→Ollama fallback은 **NOT_VERIFIED**.

## 7. 344초 세부 원인

| 단계 | 과거 | 최종 |
|---|---:|---:|
| Retrieval + factual evidence verification |25.975s|25.401s|
| Prompt 구성 |NOT_VERIFIED|0.000052s|
| Gemini 대기/retry/fallback |0|0|
| Ollama load |8.068s|6.469s|
| Ollama prefill |8.033s|6.726s|
| Ollama token generation |327.262s|75.074s|
| 전체 generation stage |344.496s|89.452s|
| Response/card validation + citations |2.651s|4.726s|

과거 generation의 약95%는 token generation이었다. 여러 Gemini 요청의 누적 대기였다는 근거는 없다. Native 단계 합계 밖의 scheduler/HTTP/JSON 검증은 aggregate overhead이며 개별 분리는 NOT_VERIFIED. Evidence verification은 retrieval에, 최종 card grounding/변환은 validation에 포함된다. 최종 persist 전119.591초, DB run elapsed119.608초; 저장 차이는 약0.017초다. 별도 브라우저 network stopwatch는 측정하지 않았다.

## 8. 실제 수정 파일

- backend/app: `generation.py`, `local_inference.py`(신규), `embeddings.py`, `database.py`, `analysis_service.py`.
- backend/tests: `test_low_memory.py`, `test_generation_transport.py`(신규), `test_analysis.py`의 privacy·SDK 계약.
- scripts: `measure_e2e_generation.py`(신규), `run_service_e2e_api.py`.
- frontend: `next.config.ts`, `eslint.config.mjs`의 E2E/check build cache 분리.
- `.env.example`, `.gitignore`, 계약3문서, checkpoint/이 보고서. 기존 replay 도구는 새 runtime-optimization artifact directory로 복사하여 원래 결과를 덮어쓰지 않았다.

## 9. 채택한 저메모리 설정

개발 전용 `STOCK_BRIEF_LOW_MEMORY=1`: local embedding/generation을 단일 process RLock으로 순차 실행, embed keep_alive0, generation keep_alive60s/num_ctx4096, PostgreSQL application pool2/overflow0, E2E API worker1. Production/default 설정을 덮지 않는다. 추론 lock은 다른 process/다른 Ollama client와 retrieval 전체를 제한하지 않으므로 서버 전체 동시성 제한이라고 주장하지 않는다. Query embedding 외에 기존583vectors를 다시 생성하지 않았다. chunk/검색/인용 필수 기능은 유지됐다.

## 10. LLM 호출·prompt 개선

확인된 SDK 중첩 retry는 제거했다. pipeline generation 호출은 이미1회여서 합치거나 제거하지 않았다. 원문·facts·전체 UUID·output schema·출력 token cap은 그대로 유지했다. UUID축약+batch128 실험은83.72/69.11초였으나 최종 카드가2→1로 감소했다. batch128 단독도1개로 줄어 **두 실험 모두 코드에서 제거**했다. 빠르다는 이유로 coverage 저하를 채택하지 않았다. 기존 진행 안내는 확인했으며 검증 전 텍스트 streaming은 추가하지 않았다.

## 11. DB worker 종료 원인

과거 E2E PostgreSQL worker exit code2와 recovery 반복을 확인했다. Container OOMKilled=false/RestartCount0이라 OOM으로 단정하지 않는다. 2026-10-12T15:37Z의 별도 종료는 fast shutdown/administrator command로 확인되지만, 이 사실로 worker exit2 원인을 설명하지 않는다. 근본 원인은 **UNKNOWN**. 확인한 마지막 worker exit2는2026-10-13 15:37:54 KST(06:37:54 UTC), 뒤이은 recovery 완료는15:38:13 KST다. 이번 계측 중 새로운 worker exit2는 관측되지 않았다. pool 설정은 예방적 제한이며 crash를 고쳤다고 주장하지 않는다. E2E volume을 재생성/수정하지 않았다.

## 12. 전후 성능

| Metric | Before | After(최종 채택 설정) |
|---|---:|---:|
| Total latency |374.374s(browser)|119.608s(server run; browser 완료 확인)|
| Generation stage |344.496s|89.452s|
| Gemini calls |0(trace 확인)|0|
| Ollama generation calls |1|1|
| Prompt tokens |1419|1419|
| Output tokens |624|624|
| Tokens/sec |1.907|8.312|
| Peak memory |NOT_VERIFIED|Ollama RSS3.51GiB; system peak NOT_VERIFIED|
| Swap increase |NOT_VERIFIED|+2750.38MiB|
| Citation count |2|2|
| Factual correctness |이전 source 검증|동일 후보·최종 선택·원문 hash 및 UI 재검증|

동일 질문/문서/provider/model/schema/candidates와 validated selection을 비교해 일치를 확인했다. 관측 전체 시간은254.77초(68.1%), generation은255.04초(74.0%) 감소했다. CPU·swap·host load가 동일하게 통제되지 않아 인과 효과나 안정적 latency 보장으로 해석하지 않는다. 짧은 다른 질문의108.71/304.05초는 참고 실험이며 동등 비교로 쓰지 않는다.

## 13. 호재·악재 사실 정확성

최종 run `032a7521-91c6-4cdc-891d-f6b95023ba6e`: 호재2/악재0, ‘영업이익 증가’, ‘전자·이노텍 매출 증가’는 각각 literal source 근거와 일치. 음수 카드를 임의 생성하지 않았다. 실제+전망 복합 수치 질문은 coveragefalse/HOLD, LG CNS 단위 질문은 ambiguous_requirement/HOLD였다. 근거 없는 수치/단위 추론을 차단하고 정확히 `확인할 수 없습니다`를 표시했다.

## 14. Citation·bbox

페이지3 citation2개, 실제 이미지2개 loaded, source-owned bbox9개를 DOM에서 확인했다. PDF3→4 이동과 page4 이미지 loaded를 확인했다. Citation 링크 클릭은 시도했지만 IAB의 새 탭 생성은 관측되지 않아 클릭만으로 새 탭 navigation PASS라고 기록하지 않는다. 관측된 href를 직접 열어 실제 원문 viewer와 페이지 이동을 추가 검증했다.

## 15. 브라우저 E2E

기존 dev13002는 hydration 후 문서 loading에 머물렀다. 초기 원인은 확정하지 않았다. 분리한 `.next-e2e` production UI13003에서 문서 선택583/583, 분석 요청, 진행 중/버튼 비활성, 최종 카드/citation/bbox, source page viewer, 두 HOLD 화면을 실제 확인했다. API 성공만을 브라우저 성공으로 계산하지 않았다. 새 PDF 업로드는 범위 밖이며 수행하지 않았다. 최종 사용자 흐름의 링크 새 탭 동작은 위 제한을 유지한다.

## 16. 회귀

최종 `./scripts/check.sh`: **backend675/frontend11/lint/build PASS**. PyMuPDF/asyncio 및 SDK deprecation20 warnings. 분리된 generated build directory를 ESLint가 소스로 검사하던 설정을 고쳤으며 source 검사나 테스트를 생략하지 않았다.

현재 validators로 개발12/12, POSCO1/1, selected pack20/20, offline Hyundai/Samsung17/17 동일을 재실행했다. Kia REVIEW, SK/Counts HOLD, review-aware false-complete0 유지. 결과는 `evals/results/runtime-optimization-20261013/regression-summary.json`; sealed v1 재실행/재채점 없음.

## 17. 무결성·실행 안전성

시작/최종 snapshot의 pages/page_extractions/chunk UUID/source/provenance/vector hash 모두 동일,583 finite/nonzero vector(1024), missing0. Sealed114 files SHA256/immutable flags 동일. Production DB/volume 접근·migration/active revision/gold/manifest/first-run/immutable 변경 없음. Production 데이터 자체의 hash는 접근 금지 때문에 NOT_VERIFIED.

실행 실수: API 재시작 중 검증하지 않은 PID12080에 TERM을 보내 macOS replicatord를 잘못 종료했다. 이후 실제 E2E PID는 port/start log로 확인해 처리했다. `launchctl list`에서 com.apple.replicatord 등록/종료 상태0/대기 상태를 확인했으며 재실행 PID는 NOT_VERIFIED. 이 사고를 DB worker 과거 종료 원인과 연결하지 않는다.

## 18. 남은 blocker·판정

**PARTIAL**: 근거 정확성과 583vectors 무결성을 유지한 분석/인용/페이지/HOLD 및 회귀는 확인됐다. 실제 swap 압박,108~304초 변동, warm 유지, global 모델 동시성, 과거 DB worker exit2 원인은 해결됐다고 할 수 없다. 외부 Gemini 실요청/실 fallback과 IAB citation 새 탭 navigation도 NOT_VERIFIED다. 승인 없이 공유 Docker/Ollama 설정이나 다른 프로젝트 서비스를 변경하지 않았다.

재개: `PYTHONPATH=backend .venv/bin/python scripts/run_service_e2e_api.py --low-memory`; UI는 frontend에서 `NEXT_DIST_DIR=.next-e2e npm run start -- --hostname 127.0.0.1 --port 13003`. 계측은 새 label로 `PYTHONPATH=backend .venv/bin/python scripts/measure_e2e_generation.py --label NEW_LABEL --low-memory`. 품질 저하 실험을 재적용하지 않는다. Check는 `NEXT_DIST_DIR=.next-check NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:18002 ./scripts/check.sh`. Shared host 서비스 조정/실 Gemini 전송은 별도 승인 필요.

Artifact 접두사: `.e2e-persistent/service-quality/optimization-*`. 핵심: accepted-run/accepted-metrics, browser-final.json/png, browser-numeric/unit, source-page4, metrics, old-sdk-retry, check-accepted.log, db.log/state/stats, sealed-integrity 및 snapshot-optimization-{before,final}.json. 기존 artifacts를 덮어쓰지 않았다.
