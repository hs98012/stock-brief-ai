# 원문 metric annotation과 보수적 query 동치성

1. **변경 파일**

   새 `backend/app/metric_annotations.py`, `backend/tests/test_metric_annotations.py`, `scripts/hash_active_tables.py`; query integration은 `backend/app/evidence_requirements.py`, `primitive_graph.py`, `table_evidence.py`, `evidence_bundle.py`에 한정했다. 계약 문서 `api-contract.md`, `acceptance.md`, `qa-rules.md`를 함께 갱신했다. 이 보고서, `evals/metric-annotation-reviewed.json`, raw replay·검사 로그·diff를 저장한다. 기존 사용자 변경과 기존 shared-context/ownership 테스트는 보존했다.

2. **기존 query matching failure path**

   `requirements_for → table_requirements`는 METRIC/PERIOD regex로 literal requirement를 생성한다. source primitive는 metric/row_label/metric_span에 원문 label을 저장한다. `metric_form`은 whitespace/case, 알려진 metric alias, rate/growth modifier를 처리하며 annotation을 제거하지 않는다. query `영업이익률`은 normalized=`영업이익`, modifier=`ratio`; raw source `영업이익률3)`은 normalized=`영업이익률3)`, modifier=`amount`다. 따라서 `comparison_candidates → fact_requirement_match`의 normalized+modifier exact 검사에서 실패했다. 일반 legacy candidate gate의 `fact_matches_query`에는 raw row/metric substring 검사가 있지만 이것으로 annotated 동치를 승인하지 않는다. 새 annotated 경로는 requirement의 exact canonical 검사로 연결했다. fuzzy/similarity 동치는 추가하지 않았다.

3. **annotation 데이터 모델**

   query-time `metric_identity`에 raw_label/raw_span, canonical_label, annotation/marker_span, annotation_type, proof_level, definition_spans, proof_checks, scope_metrics, collision_spans, rejection_reason을 보존한다. raw metric/row_label/source spans, 저장 primitive, geometry, shared context와 ownership은 덮어쓰지 않는다. 별도 superscript는 기존 base metric span과 별개 marker source span으로 보존한다. DB schema/migration은 변경하지 않는다.

4. **annotation proof 규칙**

   marker syntax는 후보만 탐지한다. 원문 offset/quote/bbox와 unsafe span을 재검증하고 metric cell 소속이 유일해야 한다. definition은 같은 source/page의 전체 원문 line으로 추적하며 metric table 밖의 인접 footer에 유일하게 귀속되어야 한다. 명시적 `주:`/`Notes:` 같은 주석 anchor, 또는 raised definition marker와 반복 table convention/별도 superscript 증거를 추가로 요구한다. 실제 geometry/source 근거 없이 숫자나 괄호를 제거하지 않는다. 후보 수준은 verified_annotation, probable_annotation, unverified_suffix로 구분하며 bare collision 후보는 not_annotated로 기록한다. geometry threshold 함수와 unit validator는 그대로다.

5. **canonical metric 생성 규칙**

   verified annotation일 때만 실제 raw source prefix를 canonical label로 사용한다. 다른 suffix는 raw label 그대로 유지하며 potential base는 collision 감사용 후보로만 남긴다. query literal metric과 canonical label은 whitespace/case를 제외하고 exact match해야 한다. query의 surface/normalized/modifier 필드도 일관되어야 한다. 기존 unique row/downstream chain 및 source/graph/pack 재검증은 별도로 요구한다. footnote definition과 marker span은 evidence pack의 source span/chunk coverage에 포함한다.

6. **collision 검증 규칙**

   같은 표에서 period header 앞의 모든 label column을 검사한다. 승인된 value chain만 보지 않고 모든 raw row 후보를 포함한다. 두 verified annotated row, annotated+bare row, 다른 label column의 row, 탈락한 sibling, 아직 검증되지 않은 suffix의 potential base가 경쟁하면 canonical_metric_collision으로 HOLD한다. 같은 shared context에만 범위를 제한해 다른 scope의 경쟁 row를 숨기지 않는다.

7. **추가 positive/negative tests**

   annotation 39 cases, shared/ownership/row/column/unit/graph/requirement와 함께 targeted 156 passed. 실제 `3)` footnote를 가진 두 ratio metric의 exact canonical match, 독립 superscript span, 같은 verified marker의 서로 다른 base 및 isolated comparison pack을 승인한다. 의미 숫자 10종을 보존하며 proof 없음/다른 numbered reference, canonical collision(annotated pair/bare/rejected sibling/다른 label column), partial/substring query, raw/marker/canonical/query/definition 변조·삭제, empty base, duplicate/remote/unsafe definition, broken downstream chain을 거절한다. semantic annotation 계층을 비활성화한 RED 검사에서 두 positive 동치 테스트가 실패했고, 다른 label column collision 검사도 구현 전 실패했다. 기존 shared-context/ownership/row/column/unit 테스트 파일은 변경하지 않았다.

8. **현대차 annotation 원문 proof**

   native source metric은 `영업이익률3)`이며 annotation marker는 원문 char offset으로 분리한 `3)`다. 같은 표 아래 native line `n:51:0`의 definition marker bbox는 `[592.440673828125,462.9814758300781,595.8115844726562,467.9358215332031]`이다. 정의는 원문 단어 순서로 다음과 같다.

   > 3) 2023년 기말, Hyundai Motor Manufacturing Rus LLC (HMMR)이 처분 자산집단 및 중단영업으로 분류됨에 따라, 비교 공시 대상 기간의 금액 재작성

   definition marker가 body보다 작고 올라간 형태이며 동일 표에서 `매출액3)`, `영업이익3)`, `EBITDA3)`, `영업이익률3)`, `순이익률3)` convention이 반복된다. source span과 실제 bbox·table footer 소속·unique definition 검증으로 verified_annotation을 승인한다. label 내부 marker의 별도 glyph bbox를 추정하지 않고 기존 word bbox를 유지한다. 정확한 definition/marker/source/collision span과 checks는 reviewed JSON에 저장한다.

9. **현대차 query equivalence 판정**

   canonical label=`영업이익률`, query literal=`영업이익률`로 exact canonical text는 일치한다. 그러나 같은 표에 raw `영업이익률`인 별도 기준 row도 존재한다. 연결 row label bbox는 `[688.9717407226562,398.1713562011719,727.0438232421875,408.3382568359375]`; competing bare row label bbox는 `[688.9779052734375,429.8014831542969,723.218017578125,439.5134582519531]`다. 두 raw row가 같은 canonical로 충돌한다. 질문에는 “연결 기준”이 있지만 현재 requirement에는 이를 유일한 source scope/row로 연결하는 검증된 selector가 없다. 따라서 annotation proof 승인과 query equivalence 최종 승인을 분리하고 canonical_metric_collision으로 HOLD한다.

10. **현대차 challenge 전/후**

    전: coverage_complete=false, raw annotation 미모델링으로 metric_mismatch. 후: annotation verified, canonical text exact, canonical_metric_collision으로 coverage_complete=false. 앞서 검증한 공유 context, `%`, `2022→6.9`, `2023→9.3` 및 sibling chain 격리는 그대로 유지한다. PASS를 강제하지 않으며 selected pack은 기존 baseline과 exact equality로 비교한다.

11. **개발/POSCO/삼성/SK 회귀**

    immutable observation과 frozen hybrid rank를 재사용한다. 개발 combined comparison 12/12(후보 10/10+고정 control 2/2), POSCO 1/1, 삼성 false-complete 0 및 SK HOLD를 검사한다. 신용보증기금·현대차·기아·SK를 포함한 fixed regression/challenge selected pack을 baseline과 비교하고 기아의 기존 manual strict review를 유지한다. 기아 automatic strict=false는 수동 판정을 새 자동 PASS로 바꾸지 않는다. 최종 replay에서 fixed regression 4개와 challenge 5개의 selected pack이 모두 baseline과 exact JSON equality다. 개발 12/12, POSCO 1/1, 삼성 coverage=false/false-complete 0, SK HOLD, 기아 manual strict review 유지. challenge strict 1/5, false-complete 0. 상세 결과는 reviewed JSON에 기록했다.

12. **전체 테스트 결과**

    `./scripts/check.sh`: backend 418 passed/1 skipped, frontend 7 passed, lint/build PASS. skip은 optional google.genai dependency 미설치다. targeted annotation/shared-context/ownership/row/column/unit/graph/requirement 156 passed. 재개 전 임시 로그가 소실되어 동일 최종 코드로 2026-10-08에 재검사하고 결과를 `evals/results/paddle/metric-annotation-*20261008*`에 직접 저장했다. replay는 새 search/OCR/embedding/LLM 호출 없이 frozen ranks/관측값을 사용한다. active control 점수는 frozen baseline 재검증이며 live search 검증은 아니다.

13. **hardcoding/diff**

    회사명, 대상 footnote-bearing metric label, 알려진 bbox, challenge ID, expected answer shortcut을 production 코드에서 검사한다. 기존 geometry/shared-context/unit/search/RRF/OCR/embedding/generation 코드의 source hash는 shared-context baseline과 일치해야 한다. unannotated pack의 기존 provenance 동작을 보존하여 annotation이 없는 selected pack을 바꾸지 않는다. `git diff --check` 및 이번 변경의 added-line whitespace 검사를 수행하고 결과/diff를 저장한다.

14. **DB/hash 불변**

    migration/reprocessing/OCR/embedding/LLM/active revision 변경 및 DB mutation은 실행하지 않았다. 재개 전 READ ONLY snapshot끼리 해시 일치를 확인했으나 임시 원본이 세션 사이에 소실되었다. 재개 후 PostgreSQL 연결은 refused이고 Docker daemon도 중지되어 최종 live hash는 확인할 수 없습니다. `scripts/hash_active_tables.py`는 같은 canonical hash 형식으로 REPEATABLE READ READ ONLY만 실행하며 기존 출력 파일을 덮어쓰지 않는다. DB가 준비되면 전/후 hash를 저장하고 기존 persisted shared-context baseline과 비교한다. 최종 live verification 없이 DB 불변을 확인했다고 표시하지 않는다.

15. **남은 HOLD 원인**

    현대차의 blocker는 annotation 미검증에서 canonical metric collision으로 바뀌었다. 동일 canonical metric의 연결/별도 scope를 query 요구와 유일하게 연결했다고 증명할 수 없다. cross-page definition, unsupported/fragmented marker 구조, remote/duplicate source 등도 현재 proof 계약에서 승인이 불가하면 HOLD다. live DB hash의 최종 확인은 현재 환경에서 미완료다.

16. **다음 작업 후보**

    원문 shared-context membership과 질문의 scope 문구를 근거로 연결하는 일반 query scope selector. 동일 canonical의 다른 scope, scope 미지정/중복/손상된 source를 negative tests로 포함해야 한다. annotation syntax 확장은 실제 source 구조/definition을 확보한 후 별도로 검증한다. collision을 무시하거나 특정 회사/주석/metric에 예외를 두지 않는다.

## 명시적 답변

| 질문 | 답변 |
|---|---|
| `3)`는 실제 footnote/annotation이라고 원문으로 증명됐는가? | 예. unique footer definition, raised definition marker 및 반복 convention 검증 |
| annotation 제거는 일반 규칙에 의해 수행됐는가? | 예. source proof를 만족한 marker만 canonical prefix에 사용 |
| raw label은 그대로 보존되는가? | 예. metric/row_label/source spans를 덮어쓰지 않음 |
| canonical label은 `영업이익률`인가? | 예 |
| query와 canonical label이 exact match하는가? | 예. canonical text 검사 일치 |
| canonical collision은 없는가? | 아니오. 같은 표의 연결/별도 row가 충돌 |
| 따라서 coverage_complete=true가 증거로 정당화되는가? | 아니오. HOLD/false 유지 |
