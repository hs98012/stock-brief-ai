from types import SimpleNamespace
from uuid import uuid4

from app.generation_metrics import (
    citation_problems,
    classify_outcome,
    refusal_outcome,
    response_citation_report,
    summarize_generation,
)

DOC_ID = uuid4()
PAGE_TEXT = "1Q 실적 요약. HBM 공급 확대로 메모리 이익이 개선됐다. 파운드리 적자는 지속됐다."


def _page(number: int = 1, text: str = PAGE_TEXT):
    return SimpleNamespace(id=uuid4(), document_id=DOC_ID, page_number=number, final_text=text)


def _chunk(page, start: int, end: int):
    return SimpleNamespace(id=uuid4(), document_id=page.document_id, page_id=page.id,
        page_number=page.page_number, char_start=start, char_end=end, content=page.final_text[start:end])


def _citation(chunk, quote: str, start: int | None, end: int | None, page_number: int = 1) -> dict:
    return {"chunk_id": str(chunk.id), "page_number": page_number, "quote": quote,
        "source_chunk_ids": [str(chunk.id)], "char_start": start, "char_end": end}


def _setup():
    page = _page()
    chunk = _chunk(page, 0, len(PAGE_TEXT))
    return chunk, {1: page}, {str(chunk.id): chunk}


def test_citation_with_exact_offsets_is_valid() -> None:
    chunk, pages, chunks = _setup()
    quote = "HBM 공급 확대로 메모리 이익이 개선됐다."
    start = PAGE_TEXT.index(quote)
    assert citation_problems(_citation(chunk, quote, start, start + len(quote)), pages, chunks) == []


def test_citation_quote_that_differs_from_offsets_is_invalid() -> None:
    chunk, pages, chunks = _setup()
    start = PAGE_TEXT.index("HBM")
    problems = citation_problems(_citation(chunk, "HBM 공급 축소", start, start + 9), pages, chunks)
    assert problems == ["span_not_covered"]


def test_citation_chunk_outside_document_is_invalid() -> None:
    _, pages, chunks = _setup()
    foreign = _chunk(_page(), 0, 5)
    assert citation_problems(_citation(foreign, PAGE_TEXT[:5], 0, 5), pages, chunks) == ["chunk_not_in_document"]


def test_citation_span_id_is_resolved_through_source_chunk_ids() -> None:
    chunk, pages, chunks = _setup()
    quote = PAGE_TEXT[:9]
    citation = {**_citation(chunk, quote, 0, len(quote)), "chunk_id": str(uuid4()), "source_chunk_id": str(chunk.id)}
    assert citation_problems(citation, pages, chunks) == []


def test_citation_page_number_mismatch_is_invalid() -> None:
    chunk, pages, chunks = _setup()
    problems = citation_problems(_citation(chunk, PAGE_TEXT[:5], 0, 5, page_number=2), pages, chunks)
    assert "page_mismatch" in problems


def test_citation_without_offsets_falls_back_to_substring() -> None:
    chunk, pages, chunks = _setup()
    assert citation_problems(_citation(chunk, "파운드리 적자는 지속됐다.", None, None), pages, chunks) == []
    assert citation_problems(_citation(chunk, "없는 문장", None, None), pages, chunks) == ["quote_not_in_page"]


def test_response_report_flags_item_evidence_without_citation() -> None:
    chunk, pages, chunks = _setup()
    quote = PAGE_TEXT[:9]
    response = {"positives": [{"evidence_chunk_ids": [str(chunk.id), str(uuid4())]}], "negatives": [],
        "citations": [_citation(chunk, quote, 0, len(quote))]}
    report = response_citation_report(response, pages, chunks)
    assert report["citation_count"] == 1 and report["valid_citation_count"] == 1
    assert report["unlinked_evidence_ids"] == 1
    assert report["all_valid"] is False


def test_response_report_without_citations_has_no_validity_verdict() -> None:
    _, pages, chunks = _setup()
    report = response_citation_report({"positives": [], "negatives": [], "citations": []}, pages, chunks)
    assert report == {"citation_count": 0, "valid_citation_count": 0, "unlinked_evidence_ids": 0,
        "all_valid": None, "problems": []}


def test_refusal_outcome_for_insufficient_and_answerable_cases() -> None:
    refused = {"positives": [], "negatives": [], "citations": [], "summary": "확인할 수 없습니다"}
    answered = {"positives": [{"title": "x"}], "negatives": [], "citations": [{"chunk_id": "a"}], "summary": "요약"}
    assert refusal_outcome("insufficient", refused) == {"refused": True, "correct": True, "cannot_confirm_phrase": True}
    assert refusal_outcome("insufficient", answered)["correct"] is False
    assert refusal_outcome("positive", refused) == {"refused": True, "correct": False, "cannot_confirm_phrase": True}
    assert refusal_outcome("negative", answered)["correct"] is True


def _result(passed: bool, polarity: str = "positive", stage: str | None = None,
        failures: list[str] | None = None, error: str | None = None) -> dict:
    row = {"passed": passed, "expected_polarity": polarity, "failures": failures or [],
        "diagnostics": {"stage": stage} if stage else {}}
    if error:
        row["error"] = error
    return row


def test_classify_outcome_separates_provider_errors_from_quality_failures() -> None:
    assert classify_outcome(_result(False, failures=["request_error"], error="HTTP 503: busy")) == "provider_error"
    assert classify_outcome(_result(False, failures=["request_error"], error="timed out")) == "provider_error"
    assert classify_outcome(_result(False, failures=["request_error"], error="HTTP 500: boom")) == "request_error"
    assert classify_outcome(_result(True, stage="selected")) == "passed"
    assert classify_outcome(_result(False, "insufficient", "not_applicable", ["polarity"])) == "refusal_failed"


def test_classify_outcome_maps_stages_to_retrieval_generation_citation() -> None:
    assert classify_outcome(_result(False, stage="retrieval_candidate_excluded", failures=["topic"])) == "retrieval"
    assert classify_outcome(_result(False, stage="retrieval_wrong_perspective", failures=["topic"])) == "retrieval"
    assert classify_outcome(_result(False, stage="generation_not_selected", failures=["topic"])) == "generation"
    assert classify_outcome(_result(False, stage="output_validation_removed", failures=["topic"])) == "citation"
    assert classify_outcome(_result(False, stage="selected", failures=["topic"])) == "judged_mismatch"
    assert classify_outcome(_result(False, stage="trace_unavailable", failures=["topic"])) == "trace_unavailable"


def test_summarize_generation_empty_rows() -> None:
    summary = summarize_generation([])
    assert summary["cases"] == 0
    assert summary["citation_validity"]["rate"] is None
    assert summary["refusal"]["insufficient_correct_rate"] is None


def test_summarize_generation_counts_rates_and_excludes_request_errors_from_refusal() -> None:
    rows = [
        {"outcome": "passed", "expected_polarity": "positive",
         "refusal": {"refused": False, "correct": True, "cannot_confirm_phrase": False},
         "citations": {"citation_count": 2, "valid_citation_count": 2, "all_valid": True}},
        {"outcome": "retrieval", "expected_polarity": "negative",
         "refusal": {"refused": True, "correct": False, "cannot_confirm_phrase": True},
         "citations": {"citation_count": 0, "valid_citation_count": 0, "all_valid": None}},
        {"outcome": "passed", "expected_polarity": "insufficient",
         "refusal": {"refused": True, "correct": True, "cannot_confirm_phrase": True},
         "citations": {"citation_count": 0, "valid_citation_count": 0, "all_valid": None}},
        {"outcome": "provider_error", "expected_polarity": "insufficient", "refusal": None, "citations": None},
    ]
    summary = summarize_generation(rows)
    assert summary["cases"] == 4
    assert summary["outcomes"] == {"passed": 2, "retrieval": 1, "provider_error": 1}
    assert summary["citation_validity"] == {"valid": 2, "total": 2, "rate": 1.0,
        "cases_with_citations": 1, "cases_all_valid": 1}
    assert summary["refusal"] == {"insufficient_evaluated": 1, "insufficient_correct": 1,
        "insufficient_correct_rate": 1.0, "answerable_evaluated": 2, "answerable_false_refusals": 1,
        "answerable_false_refusal_rate": 0.5, "excluded_request_errors": 1}
