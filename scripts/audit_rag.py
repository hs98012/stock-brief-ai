#!/usr/bin/env python3
"""Collect reproducible API observations; semantic judgments stay explicitly manual."""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

from evaluate import request_json


def run_case(base, document, case, timeout, retrieval_only=False):
    result = {"id": case["id"], "question": case["question"], "category": case["category"],
        "cohort": case["cohort"], "gold": case["gold"], "expected_pages": case["expected_pages"],
        "answer_correct": None, "claim_supported": None,
        "semantic_review": "원문 PDF와 응답을 사람이 대조해야 합니다."}
    page_cache = {}

    def page(number):
        if number not in page_cache:
            page_cache[number] = request_json("GET", f"{base}/api/v1/documents/{document['id']}/pages/{number}", None, timeout)
        return page_cache[number]

    for number in case["expected_pages"]:
        page(number)
    # These filters identify this report; cross-report hits are never credited.
    started = time.monotonic()
    try:
        search = request_json("POST", f"{base}/api/v1/search", {
            "query": case["question"], "top_k": 5, "ticker": document["stock_code"],
            "published_from": document["published_at"], "published_to": document["published_at"],
        }, timeout)
        result["search"] = search
        hits = {r["page_number"] for r in search["results"] if r["document_id"] == document["id"]}
        expected = set(case["expected_pages"])
        result["page_recall_at_5"] = len(hits & expected) / len(expected) if expected else None
        # Page recall alone is not evidence recall: a different chunk on the same page can match.
        result["evidence_recall_at_5"] = None
        result["evidence_recall_note"] = "gold 내용과 검색 quote의 수동 대조 필요; 페이지 일치만으로 정답 근거 성공을 판정하지 않음"
    except Exception as exc:
        result["search_error"] = str(exc)
    result["search_seconds"] = round(time.monotonic() - started, 3)
    if retrieval_only:
        result["analysis_error"] = "--retrieval-only: 생성 미실행"
        result["pages"] = page_cache
        return result
    started = time.monotonic()
    payload = {"document_id": document["id"], "question": case["question"]}
    try:
        response = request_json("POST", f"{base}/api/v1/analyses", payload, timeout)
        result["analysis"] = response
        result["analysis_seconds"] = round(time.monotonic() - started, 3)
        result["trace"] = request_json("POST", f"{base}/internal/evaluations/analysis-trace", payload, timeout)
        citations = response.get("citations", [])
        result["citation_checks"] = [{"chunk_id": c["chunk_id"], "page_number": c["page_number"],
            "page_exists": bool(page(c["page_number"])),
            "exact_stored_span": (isinstance(c.get("char_start"), int) and isinstance(c.get("char_end"), int)
                and 0 <= c["char_start"] < c["char_end"] <= len(page(c["page_number"])["final_text"])
                and page(c["page_number"])["final_text"][c["char_start"]:c["char_end"]] == c["quote"]),
            "pdf_semantic_validity": None} for c in citations]
        result["abstained"] = response["analysis_status"] == "insufficient_evidence" and not (
            response["positives"] or response["negatives"] or citations)
        result["exact_abstention"] = result["abstained"] and response["summary"] == "확인할 수 없습니다"
    except Exception as exc:
        result["analysis_error"] = str(exc)
        result["analysis_seconds"] = round(time.monotonic() - started, 3)
    result["pages"] = page_cache
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=Path("evals/audit-cases.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--api-base-url", default="http://localhost:8001")
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--only", help="Comma-separated case IDs")
    parser.add_argument("--retrieval-only", action="store_true")
    args = parser.parse_args()
    base = args.api_base_url.rstrip("/")
    cases = json.loads(args.cases.read_text())
    documents = request_json("GET", f"{base}/api/v1/documents", None, args.timeout)["items"]
    report = {"fixture_sha256": hashlib.sha256(args.cases.read_bytes()).hexdigest(), "cases": []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for case in cases:
        if args.only and case["id"] not in args.only.split(","):
            continue
        matches = [d for d in documents if d["company_name"] == case["company_name"]
            and d["published_at"] == case["published_at"]]
        if len(matches) != 1:
            row = {"id": case["id"], "skipped": "문서 식별 결과가 정확히 하나가 아닙니다."}
        else:
            row = run_case(base, matches[0], case, args.timeout, args.retrieval_only)
        report["cases"].append(row)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(case["id"], row.get("analysis_error", row.get("analysis", {}).get("analysis_status")),
            row.get("analysis_seconds"), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
