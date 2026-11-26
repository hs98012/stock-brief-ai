from uuid import uuid4

from app.analysis_retrieval import (collect_analysis_evidence, is_boilerplate,
    GENERAL_SUMMARY_POSITIVE_PATTERN, NEGATIVE_QUERY, POSITIVE_QUERY,
    STRONG_NEGATIVE_PATTERN, STRONG_POSITIVE_PATTERN,
    is_contextless_numeric_fragment, question_focus_terms, readable_excerpt)
from app.search import SearchExecution
from tests.test_hybrid_search import seed_chunk


def test_incomplete_compound_pack_is_not_sent_to_generation(monkeypatch) -> None:
    monkeypatch.setattr('app.analysis_retrieval.hybrid_search',
        lambda *args, **kwargs: SearchExecution([], True, None,
            evidence_pack=[], requirements=[{'id': 'narrative_1', 'kind': 'narrative'},
                                             {'id': 'structured_1', 'kind': 'table'}],
            coverage_complete=False))
    diagnostics = {}
    assert collect_analysis_evidence(object(), uuid4(),
        '소재 개선 이유와 표의 2Q26F 영업이익을 함께 알려줘', 5, object(), diagnostics) == []
    assert diagnostics['coverage_complete'] is False


def test_general_investment_grade_and_disclaimer_are_excluded() -> None:
    text = "[종목 투자등급] Buy 매수, Hold 보유, Sell 매도 의견의 절대수익률 산정 방식 안내"
    assert is_boilerplate(text)
    assert is_boilerplate("[Compliance Notice] 조사분석자료의 투자등급 부여 비중")


def test_contextless_percent_table_is_excluded_but_interpretable_text_is_kept() -> None:
    assert is_contextless_numeric_fragment("DRAM 20% 37% 31% 33% NAND 9% 23% 13% 5% SDC 6% 13% 19%")
    assert not is_contextless_numeric_fragment("영업이익은 전년 대비 20% 증가할 전망이며 수익성 개선이 예상된다. 20% 18%")


def test_mixed_chunk_uses_question_perspective(monkeypatch) -> None:
    document_id = uuid4(); chunk_id = uuid4()
    row = {"rank": 1, "rrf_score": 0.03, "bm25_rank": 1, "vector_rank": 1,
        "chunk_id": chunk_id, "document_id": document_id, "document_name": "report.pdf",
        "company_name": "삼성전자", "ticker": "005930", "publisher": "기관", "published_at": None,
        "document_type": "broker_report", "page_number": 1, "section_title": None,
        "quote": "메모리 제조 부문의 판매량이 증가할 전망이다. 파운드리는 적자 상태다."}
    monkeypatch.setattr("app.analysis_retrieval.hybrid_search",
        lambda *args, **kwargs: SearchExecution([row], True, None))
    result = collect_analysis_evidence(object(), document_id,
        "파운드리와 메모리 제조 경쟁력의 긍정 요인을 설명해줘.", 10, object())
    assert result and result[0]["analysis_perspective"] == "positive"


def test_general_summary_keeps_disjoint_positive_and_negative_spans_from_same_chunk(monkeypatch) -> None:
    document_id = uuid4(); mixed_id = uuid4(); negative_id = uuid4()
    base = {"rank": 1, "rrf_score": 0.03, "bm25_rank": 1, "vector_rank": 1,
        "document_id": document_id, "document_name": "report.pdf", "company_name": "삼성전자",
        "ticker": "005930", "publisher": "기관", "published_at": None,
        "document_type": "broker_report", "page_number": 1, "section_title": None}
    mixed = {**base, "chunk_id": mixed_id,
        "quote": "판매량은 증가할 전망이다. 파운드리 사업은 적자 상태다."}
    negative = {**base, "chunk_id": negative_id, "page_number": 3,
        "quote": "영업이익률 (%) Foundry/LS -20.0 -33.3 -12.4"}
    monkeypatch.setattr("app.analysis_retrieval.hybrid_search",
        lambda *args, **kwargs: SearchExecution([mixed, negative], True, None))
    question = "이 보고서를 읽고 주식 초보자 관점에서 호재와 악재를 각각 최대 3개까지 요약해줘."
    results = collect_analysis_evidence(object(), document_id, question, 10, object())
    mixed_results = [result for result in results if result.get("source_chunk_id") == mixed_id]
    assert {result["analysis_perspective"] for result in mixed_results} == {"positive", "negative"}
    positive = next(result for result in mixed_results if result["analysis_perspective"] == "positive")
    negative = next(result for result in mixed_results if result["analysis_perspective"] == "negative")
    assert positive["char_end"] <= negative["char_start"]
    assert not any(result.get("source_chunk_id") == negative_id for result in results)


def test_general_summary_excludes_ambiguous_mixed_sentence(monkeypatch) -> None:
    document_id = uuid4(); mixed_id = uuid4(); positive_id = uuid4()
    base = {"rank": 1, "rrf_score": 0.03, "bm25_rank": 1, "vector_rank": 1,
        "document_id": document_id, "document_name": "report.pdf", "company_name": "삼성전자",
        "ticker": "005930", "publisher": "기관", "published_at": None,
        "document_type": "broker_report", "page_number": 1, "section_title": None}
    mixed = {**base, "chunk_id": mixed_id,
        "quote": "영업이익은 시장 기대치를 하회했지만 이후 판매량 증가가 예상된다."}
    positive = {**base, "chunk_id": positive_id,
        "quote": "HBM 가격 상승과 DRAM 수요 증가가 예상된다."}
    monkeypatch.setattr("app.analysis_retrieval.hybrid_search",
        lambda *args, **kwargs: SearchExecution([mixed, positive], True, None))
    question = "이 보고서를 읽고 주식 초보자 관점에서 호재와 악재를 각각 최대 3개까지 요약해줘."
    results = collect_analysis_evidence(object(), document_id, question, 10, object())
    mixed_results = [result for result in results if result.get("source_chunk_id") == mixed_id]
    assert mixed_results == []
    assert any(result.get("source_chunk_id", result["chunk_id"]) == positive_id
        and result["analysis_perspective"] == "positive" for result in results)


def test_excerpt_is_short_and_exact_database_substring() -> None:
    text = "일반 설명입니다. " * 40 + "파운드리 가동률 상승으로 적자 축소가 진행될 전망입니다. " + "기타 설명입니다. " * 40
    excerpt = readable_excerpt(text, "파운드리 수익성 위험")
    assert excerpt is not None and excerpt in text and len(excerpt) <= 320
    assert "파운드리" in excerpt and "적자 축소" in excerpt


def test_excerpt_does_not_mix_business_fact_with_target_price_lines() -> None:
    text = "파운드리 가동률 상승에 따라 적자 축소가 진행될 전망입니다.\n목표주가 7.9만원 유지.\n투자의견 Buy 유지."
    excerpt = readable_excerpt(text, "파운드리 적자 수익성")
    assert excerpt == "파운드리 가동률 상승에 따라 적자 축소가 진행될 전망입니다."


def test_negative_facts_are_excerpted_before_later_positive_outlook() -> None:
    text = ("2Q25 영업이익은 시장 기대치를 하회하는 실적을 기록했습니다.\n"
        "일회성 비용과 재고 평가 충당금이 발생했습니다.\n"
        "3Q25 가격 상승으로 이익 개선이 예상됩니다.")
    excerpt = readable_excerpt(text, "기대 하회 비용 충당금 부진 위험")
    assert excerpt is not None and "기대치를 하회" in excerpt


def test_excerpt_preserves_decimal_number() -> None:
    text = "2Q25 영업이익은 4.6조원으로 시장 기대치를 하회했습니다. 다음 문장입니다."
    excerpt = readable_excerpt(text, "영업이익 기대 하회")
    assert excerpt is not None and "4.6조원" in excerpt


def test_excerpt_stops_before_standalone_ocr_noise_line() -> None:
    text = ("HBM 가격 상승으로 DRAM ASP 상승이 예상됩니다.\n"
        "be\n사업 전방과 eens 전해지는 별도 문단입니다.")
    excerpt = readable_excerpt(text, "HBM DRAM 가격 상승", preferred_pattern=STRONG_POSITIVE_PATTERN)
    assert excerpt == "HBM 가격 상승으로 DRAM ASP 상승이 예상됩니다."


def test_analysis_retrieval_uses_question_positive_and_negative_queries(monkeypatch) -> None:
    calls = []
    document_id = uuid4(); chunk_id = uuid4()
    row = {"rank": 1, "rrf_score": 0.03, "bm25_rank": 1, "vector_rank": 1,
        "chunk_id": chunk_id, "document_id": document_id, "document_name": "report.pdf",
        "company_name": "기업", "ticker": "000000", "publisher": "기관", "published_at": None,
        "document_type": "broker_report", "page_number": 2, "section_title": None,
        "quote": "파운드리 적자가 줄어 수익성이 개선될 전망이다."}

    def fake_search(db, query, top_k, filters, provider):
        calls.append(query)
        assert filters.document_id == document_id
        return SearchExecution([row], True, None)

    monkeypatch.setattr("app.analysis_retrieval.hybrid_search", fake_search)
    results = collect_analysis_evidence(object(), document_id, "회사를 분석해줘", 10, object())
    assert len(calls) == 3 and POSITIVE_QUERY in calls[1] and NEGATIVE_QUERY in calls[2]
    assert results[0]["chunk_id"] == chunk_id


def test_general_summary_uses_standalone_perspective_queries_and_balanced_candidates(monkeypatch) -> None:
    document_id = uuid4(); positive_id = uuid4(); negative_id = uuid4()
    base = {"rank": 1, "rrf_score": 0.03, "bm25_rank": 1, "vector_rank": 1,
        "document_id": document_id, "document_name": "report.pdf", "company_name": "삼성전자",
        "ticker": "005930", "publisher": "기관", "published_at": None,
        "document_type": "broker_report", "page_number": 1, "section_title": None}
    positive = {**base, "chunk_id": positive_id,
        "quote": "HBM 가격 상승과 DRAM 수요 증가로 실적 개선이 예상된다."}
    negative = {**base, "chunk_id": negative_id, "page_number": 3,
        "quote": "파운드리 사업은 대규모 투자에도 적자 상태가 이어진다."}
    calls = []

    def fake_search(db, query, top_k, filters, provider):
        calls.append(query)
        if query == POSITIVE_QUERY:
            return SearchExecution([positive], True, None)
        if query == NEGATIVE_QUERY:
            return SearchExecution([negative], True, None)
        return SearchExecution([], True, None)

    monkeypatch.setattr("app.analysis_retrieval.hybrid_search", fake_search)
    question = "이 보고서를 읽고 주식 초보자 관점에서 호재와 악재를 각각 최대 3개까지 요약해줘."
    results = collect_analysis_evidence(object(), document_id, question, 10, object())
    assert calls == [question, POSITIVE_QUERY, NEGATIVE_QUERY]
    assert {result["analysis_perspective"] for result in results} == {"positive", "negative"}


def test_general_summary_keeps_empty_result_when_document_has_no_business_evidence(monkeypatch) -> None:
    document_id = uuid4()
    row = {"rank": 1, "rrf_score": 0.03, "bm25_rank": 1, "vector_rank": 1,
        "chunk_id": uuid4(), "document_id": document_id, "document_name": "report.pdf",
        "company_name": "기업", "ticker": None, "publisher": "기관", "published_at": None,
        "document_type": "broker_report", "page_number": 1, "section_title": None,
        "quote": "이 문서는 회사의 일반적인 연혁을 소개합니다."}
    monkeypatch.setattr("app.analysis_retrieval.hybrid_search",
        lambda *args, **kwargs: SearchExecution([row], True, None))
    question = "이 보고서를 읽고 주식 초보자 관점에서 호재와 악재를 각각 최대 3개까지 요약해줘."
    assert collect_analysis_evidence(object(), document_id, question, 10, object()) == []


def test_negative_excerpt_keeps_question_specific_hbm_and_foundry_context(monkeypatch) -> None:
    document_id = uuid4(); chunk_id = uuid4()
    text = ("2Q25 영업이익은 시장 기대치를 하회했습니다. 기타 설명이 이어집니다. " * 8
        + "상반기 HBM 출하량 저조로 재고 평가 충당금이 발생했고 파운드리에도 재고 평가 충당금이 반영됐습니다.")
    row = {"rank": 1, "rrf_score": 0.03, "bm25_rank": 1, "vector_rank": 1,
        "chunk_id": chunk_id, "document_id": document_id, "document_name": "report.pdf",
        "company_name": "삼성전자", "ticker": "005930", "publisher": "기관", "published_at": None,
        "document_type": "broker_report", "page_number": 1, "section_title": None, "quote": text}
    monkeypatch.setattr("app.analysis_retrieval.hybrid_search",
        lambda *args, **kwargs: SearchExecution([row], True, None))
    result = collect_analysis_evidence(object(), document_id, "HBM 출하와 파운드리 위험", 10, object())[0]
    assert result["analysis_perspective"] == "negative"
    assert "HBM" in result["quote"] and "파운드리" in result["quote"] and result["quote"] in text


def test_specific_unsupported_question_does_not_keep_generic_expansion_candidates(monkeypatch) -> None:
    document_id = uuid4(); chunk_id = uuid4()
    row = {"rank": 1, "rrf_score": 0.03, "bm25_rank": None, "vector_rank": 1,
        "chunk_id": chunk_id, "document_id": document_id, "document_name": "report.pdf",
        "company_name": "삼성전자", "ticker": "005930", "publisher": "기관", "published_at": None,
        "document_type": "broker_report", "page_number": 1, "section_title": None,
        "quote": "하반기 실적 개선과 파운드리 적자 축소가 예상됩니다."}
    monkeypatch.setattr("app.analysis_retrieval.hybrid_search",
        lambda *args, **kwargs: SearchExecution([row], True, None))
    question = "삼성전자의 2030년 탄소배출 감축 목표와 달성률을 설명해줘."
    assert {"탄소배출", "감축", "달성률"}.issubset(question_focus_terms(question))
    assert collect_analysis_evidence(object(), document_id, question, 10, object()) == []


def test_positive_outlook_question_keeps_direct_improvement_pattern(monkeypatch) -> None:
    document_id = uuid4(); chunk_id = uuid4()
    row = {"rank": 1, "rrf_score": 0.03, "bm25_rank": 1, "vector_rank": 1,
        "chunk_id": chunk_id, "document_id": document_id, "document_name": "report.pdf",
        "company_name": "삼성전자", "ticker": "005930", "publisher": "기관", "published_at": None,
        "document_type": "broker_report", "page_number": 1, "section_title": None,
        "quote": "파운드리 가동률 상승에 따라 점진적 적자 축소가 진행될 것으로 판단합니다."}
    monkeypatch.setattr("app.analysis_retrieval.hybrid_search",
        lambda *args, **kwargs: SearchExecution([row], True, None))
    results = collect_analysis_evidence(object(), document_id,
        "보고서의 가동률 전망은 무엇이야?", 10, object())
    assert len(results) == 1 and results[0]["analysis_perspective"] == "positive"


def test_general_summary_prefers_report_wide_positive_outlook_sentence() -> None:
    text = ("파운드리 가동률 상승에 따라 적자 축소가 진행될 것으로 판단합니다.\n"
        "여전히 비관론이 우세하나 하반기 개선될 실적 모멘텀을 고려하면 경쟁사와의 밸류 갭 축소 움직임이 기대됩니다.")
    excerpt = readable_excerpt(text, "실적 성장 증가 개선 회복 수요 가격 점유율",
        preferred_pattern=GENERAL_SUMMARY_POSITIVE_PATTERN)
    assert excerpt and "하반기 개선될 실적 모멘텀" in excerpt and "밸류 갭 축소" in excerpt


# Full table structure and page offsets are tested in test_evidence_facts.py.
