from types import SimpleNamespace

import pytest

from app.database import require_postgresql
from app.packet_metrics import (
    check_split_allowed,
    dev_case_result,
    expected_page_exclusions,
    gold_unit_result,
    summarize_dev,
    summarize_units,
)


def _span(page: int, perspective: str = "positive", quote: str = "HBM 공급 확대로 이익이 개선됐다.") -> dict:
    return {"page_number": page, "analysis_perspective": perspective, "quote": quote}


def _dev_case(polarity: str = "positive", pages: list[int] | None = None) -> dict:
    return {"id": "case", "expected_polarity": polarity, "expected_pages": [1] if pages is None else pages}


def test_dev_case_counts_expected_page_span_in_packet():
    # Arrange
    packet = [_span(2), _span(1, "negative")]

    # Act
    result = dev_case_result(_dev_case(), packet)

    # Assert
    assert result["expected_page_in_packet"] is True
    assert result["expected_page_polarity_in_packet"] is False
    assert result["packet_size"] == 2
    assert result["packet_pages"] == [1, 2]


def test_dev_case_requires_matching_perspective_for_polarity_hit():
    result = dev_case_result(_dev_case("negative"), [_span(1, "negative")])

    assert result["expected_page_in_packet"] is True
    assert result["expected_page_polarity_in_packet"] is True


def test_dev_case_misses_when_packet_has_only_other_pages():
    result = dev_case_result(_dev_case(), [_span(3)])

    assert result["expected_page_in_packet"] is False
    assert result["expected_page_polarity_in_packet"] is False


def test_insufficient_case_has_no_inclusion_judgement():
    result = dev_case_result(_dev_case("insufficient", []), [_span(1)])

    assert result["expected_page_in_packet"] is None
    assert result["expected_page_polarity_in_packet"] is None
    assert result["packet_size"] == 1


def test_expected_page_exclusions_counts_only_expected_pages():
    diagnostics = {"filter_exclusions": [
        {"page_number": 1, "filter": "perspective", "reason": "neutral"},
        {"page_number": 1, "filter": "perspective", "reason": "neutral"},
        {"page_number": 2, "filter": "focus", "reason": "focus_terms_missing"},
        {"page_number": 1, "filter": "quality", "reason": "ocr_noise"},
    ]}

    assert expected_page_exclusions(diagnostics, [1]) == {"perspective:neutral": 2, "quality:ocr_noise": 1}


def test_expected_page_exclusions_handles_missing_diagnostics():
    assert expected_page_exclusions({}, [1]) == {}


def test_summarize_dev_reports_answerable_rate_and_insufficient_sizes():
    rows = [
        dev_case_result(_dev_case(), [_span(1)]),
        dev_case_result(_dev_case("negative"), [_span(1, "positive")]),
        dev_case_result(_dev_case(), []),
        dev_case_result(_dev_case("insufficient", []), []),
    ]

    summary = summarize_dev(rows)

    assert summary["answerable"] == 3
    assert summary["expected_page_in_packet"] == [2, 3]
    assert summary["expected_page_polarity_in_packet"] == [1, 3]
    assert summary["empty_packet_answerable"] == 1
    assert summary["insufficient"] == 1
    assert summary["insufficient_packet_sizes"] == [0]


def test_gold_unit_requires_literal_conditions_on_same_page():
    unit = {"case": "c1", "unit": "u1", "page_number": 1, "literal_conditions": ["이익이 개선"]}

    assert gold_unit_result(unit, [_span(1)])["in_packet"] is True
    assert gold_unit_result(unit, [_span(2)])["in_packet"] is False
    assert gold_unit_result(unit, [_span(1, quote="파운드리 적자")])["in_packet"] is False


def test_gold_unit_literal_match_ignores_whitespace():
    unit = {"case": "c1", "unit": "u1", "page_number": 1, "literal_conditions": ["이익이개선됐다"]}

    assert gold_unit_result(unit, [_span(1)])["in_packet"] is True


def test_summarize_units_counts_total_and_cases():
    rows = [
        {"case": "c1", "unit": "u1", "in_packet": True},
        {"case": "c1", "unit": "u2", "in_packet": False},
        {"case": "c2", "unit": "u3", "in_packet": False},
    ]

    summary = summarize_units(rows)

    assert summary["units_in_packet"] == [1, 3]
    assert summary["cases_with_any_unit"] == [1, 2]


def test_test_split_requires_explicit_final_confirmation():
    with pytest.raises(SystemExit):
        check_split_allowed("test-v2", confirm_final=False)
    check_split_allowed("test-v2", confirm_final=True)
    check_split_allowed("dev", confirm_final=False)


def test_unknown_split_is_refused():
    with pytest.raises(SystemExit):
        check_split_allowed("holdout-v1", confirm_final=True)


def test_require_postgresql_refuses_other_dialects():
    with pytest.raises(SystemExit):
        require_postgresql(SimpleNamespace(dialect=SimpleNamespace(name="sqlite")))
    require_postgresql(SimpleNamespace(dialect=SimpleNamespace(name="postgresql")))
