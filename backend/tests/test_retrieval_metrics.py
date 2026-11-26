import pytest

from app.retrieval_metrics import first_match_rank, summarize, summarize_by_group, unit_matches


def _result(rank: int, page: int, quote: str = "", **extra) -> dict:
    return {"rank": rank, "page_number": page, "quote": quote, "table_evidence": [], **extra}


def test_empty_results_have_no_match_rank() -> None:
    assert first_match_rank([], [{"page_number": 1}]) is None


def test_unit_without_evidence_fields_matches_on_page_only() -> None:
    assert unit_matches(_result(1, 1, "아무 문장"), {"page_number": 1})
    assert not unit_matches(_result(1, 2, "아무 문장"), {"page_number": 1})


def test_literal_conditions_require_every_phrase_ignoring_whitespace() -> None:
    unit = {"page_number": 3, "literal_conditions": ["영업이익은 5,330억원", "92.5% 증가"]}
    assert unit_matches(_result(1, 3, "2Q26 연결 영업이익은\n5,330 억원으로 92.5% 증가했다"), unit)
    assert not unit_matches(_result(1, 3, "2Q26 연결 영업이익은 5,330억원"), unit)


def test_table_unit_matches_structured_fact_and_rejects_other_period() -> None:
    unit = {"page_number": 2, "table": {"row_label": "보험손익", "period": "1Q26", "unit": "십억원", "value": "227"}}
    fact = {"row_label": "보험손익", "period": "1Q26", "unit": "십억원", "value": "227", "status": "unspecified"}
    assert unit_matches(_result(1, 2, table_evidence=[fact]), unit)
    assert not unit_matches(_result(1, 2, table_evidence=[{**fact, "period": "2Q26F"}]), unit)


def test_table_unit_skips_null_gold_fields() -> None:
    unit = {"page_number": 2, "table": {"row_label": "LG CNS", "period": None, "unit": "조원", "value": "3.42"}}
    fact = {"row_label": "LG CNS", "period": "2026F", "unit": "조원", "value": "3.42"}
    assert unit_matches(_result(1, 2, table_evidence=[fact]), unit)


def test_table_unit_falls_back_to_row_label_and_value_in_quote() -> None:
    unit = {"page_number": 2, "table": {"row_label": "철강", "period": "2Q26F", "value": "424"}}
    assert unit_matches(_result(1, 2, "철강 영업이익 2Q26F 424"), unit)
    assert not unit_matches(_result(1, 2, "철강 영업이익 2Q26F 425"), unit)


def test_numeric_unit_matches_fact_or_value_in_quote() -> None:
    unit = {"page_number": 1, "numeric": [{"metric": "순이익", "value": "4,993"}, {"metric": "순이익", "value": "13.8"}]}
    structured = _result(1, 1, "순이익 4,993억원", numeric_evidence=[{"metric": "순이익", "value": "13.8"}])
    assert unit_matches(structured, unit)
    assert not unit_matches(_result(1, 1, "순이익 4,993억원"), unit)


def test_page_only_mode_ignores_evidence_conditions() -> None:
    unit = {"page_number": 1, "literal_conditions": ["없는 문장"]}
    assert not unit_matches(_result(1, 1, "다른 문장"), unit)
    assert unit_matches(_result(1, 1, "다른 문장"), unit, page_only=True)


def test_first_match_rank_uses_best_rank_across_units() -> None:
    units = [{"page_number": 2}, {"page_number": 1}]
    results = [_result(1, 3), _result(2, 1), _result(3, 2)]
    assert first_match_rank(results, units) == 2


def test_summarize_computes_hits_recall_and_mrr() -> None:
    metrics = summarize(case_ranks=[1, 3, None], unit_ranks=[1, 4, None, 6])
    assert metrics["hit@1"] == [1, 3]
    assert metrics["hit@3"] == [2, 3]
    assert metrics["hit@5"] == [2, 3]
    assert metrics["unit_recall@5"] == [2, 4]
    assert metrics["mrr@5"] == pytest.approx((1 + 1 / 3) / 3)


def test_summarize_ignores_ranks_beyond_cutoff_in_mrr() -> None:
    assert summarize(case_ranks=[6], unit_ranks=[6])["mrr@5"] == 0.0


def test_summarize_empty_input_returns_zero_without_division_error() -> None:
    metrics = summarize(case_ranks=[], unit_ranks=[])
    assert metrics["hit@1"] == [0, 0]
    assert metrics["mrr@5"] == 0.0


def test_summarize_by_group_splits_cases_and_units_by_label() -> None:
    case_ranks = {"a": 1, "b": None, "c": 2}
    unit_ranks = {"a": [1], "b": [None, 3], "c": [2]}
    groups = {"a": "exact", "b": "exact", "c": "semantic"}
    metrics = summarize_by_group(case_ranks, unit_ranks, groups)
    assert sorted(metrics) == ["exact", "semantic"]
    assert metrics["exact"]["hit@1"] == [1, 2]
    assert metrics["exact"]["unit_recall@5"] == [2, 3]
    assert metrics["semantic"]["mrr@5"] == pytest.approx(0.5)


def test_summarize_by_group_ignores_labels_for_cases_not_measured() -> None:
    metrics = summarize_by_group({"a": 1}, {"a": [1]}, {"a": "exact", "unanswerable": "semantic"})
    assert sorted(metrics) == ["exact"]


def test_summarize_by_group_rejects_case_without_label() -> None:
    with pytest.raises(ValueError, match="b"):
        summarize_by_group({"a": 1, "b": 2}, {"a": [1], "b": [2]}, {"a": "exact"})
