# Sealed holdout v1 — 2026-10-10

자료 구축·사전 평가 기준 정의·hash 봉인 작업이다. Holdout 성능 평가는
**NOT_RUN**이며 production 변경은 **0**이다. 원문은 공식 증권사 서버에서
내려받아 Git-ignored `evals/results/sealed-holdout-v1/`에 보존했다. Gold와
source review 자료는 production 입력으로 사용하지 않는다.

1. **문서 5개, 전체 29페이지**:

   | 기업 | 보고서 발행일 | 발행사 | 전체 페이지 |
   |---|---|---|---|
   | NAVER | 2026-10-02 | 하나증권 | 5 |
   | 카카오 | 2025-01-14 | 상상인증권 | 5 |
   | 셀트리온 | 2025-07-14 | SK증권 | 4 |
   | 오리온 | 2025-03-11 | 유안타증권 | 10 |
   | KT | 2025-05-12 | SK증권 | 5 |

   Source URL·원본 파일명·버전·stock code·PDF SHA-256·UUID는 sealed
   `documents.json`에 기록했다. 발행일은 PDF 표지와 대조했으며 다운로드
   URL에 포함된 날짜로 대신하지 않았다. 각 보고서는 일부 페이지를 잘라
   재사용한 파일이 아닌 전체 원본이다.

2. **질문 15개**: 각 문서 3개. `questions.json`은 ID/document ID/질문 원문만
   포함한다. `gold.json`은 예상 판정·정답·metric/period/scope/unit·source
   page/bbox·proof·review status를 별도로 기록한다. 답변 가능 10문항에는
   필수 factual unit 15개가 있다. Unresolved=0. Gold 원문 답은 이 보고서나
   production test fixture로 복사하지 않는다.

3. **중복 조사**: 신규 자료를 확보하기 전에 existing development fixture,
   challenge, evaluation gold/results(ignored artifacts 포함), regression/test
   JSON, docs JSON을 조사했다. JSON 253개, 기존 로컬 PDF 8개, 참조 PDF hash
   12개, document UUID 16개를 inventory에 보존했다. 알려진 기업은 삼성전자,
   현대차, 기아, SK하이닉스, LG, DB손해보험, POSCO홀딩스, 신용보증기금이며
   counts 교통사고 문서의 filename/hash도 포함된다. 후보 이름의 기존
   tests/fixtures/docs 텍스트 검색도 수행했다. 신규 5개는 SHA-256/UUID/
   company/filename 중복이 모두 0이다. 다른 버전의 같은 기업을 선택하지
   않았고 기존 문서의 다른 페이지도 쓰지 않았다. 연결 복구 후 **live active
   documents 10개와의 hash/UUID/company/stock code 중복도 0**이었다.
   전 세계/미기록 자료까지 독립성을 주장하지 않는다.

4. **유형 분포**: 일반 scalar 조회 2, 기간 비교 2, 신규/이전 추정치 비교 1,
   혼합 단위 2, 주석 metric 1, 명시 scope 조회 1, 주당지표 조회 1,
   negative 5. 주석 metric은 원문 주석을 함께 확인했고 연결·별도는 원문
   명시 귀속을 보존한다. Source에 scope가 없는 특정 표의 조회는 그 미표기
   상태를 gold에 기록해 임의 연결/별도 추론을 방지한다.

5. **Positive 10 / negative 5**: metric 미지정, 기간 미지정, scope 미지정,
   문서 내부 상충 수치, 필요한 실제 확정치 부재를 각각 1개 포함한다.
   문서 변조 synthetic negative=0, 손상된 질문=0. 세 미지정 질의는 정상적인
   표현으로 직접 작성한 underspecified 질의이며 실제 사용자 로그라는 뜻이
   아니다. 모든 negative의 origin을 gold에 별도로 기록했다.

6. **Gold 작성 근거**: production parser/search/model 결과를 사용하지 않고
   원본 PDF를 직접 읽었다. 관련 표/본문/주석 페이지는 전체 크기로 시각
   대조했다. 29페이지를 모두 렌더하고 문서 overview도 확인했다.
   PyMuPDF native text/bbox는 독립적인 gold locator일 뿐 production의
   final_text offset을 뜻하지 않는다. 98개 proof component의 bbox→원문
   text roundtrip과 15개 value proof를 확인했다. Gold status=AUTHOR_VERIFIED,
   별도 사람의 second review=NOT_PERFORMED. Author review를 시스템 응답에
   대한 manual strict 승인으로 사용하지 않는다.

7. **Page/span**: 모든 positive factual unit은 원본 physical page와 unrotated
   PDF point bbox를 갖는다. Source 전체를 확인해야 하는 absence negative는
   전체 10페이지 review 범위와 각 native page text hash를 갖는다. 존재하지
   않는 수치에 가짜 quote/bbox를 생성하지 않았다. Metric/기간/scope 후보와
   상충 수치는 negative의 원문 proof로 보존했다.

8. **사전 기준/분모**: 봉인된 `criteria.json`이 최종 규칙이다.

   | 지표 | 고정 분모 또는 정의 |
   |---|---|
   | Coverage completeness | 답변 가능 10문항의 모든 필수 fact proof 확보 |
   | Exact factual correctness | 필수 factual unit 15개, 누락·오답은 실패 |
   | Strict evidence validity | 답변 가능 10문항; 값·원문·페이지·단위·scope·주석 모두 검증 |
   | False-complete count | 전체 15문항에서 complete/PASS 주장과 gold/proof 불일치 수 |
   | Source page accuracy | 15개 fact의 지정 문서/physical page 정확성 |
   | Scope/unit correctness | 15개 fact의 scope 및 원문 단위 귀속 정확성 |
   | HOLD precision | 올바른 HOLD / 전체 predicted HOLD; 분모 0이면 null |
   | Retrieval evidence recall@5 | 15개 필수 fact proof의 top-5 확보; page recall과 구분 |

   HOLD recall 분모=5, 답변 가능한 10개에서 false HOLD 수를 별도 보고한다.
   Automatic strict/수동 승인/미결 REVIEW를 각각 집계한다. REVIEW는 자동
   PASS로 바꾸지 않는다. ERROR는 semantic HOLD로 세지 않고 고정 분모에서
   숨기지 않는다. Whitespace만 typographic normalization을 허용하며
   반올림·스케일 변환·기간 qualifier/추정치 버전 혼동은 승인하지 않는다.
   최초 retrieval/evidence 단계에서 생성 답변 정확성·answer HOLD 지표는
   **NOT_VERIFIED**로 남기고 evidence 판정과 구분한다.

9. **독립 작성**: 질문과 gold는 새 source 확인에 따라 작성했다. 기존
   시스템 답변/검색 결과를 정답 근거로 사용하지 않았다. Gold를 production
   규칙으로 구현하거나 parser가 지원하는 항목만 골라 성능 분모를 바꾸지 않았다.

10. **Leakage 방지**: 원문·질문·gold·review/config/criteria는 sealed bundle에
    분리 저장한다. Blind collector는 `questions.json`, `documents.json`,
    config만 의미적으로 읽는다. Verifier는 gold bytes의 hash만 계산한다.
    Collector는 gold/원문 review bbox/author annotation을 모델 입력으로
    읽거나 주입하지 않는다. 기존 raw ingestion 경로/production test data로
    새 자료를 이동하지 않았다. Holdout retrieval/embedding/production PDF
    parser/generator 호출은 0이다. Gold 공개·평가 결과 확인 후 수정 금지.

11. **봉인**: 공개 `evals/sealed-holdout-v1-manifest.json` 및 `.sha256`에
    document hashes, gold/questions/criteria/config hash, 전체 bundle 파일
    inventory, timestamp, tool hash를 기록한다. Source/review/code snapshot은
    로컬 ignored bundle 안에 있으며 archive를 다른 호스트로 복사할 때도
    manifest 전체 hash 검증이 필요하다. SHA-256은 변경 탐지 수단이며 암호화나
    외부 WORM 보관을 주장하지 않는다. 봉인 파일은 읽기 전용으로 설정한다.

12. **기준 code commit**: `28061c63186020b3302b5918fda49f34ff42ab63`.
    작업 시작 당시 dirty worktree였으므로 commit만으로 기준을 정의하지
    않았다. Backend/frontend source·dependency lock·안전한 예시 config의
    56개 파일 hash, code tar archive, 기존 tracked diff와 status를 보존했다.
    실제 `.env`와 비밀값은 포함하지 않았다. Seal verifier는 현재 source가
    그 snapshot과 다르면 평가 전에 중단한다.

13. **Production 변경 0**: 기존 code/config SHA-256 불변을 확인한다.
    신규 evaluation verifier/미실행 collector 및 seal integrity tests만
    추가했다. Search parameter·model·geometry·OCR threshold·API/data model
    변경은 없다. Transport localhost 주소는 향후 isolated host 실행용이며
    production 설정을 수정하지 않는다. 기존 challenge 결과는 재평가하거나
    판정을 바꾸지 않았다.

14. **DB VERIFIED**: 처음 localhost:5432는 Connection refused였다. 권한을
    확보한 read-only Docker 점검에서 daemon은 실행 중이며 프로젝트
    PostgreSQL 컨테이너만 정상 종료(ExitCode=0)된 것을 확인했다. 기존
    초기화된 볼륨을 유지한 채 해당 컨테이너만 재시작해 연결을 복구했다.
    이후 READ ONLY REPEATABLE READ의 before/after 5개 table hash가 서로
    같고 `composite-unit-active-after-20261009.json`과도 모두 같았다.
    Counts는 documents=10, pages=75, chunks=231, analysis_runs=311,
    page_extractions=0이다. 초기화/migration/복원/revision 변경은 없었다.
    서비스 상태 변경은 기존 PostgreSQL 재시작 1건이다. Offline 자료
    구축/봉인 자체는 DB 의존 없이 수행했다.

15. **미확보/한계**: 원문 자체에서 복수 unit의 귀속이 불명확한 적합한
    negative는 이번 5개에서 확보하지 못했다. 명확한 혼합 단위 표를
    임의로 ambiguous로 만들지 않았다. 별도 사람의 second gold review는
    미수행이다. Ollama bge-m3 digest와 1024차원 모델 metadata, 기존 OCR
    worker image ID/source hash는 확보했다. OCR worker는 중지돼 health 및
    실제 model weight fingerprint는 미확인이다. 생성까지 포함한
    end-to-end blind adapter는 별도 작업이다.

16. **다음 단계 명령**(이번에는 평가 실행 금지):

    봉인/기준 코드만 검증:

    ```bash
    .venv/bin/python scripts/verify_sealed_holdout.py --manifest evals/sealed-holdout-v1-manifest.json
    ```

    이후 명시적으로 승인된 최초 isolated retrieval/evidence 실행:

    ```bash
    .venv/bin/python scripts/collect_sealed_holdout.py --manifest evals/sealed-holdout-v1-manifest.json --output-dir evals/results/sealed-holdout-v1-first-run --execute-first-run
    ```

    Collector는 모델 서비스가 준비돼야 실행된다. 지정 output은 최초 ledger로
    예약하며 기존 디렉터리가 있으면 덮어쓰지 않는다. 실패 기록을 삭제해
    최초 실행인 것처럼 다시 실행하지 않는다. 출력 hash를 고정한 뒤 별도
    scorer/reviewer가 frozen gold/criteria와 비교한다. 이 명령은 생성 답변
    벤치마크를 실행하거나 8개 지표가 이미 측정됐다고 주장하지 않는다.

17. **준비 여부**: 자료와 평가 기준은 최초 query 전에 확정·봉인됐으며
    최초 retrieval/evidence run용 collector도 준비했다. Collector의 실제
    실행/성능은 검증하지 않았다. OCR worker 준비는 미완료이고 전체 생성
    end-to-end 평가는 아직 준비 완료가 아니다. 이번 결과는 독립
    평가 자료 구축의 완료이지 holdout 성능이나 전체 운영 준비 완료가 아니다.

최종 답: 저장소에서 확인 가능한 기존 개발·평가 자료와 독립적인 문서 5개다.
정답은 실제 원문으로 작성했고 PASS와 정당한 HOLD를 모두 평가할 수 있다.
기준은 최초 실행 전에 고정했으며 hash/manifest로 봉인했다. Production
코드와 parameter를 바꾸지 않았다. **자료는 준비됐고 최초 retrieval/evidence
실행은 service preflight와 후속 승인 이후 가능하다. 전체 생성 평가는 별도
adapter가 필요하다.** 검증 로그/정확한 hash·실행 상태는 manifest와
`evals/sealed-holdout-v1-reviewed.json`을 따른다.
