#!/usr/bin/env python3
import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.evaluation import DocumentSelector, evaluate_case, match_document, validate_document_id, validate_fixture


def request_json(method: str, url: str, payload: dict[str, Any] | None, timeout: float) -> Any:
    body = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
    request = urllib.request.Request(url, data=body, method=method,
        headers={"Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:1000]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


def parse_overrides(values: list[str], fixture_count: int) -> tuple[str | None, dict[str, str]]:
    direct = None
    mapped = {}
    for value in values:
        if "=" in value:
            name, document_id = value.split("=", 1)
            mapped[name] = validate_document_id(document_id)
        else:
            if fixture_count != 1 or direct is not None:
                raise ValueError("UUID 단독 지정은 fixture가 하나일 때만 가능합니다. 여러 문서는 FIXTURE=UUID 형식을 사용하세요.")
            direct = validate_document_id(value)
    return direct, mapped


def main() -> int:
    parser = argparse.ArgumentParser(description="Stock Brief AI 다중 문서 RAG 평가")
    parser.add_argument("--fixtures", type=Path, default=ROOT / "evals" / "fixtures")
    parser.add_argument("--api-base-url", default="http://localhost:8001")
    parser.add_argument("--document-id", action="append", default=[], metavar="[FIXTURE=]UUID")
    parser.add_argument("--timeout", type=float, default=630)
    parser.add_argument("--output", type=Path, help="지정한 경우에만 JSON 결과 파일 생성")
    args = parser.parse_args()

    fixture_paths = sorted(args.fixtures.glob("*.json")) if args.fixtures.is_dir() else [args.fixtures]
    fixtures = [(path, validate_fixture(json.loads(path.read_text(encoding="utf-8")))) for path in fixture_paths]
    if not fixtures:
        parser.error("평가 fixture를 찾을 수 없습니다.")
    direct, mapped = parse_overrides(args.document_id, len(fixtures))
    documents = request_json("GET", f"{args.api_base_url.rstrip('/')}/api/v1/documents", None, args.timeout)["items"]
    report: dict[str, Any] = {"documents": [], "summary": {"passed": 0, "failed": 0, "skipped": 0}}

    for path, fixture in fixtures:
        selector = DocumentSelector(**fixture["document"])
        override = direct or mapped.get(path.stem)
        document = {"id": override} if override else match_document(documents, selector)
        document_report = {"fixture": path.name, "document": fixture["document"], "cases": []}
        if document is None:
            document_report["status"] = "skipped"
            document_report["reason"] = "일치하는 업로드 문서가 없습니다."
            report["summary"]["skipped"] += len(fixture["cases"])
            print(f"SKIP {path.name}: 일치하는 업로드 문서가 없습니다.", flush=True)
            report["documents"].append(document_report)
            continue
        document_report["status"] = "evaluated"
        for case in fixture["cases"]:
            try:
                response = request_json("POST", f"{args.api_base_url.rstrip('/')}/api/v1/analyses",
                    {"document_id": document["id"], "question": case["question"]}, args.timeout)
                trace = request_json("POST", f"{args.api_base_url.rstrip('/')}/internal/evaluations/analysis-trace",
                    {"document_id": document["id"], "question": case["question"]}, args.timeout)
                result = evaluate_case(case, response, trace)
            except Exception as exc:
                result = {"id": case["id"], "question": case["question"], "passed": False,
                    "checks": {}, "failures": ["request_error"], "error": str(exc)}
            document_report["cases"].append(result)
            key = "passed" if result["passed"] else "failed"
            report["summary"][key] += 1
            detail = "" if result["passed"] else f" ({', '.join(result['failures'])})"
            if result.get("error"):
                detail += f" - {result['error']}"
            diagnostics = result.get("diagnostics", {})
            if not result["passed"] and diagnostics:
                detail += (f" [stage={diagnostics.get('stage')}, "
                    f"candidate_pages={diagnostics.get('relevant_candidate_pages', [])}, "
                    f"generated={diagnostics.get('generated_selected_ids', [])}]")
            print(f"{key.upper():4} {path.stem}/{case['id']}{detail}", flush=True)
        report["documents"].append(document_report)
    summary = report["summary"]
    print(f"TOTAL pass={summary['passed']} fail={summary['failed']} skip={summary['skipped']}", flush=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"결과 저장: {args.output}", flush=True)
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
