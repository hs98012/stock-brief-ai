# Sealed holdout v1 — 최초 실행 환경 준비 결과

실제 holdout prediction/retrieval/scoring은 **NOT_RUN**이다. 최초 결과 디렉터리는
생성하지 않았다. 봉인 데이터·hash·기준 source는 변경하지 않았다.

1. **변경 파일**: 신규 `scripts/blind_eval/{__init__,isolation,prediction,scoring,ledger}.py`,
   `scripts/prepare_blind_evaluation.py`, `scripts/run_blind_evaluation.py`,
   `scripts/blind-eval-services.yml`, `backend/tests/test_blind_evaluation_adapter.py`,
   `evals/blind-evaluation-v1-lock.json`, `evals/blind-evaluation-v1-lock.sha256.json`,
   이 문서. Production API/data model 변경은 없으며 작업 전 dirty 파일은 유지했다.
   준비 검증 자료는 ignored `evals/results/blind-adapter-preparation-v1/`에 저장했다.

2. **봉인 무결성**: 최초·최종 verifier VERIFIED, 문서 5개/질문 15개.
   Verifier는 gold bytes의 hash만 계산하며 답·질문별 expected HOLD를 해석하지 않는다.
   Gold schema 확인은 scoring 모듈의 `--schema-only`에서 필드명/타입만 출력했다.
   실제 질문을 prediction에 전달하거나 gold 성능 scoring을 실행하지 않았다.

3. **서비스**: PostgreSQL healthy, backend healthy, OCR worker healthy, frontend running.
   기존 이미지/볼륨을 사용했다. Backend entrypoint의 `alembic upgrade head`를
   임시 Compose override의 uvicorn entrypoint로 우회했다. 같은 안전한 override를
   `scripts/blind-eval-services.yml`로 보존했다. Migration/revision 변경/문서 변경/
   OCR 재처리 없음. `/health`, `/fingerprint`, Ollama `/api/tags`만 조회했다.

4. **Adapter 구조**: coordinator가 봉인 검증 및 lock 검증 후 최초 ledger를 예약한다.
   Prediction worker에는 allowlist로 만든 문서 metadata/PDF/질문/config만 staging한다.
   기존 `extract_pdf → structured_spans → retrieval_text → bge-m3 → rank_rows`를 사용한다.
   BM25/cosine/RRF/query parser/evidence selector는 기존 구현을 그대로 호출한다.
   In-memory isolated corpus로 active DB를 읽거나 쓰지 않는다.
   Prediction에는 top-5 results, selected evidence pack, requirements/coverage,
   page/span/bbox/quote, HOLD 및 실행 오류를 기록한다.
   Scoring은 별도 명령으로 frozen artifact hash를 검증한 뒤 gold/criteria를 읽는다.
   값/metric/기간/qualifier/scope/unit/estimate version 및 source span/page/bbox를 검사한다.
   원문 proof의 token 분할/geometry를 자동 확정할 수 없으면 REVIEW이며 자동 PASS가 아니다.

5. **Gold isolation**: prediction 입력의 gold/expected answer/expected HOLD/scoring metadata
   필드를 거부한다. Prediction은 scoring 모듈을 import하지 않는다.
   별도 macOS sandbox-exec process가 evals/docs 읽기를 차단하고 자기 staging만 허용한다.
   Python audit hook도 직접 open/os.open/symlink를 차단한다.
   Synthetic sentinel로 embedding/BM25/vector/RRF/query parser/selector 및 생성 seam을 검사했다.
   macOS sandbox가 없거나 적용 실패하면 실제 실행을 허용하지 않는다.
   이는 이 호스트의 실행 경계이며 암호화·외부 WORM·관리자 공격 방어를 주장하지 않는다.

6. **Synthetic dry-run**: adapter/isolation 23 tests PASS. 정상 evidence PASS,
   근거 부족 HOLD, 잘못된 citation/unit/부분 evidence REVIEW, 모델 실패 ERROR,
   실제 extractor seam의 OCR worker 실패에 대해 문항별 ERROR 보존,
   gold 필드 주입·직접 파일 접근 차단, saved artifact scoring과 overwrite/tamper 차단 확인.
   실제 모델·OCR inference는 synthetic 테스트에서 호출하지 않았다.
   Synthetic 결과는 `synthetic-dry-run.json`에 구분 저장하며 holdout 분모에 포함하지 않는다.
   합성 답변 함수 seam의 성공은 생성 답변 factual correctness 검증을 뜻하지 않는다.

7. **설정 고정**:

   - Code commit: `28061c63186020b3302b5918fda49f34ff42ab63`.
     Dirty worktree이므로 봉인된 baseline source hash와 신규 adapter source hash도 검증한다.
   - Embedding: Ollama bge-m3, 1024차원,
     digest `7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab`.
   - LLM config: Gemini `gemini-3.7-flash`, fallback Ollama `gemma3:4b`, temperature 0.
     첫 단계에서 생성 호출은 0이며 실제 LLM version/availability는 NOT_VERIFIED_NOT_USED.
   - OCR: sealed image `sha256:91bd57fbf76cbcd89aa38772c911b210f016a5ceeadefbc3ebb1f214d375f228`.
     PP-StructureV3/korean PP-OCRv5; 실제 weight/package/options fingerprint
     `792ea7f37bc9cfa2ecf9651a1754148022d9f05c5776efa07b45e8fd1b6f10a0`.
     Sealed OCR_DPI=300, worker render_dpi=216. Frozen parser/source hashes 유지.
   - Chunking: structured_spans max_chars=1200, 구조 경계 분할, overlap 없음.
   - Retrieval: BM25Okapi + isolated exact cosine, RRF k=60,
     candidate=max(top_k*4,20), top-k=5, rerank/diagnostics=true.
     기존 active pgvector 구현은 변경하지 않았으며 offline adapter는 동일 cosine을 메모리에서 계산한다.
   - Evaluation schema v1, 봉인 criteria SHA-256
     `0aaec2085aa0f208334a4cdae88e933620a7808613c4e67157171b408296f68a`.
   - 봉인 configuration SHA-256
     `c1f343b76d45744d6ecc9cc603ade808d2dda8fb9fb62509ae75428595d615da`.
   - 신규 runtime/adapter lock configuration SHA-256
     `2ebceaf80a38250dad3077d19b4ce773b653b12ad3380d99fbee55fd7acf2332`.

8. **향후 최초 실행 명령** — 이번에는 실행하지 않았다:

   ```bash
   .venv/bin/python scripts/run_blind_evaluation.py --manifest evals/sealed-holdout-v1-manifest.json --execute-first-run
   ```

   실행 옵션을 생략하면 봉인/lock/code만 확인하고 prediction/retrieval/scoring은 실행하지 않는다.
   Prediction을 고정한 후 scoring을 별도 실행한다:

   ```bash
   .venv/bin/python -m scripts.blind_eval.scoring --manifest evals/sealed-holdout-v1-manifest.json --run-dir evals/results/sealed-holdout-v1-first-run
   ```

   기존 collector와 같은 최초 output 경로를 사용하므로 한쪽이 경로를 예약하면 다른 쪽도 실패한다.
   새 adapter 명령을 사용해야 OS gold isolation과 문항별 실패 보존을 적용할 수 있다.

9. **결과 보존**: `evals/results/sealed-holdout-v1-first-run/`의 exclusive mkdir로
   UUID Run ID/timestamp/commit/configuration hash/manifest hash를 `run.json`에 기록한다.
   `predictions/input.json`, staged PDF, document pages/provenance,
   문항별 `*.prediction.json`, `worker.json`, `completion.json`,
   `artifacts.sha256.json`, 별도 `scoring.json`/`scoring.sha256.json`을 보존한다.
   예외/worker crash는 ERROR record로 남기며 자동 문항 재시도는 없다.
   시작 이후 실패한 디렉터리는 삭제/성공 run으로 대체하지 않는다.
   Hard kill 시에도 예약 ledger/이미 저장된 문항은 남고 재실행은 거부된다.
   초기 runtime preflight 자체가 실패하면 평가하지 않은 전체-run ERROR를 보존한다.
   Python 처리 가능한 실패 후에는 prediction artifact를 SHA-256 고정/읽기 전용 처리한다.
   Scoring도 exclusive 파일 생성으로 덮어쓰기를 거부한다.

10. **DB READ ONLY 전후 비교**: REPEATABLE READ READ ONLY snapshot의 5개 table 모두 일치.

   | Table | Count | Before = after SHA-256 |
   |---|---:|---|
   | documents | 10 | `90a528749fa287d8614fe5383fa6c8a37f67498e778206108d5796860565f8b4` |
   | pages | 75 | `1cf7866151671415c87cc90b8a439c48969ebdc7a95611ba289fc041179cb575` |
   | chunks | 231 | `bce2ec67ef0b99dca798891b76998fedc9cbbe969c01a749906619198033bf0e` |
   | analysis_runs | 311 | `ce0bab08903d1fafb004361a493d67ff41ae332ca93563faf92715d5b70810fd` |
   | page_extractions | 0 | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` |

11. **전체 회귀 검증**: `./scripts/check.sh` PASS. Backend 536 passed/1 skipped,
   frontend 7 passed, lint PASS, production build PASS, py_compile PASS, git diff --check PASS.
   Skip은 로컬 `.venv`의 `google.genai` 미설치로 Gemini SDK 관련 테스트 1개가 생략된 것이다.
   `verify_composite_units.py`를 기존 immutable artifacts로 다시 실행했다.
   현대차 offline PASS(15 cached outcomes hash 검증), 삼성 offline PASS,
   기아 manual review, SK HOLD, Counts HOLD, 개발 12/12, POSCO evidence coverage 1/1,
   selected pack 20/20 불변, review-aware/effective false-complete 0 유지.
   기존 challenge replay는 sealed 15개와 별개이며 새로운 holdout retrieval을 실행하지 않았다.

12. **남은 blocker/한계**: 봉인된 criteria의 첫 단계는 retrieval/evidence 전용이다.
   따라서 최초 실행에서 생성 답변 정확성/answer HOLD/factual correctness는
   NOT_VERIFIED이며 정상 evidence COMPLETE에도 generated answer는 없다.
   Generation seam은 synthetic 함수 주입으로 검사했지만 production QA 생성 adapter,
   생성 답변의 의미 단위 판정, 실제 Gemini model version/availability 검증은 미완료다. 로컬 `.venv`에는
   `google.genai` SDK도 없어 생성 단계를 실행할 수 없다.
   전체 생성 evaluation을 요청하려면 기존 봉인을 수정하지 않고 별도의 사전 확정된
   생성 단계 configuration/schema가 필요하다. Gold second human review는 기존대로 미수행.
   REVIEW proof를 수동으로 승인하기 전 자동 PASS로 바꾸지 않는다.

13. **실행 준비 여부**: 봉인된 최초 **retrieval/evidence blind evaluation은 준비 완료**.
   전체 **생성 답변 end-to-end evaluation은 준비 미완료**이며 위 blocker가 남는다.
   봉인 질문의 실제 성능은 확인할 수 없습니다.
