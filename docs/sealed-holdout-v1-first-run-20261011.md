# Sealed Holdout v1 — 최초 retrieval/evidence 결과

15개 질문을 공식 adapter로 정확히 한 번 실행했다. 모든 prediction은 HOLD이며 answerable 10개는 false-HOLD, expected HOLD 5개는 올바른 거절이다. False-complete=0. 전체 LLM 답변 생성 평가는 수행하지 않았다.

1. **실행 준비 검증**: 기존 first-run 경로 없음 확인 후 manifest/PDF/gold bytes/config/policy/code/adapter hash 검증 PASS. PostgreSQL/backend/OCR worker healthy, bge-m3 digest 및 OCR image/weight fingerprint 일치. In-memory corpus와 staged allowlist/OS sandbox/Python audit guard로 active DB 및 gold를 분리했다. Prediction 원본을 hash/0444로 고정한 후에만 별도 scorer가 gold를 읽었다. Gold leakage 관측 없음. 최초 health 조회는 다른 서비스의 port 8000이었으며 Compose의 실제 backend port 8001에서 확인한 뒤 평가했다. 서비스 설정은 변경하지 않았다.

2. **First-run ID**: `7db3bde0-1c92-4c7c-b0c2-f9a73c7db505`. 시작 `2026-10-10T21:37:50.333718+09:00`, 종료 `2026-10-10T22:42:18.357898+09:00`. Code commit `28061c63186020b3302b5918fda49f34ff42ab63`. Manifest `e953979e5413db83d4355b205ddfacf6abdfbb8ceef4cfaa2e84d1a5f5527b57`, config `2ebceaf80a38250dad3077d19b4ce773b653b12ad3380d99fbee55fd7acf2332`, policy `0aaec2085aa0f208334a4cdae88e933620a7808613c4e67157171b408296f68a`.

3. **실행된 질문 수**: 15/15. 문서 5개/29페이지의 extraction artifact 저장. 질문별 top-5 총 75개; vector search 15/15 사용. 질문 재시도 0, generation 호출 0.

4. **완료/실패/미실행**: prediction 및 scoring 완료 15, infrastructure ERROR 0, timeout 0, 미실행 0. Semantic false-HOLD 10개는 실행 실패와 구분한다. PASS 0, HOLD 15, REVIEW 0, automatic strict 0, manual accepted 0. 원본 completion은 별도 scorer 호출 전 상태인 COLLECTED_NOT_SCORED로 보존되며 별도 scoring.json이 scoring 완료의 증거다.

5. **Answerable 10개**: 충분한 evidence 0/10, 불충분하여 HOLD 10/10. Selected evidence pack은 모두 비어 있다.

6. **Expected HOLD 5개**: 올바른 HOLD 5/5, complete로 잘못 승인 0/5. 모든 질문을 HOLD한 결과이므로 이 수치만으로 negative 원인 판별 능력을 주장하지 않는다.

7. **봉인된 8개 지표**:

   | 지표 | 최초 고정 점수 |
   |---|---:|
   | Coverage completeness | 0/10 (0%) |
   | Exact factual correctness | NOT_VERIFIED — 분모 15 유지, 생성 답변 없음 |
   | Strict evidence validity | 0/10 (0%) |
   | False-complete count | 0/15 (0%) |
   | Source page accuracy | 0/15 (0%) |
   | Scope/unit correctness | 0/15 (0%) |
   | HOLD precision | 5/15 (33.33%) |
   | Retrieval evidence recall@5 | 0/15 (0%) |

   원본 scoring.json 및 기준/분모는 변경하지 않았다. HOLD recall은 별도 5/5, selected pack의 검증된 fact recall 0/15이다.

8. **False-complete**: 0. Review-aware도 0이며 manual 승인으로 제외한 사례는 없다.

9. **False-HOLD**: 10. Answerable 문항을 모두 거절했다.

10. **Citation/page/span**: selected pack의 source page score 0/15, strict page/span/bbox/quote proof 검증 성공 0/15. 제출된 citation 자체가 없어 citation 조건부 precision은 산출 불가다. 98개 gold proof component는 수정하지 않았다. 참고 진단으로 top-5에 지정 source page가 있는 fact는 14/15지만, 이는 page availability일 뿐 봉인 page accuracy나 proof recall 점수로 대체하지 않았다.

11. **Scope/unit**: 0/15. `coverage_complete` true=0, false=7, null=8을 구분한다. null은 false로 기록을 바꾸지 않았으며 adapter 정책상 true가 아니어서 HOLD다.

12. **Retrieval evidence recall**: frozen scorer 0/15. 다음 scorer 한계가 확인되어 해석에 포함한다: gold 15개 fact 모두 value_status를 요구하지만 retrieved candidate는 status만 노출하여 fact_check의 literal field 비교를 통과하지 못한다. 7개 fact는 다른 페이지의 scope proof를 갖는데 scorer는 모든 proof가 main source_page에 있어야 한다고 검사한다. 이 한계는 retrieval의 실제 텍스트 검색 능력이 0이라는 뜻이 아니다. 점수나 schema를 고치거나 재채점하지 않았다.

13. **질문별 결과 및 14. 최초 failure layer**:

   | 질문 ID | 사전 분류 | 결과 | 오류 분류 | 최초 관측 실패 계층 |
   |---|---|---|---|---|
   | sh1-naver-01 | answerable | HOLD | false-HOLD | table geometry / fact association |
   | sh1-naver-02 | answerable | HOLD | false-HOLD | table geometry / fact association |
   | sh1-naver-03 | expected HOLD | HOLD | correct HOLD | none |
   | sh1-kakao-01 | answerable | HOLD | false-HOLD | table geometry / fact association |
   | sh1-kakao-02 | answerable | HOLD | false-HOLD | scope association |
   | sh1-kakao-03 | expected HOLD | HOLD | correct HOLD | none |
   | sh1-celltrion-01 | answerable | HOLD | false-HOLD | table geometry / fact association |
   | sh1-celltrion-02 | answerable | HOLD | false-HOLD | table geometry / fact association |
   | sh1-celltrion-03 | expected HOLD | HOLD | correct HOLD | none |
   | sh1-orion-01 | answerable | HOLD | false-HOLD | table geometry / fact association |
   | sh1-orion-02 | answerable | HOLD | false-HOLD | table geometry / fact association |
   | sh1-orion-03 | expected HOLD | HOLD | correct HOLD | none |
   | sh1-kt-01 | answerable | HOLD | false-HOLD | numeric evidence extraction / line association |
   | sh1-kt-02 | answerable | HOLD | false-HOLD | table geometry / fact association |
   | sh1-kt-03 | expected HOLD | HOLD | correct HOLD | none |

   실패 계층은 고정 artifact에서 최초로 proof 연결이 누락된 경계를 뜻한다. Table geometry 내부의 어느 세부 규칙이 원인인지는 추가 실행 없이 확정하지 않았다.

   - `sh1-naver-01`: 원문 metric/value/unit token은 보존되어 있으나 지정 p2의 58개 table fact에 필수 metric/value/unit의 결합이 없다.
   - `sh1-naver-02`: 지정 p2에 두 기간 token은 있지만 필수 metric/value/unit fact가 없고 verified table 후보도 0개다. requirement entity에 불필요한 도  기준이 남는다.
   - `sh1-kakao-01`: 지정 p1의 원문 token과 Paddle table 3개는 있으나 table fact/primitive/numeric evidence가 0개다. 다른 p4 후보가 반환되었고 requirements도 비어 있다.
   - `sh1-kakao-02`: 지정 p2에 metric/period/value/unit 일치 fact 및 verified 후보 2개가 있으나 scope가 연결되지 않았다. selection에서 source_scope_unverified, entity_mismatch, comparison_missing_or_mismatch 등이 기록되었다.
   - `sh1-celltrion-01`: 지정 p2 원문에는 신규/이전 값이 있지만 21개 table fact에 해당 영업이익 metric/value/unit가 없다. 페이지에는 equal_priority_conflict 기록도 있고 25년 2분기 질문의 requirements가 비어 있다.
   - `sh1-celltrion-02`: GPM fact 하나는 있으나 필수 매출액 metric/value/unit fact가 없다. estimate version 및 scope proof가 결합되지 않았고 requirements도 비어 있다.
   - `sh1-orion-01`: 지정 p8의 metric/값/단위/주석 token은 보존되어 있으나 65개 table fact에 필수 EPS fact가 없다. verified 후보 0개이며 top-5도 p8을 포함하지 않는다.
   - `sh1-orion-02`: 지정 p8 원문은 보존되어 있으나 해당 매출액 metric/value fact가 없다. top-5에는 p8이 있지만 requirements가 비어 있어 evidence pack이 생성되지 않는다.
   - `sh1-kt-01`: 지정 p1의 원문 proof는 보존되지만 numeric evidence가 0개다. 값이 위치한 두 중복 line 모두 metric/period regex match=0, value-unit match=2, actual predicate=true다. 기존 extractor는 같은 line의 metric/period를 요구하므로 제외된다.
   - `sh1-kt-02`: 지정 p2 원문은 있으나 143개 table fact에 필수 EPS metric/value/unit 결합이 없다. 25년 예상 EPS 질문의 requirements도 비어 있다.

15. **Artifact 경로**: `evals/results/sealed-holdout-v1-first-run/predictions/*.prediction.json`, staged input/PDF 및 `*-pages.json`; 최초 ledger `run.json`, `worker.json`, `completion.json`, `artifacts.sha256.json`; 별도 `scoring.json`/`scoring.sha256.json`. 안전성 자료 및 실패 분류는 `evals/results/sealed-holdout-v1-first-audit-20261010/`에 별도 보존했다.

16. **SHA-256**:

   | Artifact | SHA-256 |
   |---|---|
   | run.json | `6e6861c1bfdfe76c8704c9c188adae8d609b40905f7941fb3ece290126f433e8` |
   | prediction_artifact_inventory | `19d19c1211a56a62d036ebee29b72a861a813301245f005a296e455f35350d16` |
   | scoring.json | `ed10709ce26ceb3cb03ee16d654353cb4145276a692be19b03e385cfc26ec85c` |
   | scoring.sha256.json | `253172b81626ab4347d242997680e76035766da9e5e7ae46f0dc50e6cf22826c` |
   | manifest | `e953979e5413db83d4355b205ddfacf6abdfbb8ceef4cfaa2e84d1a5f5527b57` |
   | configuration | `2ebceaf80a38250dad3077d19b4ce773b653b12ad3380d99fbee55fd7acf2332` |
   | policy | `0aaec2085aa0f208334a4cdae88e933620a7808613c4e67157171b408296f68a` |
   | failure-analysis.json | `5118ffdd5240fa92dc7a17e458ea81b75f72a5e02ca235edfecdf0373807ee16` |

   Prediction inventory는 모든 prediction/PDF/input/extraction/ledger 파일별 hash를 포함한다. 최초 run 및 별도 audit artifact는 읽기 전용과 macOS uchg immutable flag로 잠그고, 최종 seal receipt에 flags/inventory/hash를 검증한다. 권한 보유자가 immutable flag를 해제하는 행위까지 막는 외부 WORM 보관은 아니다.

17. **DB hash 전후**: REPEATABLE READ READ ONLY snapshot으로 5개 table count/hash 모두 동일하며 사전 baseline과도 동일하다.

   | Table | Count | Before = after SHA-256 |
   |---|---:|---|
   | documents | 10 | `90a528749fa287d8614fe5383fa6c8a37f67498e778206108d5796860565f8b4` |
   | pages | 75 | `1cf7866151671415c87cc90b8a439c48969ebdc7a95611ba289fc041179cb575` |
   | chunks | 231 | `bce2ec67ef0b99dca798891b76998fedc9cbbe969c01a749906619198033bf0e` |
   | analysis_runs | 311 | `ce0bab08903d1fafb004361a493d67ff41ae332ca93563faf92715d5b70810fd` |
   | page_extractions | 0 | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` |

18. **기존 regression**: `./scripts/check.sh` host 실행 PASS — backend 536 passed/1 skipped, frontend 7 passed, lint/build PASS. 최초 Codex sandbox 내 검사 1개는 sandbox-exec 중첩 차단으로 실패했고 host 검사에서 통과했다. Skip은 기존 google.genai SDK 미설치 항목이다. Immutable regression verifier PASS: 현대차/삼성 offline PASS, 기아 manual review, SK HOLD, Counts HOLD, 개발 12/12, POSCO 1/1, selected pack 20/20 유지, review-aware/effective false-complete 0. 새 holdout retrieval 재실행은 없다.

19. **Production 변경**: 0. Active DB write/migration/revision/production embedding/OCR 재처리/search/RRF/model config/gold/parser/threshold 변경 없음. 기존 dirty worktree를 보존했다. 새 파일은 최초 run/audit/report artifact뿐이다.

20. **다음 작업 후보**: 이 최초 결과를 유지한 상태에서 별도 version/run의 scorer status-field 및 cross-page proof 계약 정합성 검토, 공개 개발 자료를 통한 table/metric/unit/scope 및 prose line association 진단, requirement generation 지원 범위 검토. Gold가 공개된 이 15개 질문은 이후 새로운 blind holdout이라고 부르지 않는다. 향후 실험은 별도 run으로 구분하고 이번 결과를 대체하지 않는다. 이번 작업에서 구현 수정은 하지 않았다.

최종 답: 15개 모두 평가했으며 충분한 evidence는 answerable 0/10, expected HOLD 올바른 거절은 5/5, false-complete는 0이다. 제출된 source page/span proof 검증은 0/15이다. 점수 개선을 위한 parameter/gold 변경은 없고 최초 결과는 hash 및 로컬 immutable flag로 보존한다. 이번 결과는 retrieval/evidence 평가이며 전체 자연어 LLM 답변 정확도는 NOT_VERIFIED다.
