"""Pure aggregation for the generation faithfulness evaluation (plan step 6).

Reads analysis responses and evaluate_case results; never calls retrieval or generation.
"""
import re
from collections import Counter
from typing import Any

from app.evaluation import evaluate_case
from app.evidence_integrity import span_is_covered

CANNOT_CONFIRM = "확인할 수 없습니다"
PROVIDER_ERROR_PATTERN = re.compile(r"HTTP (429|502|503|504)\b|timed out|timeout", re.IGNORECASE)
STAGE_BUCKETS = {
    "retrieval_candidate_excluded": "retrieval",
    "retrieval_wrong_perspective": "retrieval",
    "analysis_filter_excluded": "analysis_filter",
    "generation_not_selected": "generation",
    "output_validation_removed": "citation",
    "selected": "judged_mismatch",
    "trace_unavailable": "trace_unavailable",
}


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _source_ids(citation: dict[str, Any]) -> list[str]:
    ids = [str(value) for value in citation.get("source_chunk_ids") or []]
    if not ids and citation.get("source_chunk_id"):
        ids = [str(citation["source_chunk_id"])]
    return ids or [str(citation.get("chunk_id"))]


def citation_problems(citation: dict[str, Any], pages: dict[int, Any], chunks: dict[str, Any]) -> list[str]:
    """Return reasons a citation is not a verbatim span of its own document page; empty means valid.

    A citation's chunk_id may be a derived evidence-span ID; the stored chunks are its source_chunk_ids.
    """
    sources = [chunks.get(chunk_id) for chunk_id in _source_ids(citation)]
    if any(source is None for source in sources):
        return ["chunk_not_in_document"]
    page_number = citation.get("page_number")
    page = pages.get(page_number)
    if page is None or any(source.page_number != page_number for source in sources):
        return ["page_mismatch"]
    quote = str(citation.get("quote", ""))
    start, end = citation.get("char_start"), citation.get("char_end")
    if start is None or end is None:
        return [] if quote and quote in page.final_text else ["quote_not_in_page"]
    return [] if span_is_covered(page, sources, start, end, quote) else ["span_not_covered"]


def response_citation_report(response: dict[str, Any], pages: dict[int, Any], chunks: dict[str, Any]) -> dict:
    citations = response.get("citations") or []
    problems = [{"chunk_id": str(row.get("chunk_id")), "page_number": row.get("page_number"), "reasons": reasons}
        for row in citations if (reasons := citation_problems(row, pages, chunks))]
    cited_ids = {str(row.get("chunk_id")) for row in citations}
    items = (response.get("positives") or []) + (response.get("negatives") or [])
    evidence_ids = {str(chunk_id) for item in items for chunk_id in item.get("evidence_chunk_ids", [])}
    unlinked = len(evidence_ids - cited_ids)
    return {"citation_count": len(citations), "valid_citation_count": len(citations) - len(problems),
        "unlinked_evidence_ids": unlinked,
        "all_valid": (not problems and not unlinked) if citations else None, "problems": problems}


def refusal_outcome(expected_polarity: str, response: dict[str, Any]) -> dict[str, bool]:
    refused = not response.get("positives") and not response.get("negatives") and not response.get("citations")
    exposed = " ".join(str(response.get(field) or "") for field in ("summary", "insufficient_evidence_note"))
    correct = refused if expected_polarity == "insufficient" else not refused
    return {"refused": refused, "correct": correct, "cannot_confirm_phrase": CANNOT_CONFIRM in exposed}


def perspective_outcome(expected_polarity: str, response: dict[str, Any]) -> dict[str, Any] | None:
    """An answer whose items are all of the opposite perspective is a mismatch, not a refusal.

    Mixed answers (expected and opposite items) are normal for this service and only counted.
    """
    if expected_polarity not in ("positive", "negative"):
        return None
    opposite = "negatives" if expected_polarity == "positive" else "positives"
    expected_items = len(response.get(f"{expected_polarity}s") or [])
    opposite_items = len(response.get(opposite) or [])
    answered = bool(expected_items or opposite_items)
    return {"expected_items": expected_items, "opposite_items": opposite_items, "answered": answered,
        "mismatch": answered and not expected_items, "mixed": bool(expected_items and opposite_items)}


def classify_outcome(result: dict[str, Any]) -> str:
    if "request_error" in result.get("failures", []):
        return "provider_error" if PROVIDER_ERROR_PATTERN.search(str(result.get("error", ""))) else "request_error"
    if result.get("passed"):
        return "passed"
    if result.get("expected_polarity") == "insufficient":
        return "refusal_failed"
    stage = (result.get("diagnostics") or {}).get("stage")
    return STAGE_BUCKETS.get(stage, "unclassified")


def reevaluate_row(row: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    """Re-judge a saved case with the current evaluate_case; request errors keep their saved result."""
    if row.get("response") is None:
        return row
    return {**row, "result": evaluate_case(case, row["response"], row.get("trace"))}


def summarize_generation(rows: list[dict[str, Any]]) -> dict[str, Any]:
    citation_rows = [row["citations"] for row in rows if row.get("citations")]
    valid = sum(row["valid_citation_count"] for row in citation_rows)
    total = sum(row["citation_count"] for row in citation_rows)
    with_citations = [row for row in citation_rows if row["citation_count"]]
    evaluated = [row for row in rows if row.get("refusal")]
    insufficient = [row for row in evaluated if row["expected_polarity"] == "insufficient"]
    answerable = [row for row in evaluated if row["expected_polarity"] != "insufficient"]
    insufficient_correct = sum(row["refusal"]["correct"] for row in insufficient)
    false_refusals = sum(row["refusal"]["refused"] for row in answerable)
    perspectives = [row["perspective"] for row in answerable if row.get("perspective")]
    mismatches = sum(outcome["mismatch"] for outcome in perspectives)
    return {
        "cases": len(rows),
        "outcomes": dict(Counter(row["outcome"] for row in rows)),
        "citation_validity": {"valid": valid, "total": total, "rate": _rate(valid, total),
            "cases_with_citations": len(with_citations),
            "cases_all_valid": sum(bool(row["all_valid"]) for row in with_citations)},
        "refusal": {"insufficient_evaluated": len(insufficient), "insufficient_correct": insufficient_correct,
            "insufficient_correct_rate": _rate(insufficient_correct, len(insufficient)),
            "answerable_evaluated": len(answerable), "answerable_false_refusals": false_refusals,
            "answerable_false_refusal_rate": _rate(false_refusals, len(answerable)),
            "excluded_request_errors": len(rows) - len(evaluated)},
        "perspective": {"answerable_evaluated": len(perspectives),
            "answerable_answered": sum(outcome["answered"] for outcome in perspectives),
            "mismatch": mismatches, "mismatch_rate": _rate(mismatches, len(perspectives)),
            "mixed": sum(outcome["mixed"] for outcome in perspectives)},
    }
