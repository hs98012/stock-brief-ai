"""Pure judgements for the analysis-packet inclusion measurement (plan step 13).

A packet is the list collect_analysis_evidence returns; generation is never involved.
- dev fixtures: a case is included when any packet span sits on an expected page (page level).
- test-v2 gold: a unit is included when a packet span on its page holds every literal
  condition (retrieval_metrics.unit_matches), which is stricter than page level.
"""
from collections import Counter
from typing import Any

from app.retrieval_metrics import unit_matches

ALLOWED_SPLITS = ("dev", "test-v2")
FINAL_ONLY_SPLITS = ("test-v2",)


def check_split_allowed(split: str, *, confirm_final: bool) -> None:
    if split not in ALLOWED_SPLITS:
        raise SystemExit(f"{split}: 허용된 split은 {ALLOWED_SPLITS}뿐입니다.")
    if split in FINAL_ONLY_SPLITS and not confirm_final:
        raise SystemExit(f"{split}는 최종 확인용입니다. --confirm-final 없이 실행하지 않습니다.")


def dev_case_result(case: dict[str, Any], packet: list[dict[str, Any]]) -> dict[str, Any]:
    expected_pages = set(case.get("expected_pages") or [])
    answerable = case["expected_polarity"] != "insufficient"
    on_expected = [span for span in packet if span["page_number"] in expected_pages]
    return {
        "case_id": case["id"],
        "expected_polarity": case["expected_polarity"],
        "expected_pages": sorted(expected_pages),
        "packet_size": len(packet),
        "packet_pages": sorted({span["page_number"] for span in packet}),
        "expected_page_in_packet": bool(on_expected) if answerable else None,
        "expected_page_polarity_in_packet": any(
            span.get("analysis_perspective") == case["expected_polarity"] for span in on_expected)
        if answerable else None,
    }


def expected_page_exclusions(diagnostics: dict[str, Any], expected_pages: list[int]) -> dict[str, int]:
    pages = set(expected_pages)
    counts = Counter(f"{row['filter']}:{row['reason']}" for row in diagnostics.get("filter_exclusions") or []
        if row["page_number"] in pages)
    return dict(sorted(counts.items()))


def summarize_dev(rows: list[dict[str, Any]]) -> dict[str, Any]:
    answerable = [row for row in rows if row["expected_page_in_packet"] is not None]
    insufficient = [row for row in rows if row["expected_page_in_packet"] is None]
    return {
        "answerable": len(answerable),
        "expected_page_in_packet": [sum(row["expected_page_in_packet"] for row in answerable), len(answerable)],
        "expected_page_polarity_in_packet": [
            sum(row["expected_page_polarity_in_packet"] for row in answerable), len(answerable)],
        "empty_packet_answerable": sum(row["packet_size"] == 0 for row in answerable),
        "insufficient": len(insufficient),
        "insufficient_packet_sizes": [row["packet_size"] for row in insufficient],
    }


def gold_unit_result(unit: dict[str, Any], packet: list[dict[str, Any]]) -> dict[str, Any]:
    return {"case": unit["case"], "unit": unit["unit"], "page_number": unit["page_number"],
        "in_packet": any(unit_matches(span, unit) for span in packet)}


def summarize_units(rows: list[dict[str, Any]]) -> dict[str, Any]:
    cases = {row["case"] for row in rows}
    hit_cases = {row["case"] for row in rows if row["in_packet"]}
    return {"units_in_packet": [sum(row["in_packet"] for row in rows), len(rows)],
        "cases_with_any_unit": [len(hit_cases), len(cases)]}
