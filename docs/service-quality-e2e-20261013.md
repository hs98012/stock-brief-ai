# Stock Brief AI 재개 검증 보고 — 2026-10-13

## 1. 중단 당시와 현재
HEAD `28061c6`. 미커밋 구현과 기존 artifacts를 보존했다. 중단 직전 카드 중복 테스트 1개가 실패했으며 valid/perspective/span fixture를 보완해 통과했다. Docker·API·UI는 중단 후 종료되어 기존 volume을 재사용해 기동했다.

## 2. 재사용한 완료 작업
583개 bge-m3 embedding, 요청 내 검증 cache, strict requirement resolver, SDK dependency/error handling, compact generation prompt, 단계 timing, source-owned citation geometry, 원문 페이지 viewer, 업로드/오류/저장 분석 UI. OCR·chunk 생성·재임베딩을 반복하지 않았다.

## 3. 이번 새 구현
문서가 다른 fact를 중복 카드로 병합하지 않도록 guard를 추가했다. 중단 직전 구현된 cross-page fact 중복 제거와 제목의 선행 조사 정리를 검증했다. 변경 상태·검증·재개 지점을 checkpoint에 영구 기록했다.

## 4. 주요 파일
`backend/app/{analysis_service,evidence_facts,analysis_retrieval,evidence_bundle,verification_cache,structured_cells,search,generation,citation_geometry,embedding_service,main,schemas}.py`, `backend/tests/test_card_deduplication.py` 및 관련 회귀 테스트, `frontend/app/{page,analysis-view,api}.tsx/ts`, `frontend/app/source/`, `scripts/{service_e2e,run_service_e2e_api}.py`, `api-contract.md`, `acceptance.md`, `qa-rules.md`. 대부분 이전 통합 작업의 변경이며 전체 dirty tree를 이번 변경이라고 주장하지 않는다.

## 5. DB/embedding 무결성
port55433 전용 PostgreSQL, external volume `stock_brief_e2e_persistent_pgdata`. 9 pages, 9 page_extractions, 583 chunks/vectors. 각 vector 1024차원 finite/nonzero. 재개 snapshot의 원문/provenance/UUID/vector hash가 이전 재시작 snapshot과 완전히 동일하다. 기존 idempotent 검증 processed0/skipped583/failed0. 이번 embed 호출 없음.

## 6. Requirement/evidence
Analysis strict resolver는 supported/unsupported/ambiguous/error/topic-only를 구분하고 factual requirement 누락을 HOLD한다. 원문 unit/period/scope proof를 유지한다. LG CNS 3.42 단위는 source-owned owner가 유일하게 입증되지 않아 HOLD 유지; 임의 조원 연결 없음. Legacy search 계약을 분리해 frozen pack을 보존했다.

## 7. 성능
같은 질문·데이터·설정의 unprofiled 검색 **88.068 → 15.705초(82.2% 감소)**, 결과 JSON 동일. 요청 내 원문 검증과 geometry 중복 계산을 줄였다. 기존 688초는 다른 factual 질문이므로 직접 비교하지 않는다. 이전 실제 summary E2E 392.1 → 72.2초; 모델/호스트 부하도 영향을 줄 수 있어 prompt만의 인과 효과로 단정하지 않는다. CPU/메모리 이전 비교는 NOT_VERIFIED.

## 8. LLM/fallback
google-genai2.18.1 dependency 확인. timeout/429/schema/성공/fallback은 mock 테스트 통과, 실제 로컬 gemma3:4b 생성 완료. Gemini 실호출은 자동 승인 검토가 보고서 근거 외부 전송의 별도 승인 부족으로 차단했다. local-only launcher로 검증했고 우회 전송 없음. 실제 Gemini→Ollama fallback은 NOT_VERIFIED.

## 9. Frontend
처리/임베딩 준비 상태, 실제 카운트, 409/config/retrieval/timeout/network 오류 안내, 저장 분석 재사용, 호재·악재 카드, 관측 bbox overlay, deterministic source physical-page viewer 구현. 서버에 없는 OCR 진행률이나 bbox를 만들지 않는다. 동일 PDF duplicate upload API는 재사용 확인; 브라우저 file attachment는 도구 root 제한으로 NOT_VERIFIED. 새로운 PDF OCR end-to-end는 재실행하지 않았다.

## 10. 실제 브라우저
기존 local Ollama summary: completed, 원문 citation/card 표시 확인. 영업이익 실제+전망 수치 질문: HOLD insufficient_evidence. LG CNS 단위 질문: HOLD ambiguous_requirement. HOLD는 정확성 정책의 정상 동작이며 answerable 성공으로 계산하지 않는다. 이전 원문 p3 → p4 viewer와 bbox4개 alignment 확인. 최신 최종 summary 결과는 아래 추가 기록한다.

## 11. 전체 검사
`./scripts/check.sh` 호스트 실행 **backend666 passed, frontend11 passed, lint 및 production build PASS**. sandbox 실행은 OS native sandbox test가 중첩 sandbox에서 시작하지 못해 665 passed/1 failed였다. 테스트를 수정하거나 생략하지 않고 호스트 재실행으로 원인을 검증했다. 경고19개는 PyMuPDF/asyncio deprecation이다.

## 12. Challenge 회귀
이전 통합 코드 replay: combined 개발12/12, POSCO1/1, selected pack20/20 동일, Hyundai/Samsung latest offline17/17 동일. Classic recall11/12는 전후 동일하며 combined12/12와 구분한다. Kia manual REVIEW, SK/Counts HOLD 유지. 경제 fact/pack 선택 정책 변경 없음; 카드 표시 중복 제거와 fixture만 이번 변경했다.

## 13. False-complete
Review-aware false-complete0 유지. 근거 없는 음수 카드 또는 수치를 만들지 않고 unknown은 `확인할 수 없습니다`. HOLD와 REVIEW를 strict PASS로 승격하지 않았다.

## 14. 보호
Sealed114 files SHA256/immutable flags unchanged; holdout 재실행·재채점·manifest/gold/first-run 수정 없음. Production DB 접속/volume 변경/migration 없음; Production PostgreSQL Exited 유지. Production 실제 데이터 hash는 접속 금지 때문에 NOT_VERIFIED이며 container 상태를 데이터 hash 증명으로 취급하지 않는다.

## 15. 남은 문제
실제 Gemini/fallback 전송 승인, 브라우저 새 파일 upload/OCR 경로, 더 넓은 answerable factual query 검증, E2E PostgreSQL 과거 worker exit의 근본 원인. 호재 summary만 성공했다고 모든 factual 질문의 서비스 품질이 확보됐다고 주장하지 않는다.

## 16. 다음 우선순위
Gemini 명시적 근거 전송 승인 후 실제 fallback → 허용된 브라우저 file upload 경로 검증 → 개발 source proof 기반 추가 factual coverage → PostgreSQL 종료 원인 및 latency 변동 관측. Production 변경은 별도 승인 필요.

## 17. 판정
**PARTIAL**. 보존된 PDF/embedding으로 로컬 근거 기반 분석과 citation 화면은 동작하고 전체 검사는 통과했다. 외부 모델 실검증과 새 PDF 업로드 전체 경로 및 넓은 factual coverage가 남아 있다.

최신 브라우저 run `dbcbcff7-2d1e-4465-9d7f-7955c3bb9734`: **completed, 374.374초**, 중복 없는 호재2개/악재0개/citation2개. 제목 `영업이익 증가`, `전자·이노텍 매출 증가`를 실제 DOM에서 확인했다. 원문 p3 링크2개, 이미지2개 loaded, 관측 bbox9개 렌더링 확인. 기능 PASS, 합리적이고 안정적인 시간 요구는 미완료다. DB 자동 recovery가 재발했고 컨테이너 OOMKilled=false/RestartCount0라 OOM을 원인으로 단정하지 않는다. unrelated containers가 함께 기동했지만 임의 중지하지 않았다. 추가 LLM 재실행은 하지 않았다.

최종 단계 시간: retrieval/verification25.975초, generation344.496초, validation/citations2.651초. 분석 후 snapshot도 완료되어 source/provenance/UUID/vector hash 모두 동일, vectors583/missing0을 확인했다. 지연의 대부분은 이번 실제 로컬 generation이며 검색 개선 수치와 구분해야 한다.

Artifacts는 프로젝트 영구 경로 `.e2e-persistent/service-quality/`에 저장했다. `check-resumed-host.log`, `snapshot-resumed-final.json`, `snapshot-resumed-post-analysis.json`, `sealed-resumed-final.json`, `regression-summary.json`, `runs.json`, `browser-{summary,numeric,unit}.json`, `browser-resumed-final.json`, `run-resumed-final-trace.json`, `db-resumed-final.log` 및 checkpoint를 참조한다. 기존 결과는 보존했다.

후속 성능·안정화 통합 작업: `docs/runtime-optimization-20261013.md`의 18개 항목과 checkpoint 최종 기록을 참조한다. 동일 질문·후보·토큰 수의 최종 브라우저 분석119.608초/generation89.452초, 호재2/citation2/bbox9, backend675/frontend11/lint/build 및 개발12/12/selected20/20 PASS. 실제 swap 증가와108~304초 반복 변동, DB worker 원인 UNKNOWN, 실 Gemini/fallback 및 citation 새 탭 제약 때문에 PARTIAL 유지. 품질이 줄어든 UUID축약/batch128 실험은 제거했다.
