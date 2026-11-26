# Persistent E2E 문서 출처·전송 권한 조사 — 2026-10-14

**공개 출처·동일 파일 확인 VERIFIED. 현재 LG 보고서의 Gemini 전송 권한 UNCERTAIN — 전송 보류.** 이번 작업의 실제 전송은 사용자가 명시적으로 금지했으므로 NOT_ALLOWED이며 Gemini 호출0회다. 공개 PDF 확인은 공식 서버의 파일을 GET으로 읽은 것이고 로컬 문서/원문/질문을 업로드하지 않았다. 검색에도 로컬 원문/제목/질문을 보내지 않았다.

## 1. 실제 문서·발행기관·원본 출처

| 항목 | 확인 결과 |
|---|---|
| 보고서 | LG — 제도로 뒷받침될 매력 |
| 분류 | 상장기업 LG(003550)에 관한 증권사 Equity Research, broker_report |
| 발행기관·날짜 | 미래에셋증권 리서치센터, 2026-08-14 |
| 작성자 | 류제현(첫 페이지에 실명·업무 이메일 표시) |
| DB document_id | 5f4001ad-403f-452e-926a-b0ddeb4b60bb |
| 원본 파일명 | 20260814_LG (003550_매수).pdf |
| 원본 출처 | https://securities.miraeasset.com/bbs/download/2146712.pdf?attachmentId=2146712 |

PDF 첫 페이지와9페이지를 로컬에서 직접 렌더링·검토했다. 파일명/DB issuer만으로 판정하지 않았다. 원본 `holdout-v1` 파일의 macOS `com.apple.metadata:kMDItemWhereFroms`가 위 공식 URL을 두 번 기록한다. 보존 raw 복사본에는 WhereFroms가 없어 개발 원본으로 출처를 추적했다.

공식 URL은 cookie·로그인·API key 없이 HTTP200/application/pdf로2,383,959bytes를 반환했다. 공개 서버 bytes의 SHA256이 로컬 개발 원본/보존본/DB file_hash와 모두 동일하다. 웹 읽기 도구에서는 이 URL을 열지 못했으나, 별도 Python urllib anonymous GET 및 hash 비교는 성공했다. 로그인 우회는 하지 않았다.

따라서 **공개된 증권사 기업분석 보고서**라는 출처·동일성은 VERIFIED다. LG 자체 발행 IR 자료나 DART 공시, 개인의 비공개 포트폴리오/금융거래 자료로 분류하지 않는다. 다만 이 검증은 전송/재배포 라이선스를 부여하지 않는다.

## 2. SHA256 및 현재 저장 위치

```text
3489541bb393c16772ba3ed5d31c3f34a035ba36a472eabc884fa6ad60209808
```

- 실제 persistent E2E DATA_DIR 보존 PDF: `.e2e-persistent/preserved/data/raw/5f4001ad-403f-452e-926a-b0ddeb4b60bb.pdf`.
- 원래 개발 PDF: `holdout-v1/20260814_LG (003550_매수).pdf`.

두 파일의 현 hash, 공식 서버의 현 hash, documents.file_hash가 동일하다. PDF physical pages9. `holdout-v1`이라는 디렉터리 이름만으로 sealed 평가 문서라고 판단하지 않았다. `evals/audit-documents.json`은 이 파일을 prior_upload=true/blind_holdout=false로 기록한다. 이번 작업에서 sealed 문서/gold를 평가하거나 대체하지 않았다.

## 3. 복원된9페이지·583청크의 소속

고정 E2E port55433/database·user `stock_brief_e2e_restore`를 guard 및 READ ONLY transaction으로 확인했다. documents1건, pages9건, page_extractions9건, chunks583/embedding583 전부 위 LG document_id 소속이다.

| PDF page | chunks / embeddings |
|---|---:|
|1|60 / 60|
|2|39 / 39|
|3|4 / 4|
|4|37 / 37|
|5|4 / 4|
|6|2 / 2|
|7|432 / 432|
|8|0 / 0|
|9|5 / 5|
|합계|583 / 583|

페이지8은 pages/extraction에 존재하지만 chunk가 없다. 모든 페이지에 청크가 있다고 주장하지 않는다. 이유를 이번 조사에서 추측하지 않았다. 583개는 PDF 수나 문서 수가 아니라 이9페이지 문서의 저장 청크/벡터 수다.

기존 provider 조사 closeout snapshot과 pages/extractions/chunk UUID·source/provenance/vector hashes가 완전히 동일하고 vector(1024) finite/nonzero/missing0이다.

## 4. Gemini에 전달될 데이터 범위

코드 `analysis_service._prompt` 및 `GeminiGenerationProvider.generate`를 읽기 전용으로 확인했다. 실제 generate 호출은 하지 않았다.

전송 대상은 **텍스트 prompt**다: 사용자의 question, 기업명·종목코드·문서 유형·발행기관·발행일, 검색·로컬 검증된 후보의 quote/페이지/근거 UUID/section title, facts/table_evidence의 row_label/metric/period/value/unit/scope/status/comparison/direction 등 허용 필드, 분석 지시문·system instruction·JSON output schema. Gemini 모델 ID/temperature/요청 설정도 API에 전달된다.

PDF binary·페이지 이미지·583개 embedding·전체 provenance/geometry proof graph·DB 접속값은 이 생성 요청에 포함되지 않는다. 파일명/document_id/run_id/file_hash도 `_prompt`의 문서 메타데이터 필드에는 없다. 다만 파일명 등 문자열이 question/quote에 포함된다면 별도로 자동 제거하지 않는다.

**최종 citation2개만 전송하는 구조가 아니다.** 기존 accepted run `032a7521-91c6-4cdc-891d-f6b95023ba6e`의 질문은 초보자 관점의 호재/악재 각 최대3개 요약 요청이었다. 저장 trace의 후보는3개, quote 총608문자, pages3/3/1이며 최종 화면 citation은2개다. 동일 evidence를 Gemini에 사용하면 선택 이전 후보와 관련 사실이 prompt에 들어갈 수 있다. 기존 Ollama prompt는2574문자로 기록됐지만 Gemini wire bytes/토큰수와 같다고 보장하지 않는다.

현재 코드에는 전용 개인정보 익명화/DLP 필터가 없다. factual evidence 검증은 개인정보 전송 권한 검증을 대신하지 않는다. 기존3개 후보에는 이메일/@·주민등록·계좌번호 표식이 없었으나 다른 질문의 후보까지 보장하지 않는다.

## 5. 권한·라이선스·개인정보 판정

원본9페이지에는 조사분석자료 지적재산권이 미래에셋증권에 있고 허락 없이 무단 복제·배포할 수 없다는 고지가 있다. 이번 조사 범위에서 외부 AI processing/제3자 제공을 허락한 라이선스·권리자 승인 증빙은 발견하지 못했다. 공개 다운로드, PDF 보유, UI의 전송 동의만으로 권리자 허가를 추론하지 않는다. 인용/공정이용 등 특정 이용이 법적 예외에 해당하는지까지 판정한 것이 아니므로 일률적 불법 단정도 하지 않는다.

[Google API 약관](https://developers.google.com/terms)의 Submission of Content는 제출 전에 필요한 권리를 갖추도록 요구한다. [Gemini 추가 약관](https://ai.google.dev/gemini-api/terms)은 무료 서비스의 입력/출력 활용 및 사람 검토 가능성을 설명하고 개인·민감·기밀정보 제출을 금지한다. 유료 서비스는 prompt/응답을 제품 개선에 사용하지 않는다고 설명하지만 보안 목적 제한 기간 로그 및 여러 국가의 저장 가능성이 남는다. 현재 API key 프로젝트의 유료/무료·billing·보존/지역 설정은 확인하지 않았다. 유료라는 이유만으로 문서 권리 문제가 해결되지 않는다.

PDF 첫 페이지의 분석가 실명·개인 식별 가능한 업무 이메일은 개인정보 검토 대상이다.9개 기존 final_text를 검사했으며 이메일은 page1에서 확인됐다. 개인 고객 계좌/주민번호/기밀 표식은 해당 텍스트 검색에서 발견되지 않았지만 완전한 개인정보 부재 증명은 아니다. 공개 업무 연락처라고 해서 무료 Gemini에 그대로 제출해도 된다고 판정하지 않는다. 실제 테스트 packet에서는 인명/이메일/연락처를 제외하고 질문에도 개인정보를 넣지 않는 범위를 검토해야 한다.

| 대상/행위 | 분류 | 근거 |
|---|---|---|
| 현재 LG PDF의 공개 출처·동일성 |VERIFIED|공식 anonymous GET 및 SHA256 일치|
| 현재 LG PDF/evidence를 Gemini에 전달할 권한 |UNCERTAIN|명시적 복제·배포 제한, AI/외부 처리 허가 및 적용 가능한 예외 미확인. 전송 보류|
| 이번 작업의 실제 외부 문서 전송 |NOT_ALLOWED|사용자가 명시적으로 금지. 실제0회|
| 개인 연락처가 들어간 무료 Gemini packet |NOT_ALLOWED|Google 무료서비스 개인정보 제출 제한; 현재 서비스의 자동 제거 보장 없음|
| 아래 추천자료의 지정된 공개 본문 텍스트 이용조건 |VERIFIED(출처표시 조건)|공식 게시물의 공공누리1유형 명시. 미래 API 실행 승인은 별개|

판정 기준: VERIFIED는 해당 범위의 출처/이용조건이 확인된 경우, UNCERTAIN은 권리·조건 미확인으로 보류하는 경우, NOT_ALLOWED는 명시적 사용자/서비스 제한에 해당하는 경우다. 데이터 권리 확인과 이번 요청의 실제 실행 승인은 서로 다르다.

## 6. 실제 Gemini 테스트의 안전한 대체 후보

**추천: 국가데이터처 「2025년12월 및 연간 산업활동동향」(2026-01-30)의 브리핑 본문 텍스트.** [공식 게시물](https://www.korea.kr/briefing/policyBriefingView.do?newsId=156742173)은 텍스트에 한해 공공누리 제1유형(출처표시)을 명시한다. [공공누리 조건](https://www.kogl.or.kr/info/license.do)은 출처를 표시한 상업/비상업 이용·변형을 허용하고 원래 취지를 왜곡하지 않도록 한다. 사진/이미지/제3자 자료는 이 확인 범위에서 제외한다.

게시물의 공식 `속기자료.pdf` GET도 확인했다:

- URL: https://www.korea.kr/common/download.do?fileId=198345029
-6페이지,91,383bytes, SHA256 `f33784d302b0b08c208247a6b38ff18499a541d9decb1a29fff9034a0324917b`.
- 본문이 공식 브리핑 주제·날짜와 일치하며 이메일은 추출 텍스트에서 발견되지 않았다. 첫 부분에 발표자 이름은 있으므로 실제 packet에서는 제외한다.
- 이용조건 VERIFIED는 공식 게시물의 **본문 텍스트** 범위다. PDF 전체/표지/서체·이미지까지 무제한 라이선스로 확대하지 않는다. 동일 본문에서 필요한 통계 문장만 선택하고 기관·제목·날짜·원문 URL·공공누리1유형 출처를 prompt와 표시 결과에 보존하는 작은 테스트가 적절하다. 아직 다운로드 파일을 DB에 적재/embedding하거나 Gemini로 전송하지 않았다.

이 자료는 기업 증권사 보고서/DART filing이 아니므로 현 `broker_report/dart_filing` enum에 임의로 넣지 않는다. **provider 전송·schema·근거보존 smoke test용**으로 추천하며, 현재 기업 RAG 전체 E2E와 동등하다고 주장하지 않는다. 기업별 실제 서비스 비교에는 외부 AI 처리까지 재사용 권한이 확인된 기업 IR/공시 자료 또는 현재 미래에셋 보고서에 대한 권리자 허락이 별도로 필요하다. DART 공개라는 이유만으로 저작권을 자동 VERIFIED 처리하지 않는다.

## 7. 보호 및 조사 기록

Production DB 접근/DB write/migration/분석 run 추가/재임베딩/OCR 변경/봉인 재채점/시스템 종료0회. Sealed114파일 hash/immutable flags unchanged. 기존 서비스 코드·전송 정책·.env를 변경하지 않았다. 조사 보고서와 audit artifact만 새로 작성했다.

기록: `.e2e-persistent/service-quality/document-permission-20261014/document-audit.json`, `sealed-integrity.json`, `check.log`. PDF page 렌더는 private/tmp에만 저장했다.

최종 검증: `./scripts/check.sh` PASS — backend700 passed(frontend17 passed), lint/build PASS, 전체 `All checks passed.`. Backend22warnings는 검사 실패가 아니다. `git diff --check` PASS. 이번 조사는 provider 호출이나 새로운 성능 측정을 하지 않았다.
