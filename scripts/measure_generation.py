#!/usr/bin/env python3
"""Generation faithfulness evaluation on evals/fixtures (plan step 6, dev 기준).

Calls the running analysis API once per case (default execution_mode LOCAL_ONLY), judges each
case with the existing app.evaluation.evaluate_case, then checks every citation against the DB
with read-only SELECTs. Writes into a new dated folder and refuses to reuse an existing one.
"""
import argparse
import hashlib
import json
import subprocess
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))
from sqlalchemy import text  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.evaluation import DocumentSelector, evaluate_case, match_document, validate_fixture  # noqa: E402
from app.generation_metrics import (  # noqa: E402
    classify_outcome, reevaluate_row, refusal_outcome, response_citation_report, summarize_generation)
from app.models import Chunk, Page  # noqa: E402
from evaluate import request_json  # noqa: E402

LABEL = "dev 기준"


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _run_case(api: str, document_id: str, case: dict, timeout: float) -> dict:
    payload = {"document_id": document_id, "question": case["question"]}
    try:
        response = request_json("POST", f"{api}/api/v1/analyses", payload, timeout)
        trace = request_json("POST", f"{api}/internal/evaluations/analysis-trace", payload, timeout)
        return {"response": response, "trace": trace, "result": evaluate_case(case, response, trace)}
    except Exception as exc:  # recorded per case; provider errors are separated in classify_outcome
        result = {"id": case["id"], "question": case["question"], "expected_polarity": case["expected_polarity"],
            "passed": False, "checks": {}, "failures": ["request_error"], "error": str(exc)}
        return {"response": None, "trace": None, "result": result}


def _collect(args: argparse.Namespace, out: Path) -> list[dict]:
    api = args.api_base_url.rstrip("/")
    documents = request_json("GET", f"{api}/api/v1/documents", None, args.timeout)["items"]
    rows = []
    for path in sorted(args.fixtures.glob("*.json")):
        fixture = validate_fixture(json.loads(path.read_text(encoding="utf-8")))
        document = match_document(documents, DocumentSelector(**fixture["document"]))
        if document is None:
            raise SystemExit(f"{path.name}: 일치하는 업로드 문서가 없습니다. 1회 실행 조건이 깨지므로 중단합니다.")
        for case in fixture["cases"]:
            row = {"fixture": path.stem, "document_id": document["id"], "case_id": case["id"],
                "expected_polarity": case["expected_polarity"], **_run_case(api, document["id"], case, args.timeout)}
            with (out / "cases.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            result = row["result"]
            print(f"{'PASS' if result['passed'] else 'FAIL'} {path.stem}/{case['id']} "
                f"failures={result['failures']} stage={(result.get('diagnostics') or {}).get('stage')} "
                f"{result.get('error', '')}", flush=True)
            rows.append(row)
    return rows


def _document_index(db, document_id: str) -> tuple[dict[int, Page], dict[str, Chunk]]:
    doc_id = uuid.UUID(document_id)
    pages = {page.page_number: page for page in db.query(Page).filter(Page.document_id == doc_id)}
    chunks = {str(chunk.id): chunk for chunk in db.query(Chunk).filter(Chunk.document_id == doc_id)}
    return pages, chunks


def _score_row(row: dict, pages: dict, chunks: dict) -> dict:
    response, result = row["response"], row["result"]
    return {"fixture": row["fixture"], "case_id": row["case_id"], "expected_polarity": row["expected_polarity"],
        "outcome": classify_outcome(result), "failures": result["failures"], "error": result.get("error"),
        "stage": (result.get("diagnostics") or {}).get("stage"),
        "generation_model": response.get("generation_model") if response else None,
        "final_provider": ((response or {}).get("execution") or {}).get("final_provider"),
        "refusal": refusal_outcome(row["expected_polarity"], response) if response else None,
        "citations": response_citation_report(response, pages, chunks) if response else None}


def _score(rows: list[dict]) -> list[dict]:
    with SessionLocal() as db:
        if db.bind.dialect.name == "postgresql":
            db.execute(text("SET TRANSACTION READ ONLY"))
        indexes = {doc_id: _document_index(db, doc_id) for doc_id in {row["document_id"] for row in rows}}
        scored = [_score_row(row, *indexes[row["document_id"]]) for row in rows]
        db.rollback()
    return scored


def _summary_markdown(run: dict, summary: dict, scored: list[dict]) -> str:
    validity, refusal = summary["citation_validity"], summary["refusal"]
    lines = [f"# 생성 근거 충실도 평가 ({LABEL})", "",
        f"- run_id: `{run['run_id']}`, commit `{run['commit']}` (worktree_dirty={run['worktree_dirty']})",
        f"- 관측 provider/model: {run['observed_generation']}",
        f"- 시각(UTC): {run['started_at']} ~ {run['finished_at']}",
        "- fixtures는 dev셋과 3문항이 겹치고 튜닝 사용 여부가 확인 안 됐다. 일반화 성능이 아니다.", "",
        f"- citation 유효율: {validity['valid']}/{validity['total']} (rate={validity['rate']}), "
        f"citation이 있는 케이스 {validity['cases_with_citations']}개 중 전부 유효 {validity['cases_all_valid']}개",
        f"- 근거 부족 케이스 올바른 거절: {refusal['insufficient_correct']}/{refusal['insufficient_evaluated']}",
        f"- 답변 가능 케이스 잘못된 거절: {refusal['answerable_false_refusals']}/{refusal['answerable_evaluated']}",
        f"- 요청 오류로 제외: {refusal['excluded_request_errors']}", f"- 결과 분포: {summary['outcomes']}", "",
        "| fixture | case | 기대 | 결과 | stage | failures |", "|---|---|---|---|---|---|"]
    lines += [f"| {row['fixture']} | {row['case_id']} | {row['expected_polarity']} | {row['outcome']} | "
        f"{row['stage']} | {', '.join(row['failures'])} |" for row in scored]
    return "\n".join(lines) + "\n"


def _start_run(args: argparse.Namespace) -> dict:
    return {"run_id": str(uuid.uuid4()), "label": LABEL, "started_at": _now(), "commit": _git("rev-parse", "HEAD"),
        "worktree_dirty": bool(_git("status", "--porcelain")), "api_base_url": args.api_base_url,
        "execution_mode": "LOCAL_ONLY", "fixtures_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(args.fixtures.glob("*.json"))}}


def _fixture_cases(fixtures: Path, expected_sha256: dict[str, str]) -> dict[tuple[str, str], dict]:
    """Load the run's fixtures; refuse when any file differs from the hashes recorded in run.json."""
    cases = {}
    for name, digest in expected_sha256.items():
        path = fixtures / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise SystemExit(f"{path} 의 SHA-256이 run.json과 다릅니다. 재채점하지 않습니다.")
        fixture = validate_fixture(json.loads(path.read_text(encoding="utf-8")))
        cases.update({(path.stem, case["id"]): case for case in fixture["cases"]})
    return cases


def _rescore(out: Path, fixtures: Path, name: str) -> int:
    """Re-judge saved cases.jsonl with the current evaluate_case and DB citation checks; never calls the API."""
    report_path, summary_path = out / f"report-{name}.json", out / f"summary-{name}.md"
    if report_path.exists() or summary_path.exists():
        raise SystemExit(f"{report_path} 가 이미 있습니다. 덮어쓰지 않습니다.")
    saved_run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    cases = _fixture_cases(fixtures, saved_run["fixtures_sha256"])
    rows = [json.loads(line) for line in (out / "cases.jsonl").read_text(encoding="utf-8").splitlines() if line]
    rows = [reevaluate_row(row, cases[(row["fixture"], row["case_id"])]) for row in rows]
    run = {**saved_run, "rescored_at": _now(), "rescore_commit": _git("rev-parse", "HEAD"),
        "rescore_worktree_dirty": bool(_git("status", "--porcelain"))}
    scored = _score(rows)
    summary = summarize_generation(scored)
    _write_json(report_path, {"run": run, "summary": summary, "cases": scored})
    summary_path.write_text(_summary_markdown(run, summary, scored), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, default=ROOT / "evals" / "fixtures")
    parser.add_argument("--api-base-url", default="http://localhost:8001")
    parser.add_argument("--timeout", type=float, default=630)
    parser.add_argument("--output-dir", type=Path,
        default=ROOT / "evals" / "results" / f"generation-faithfulness-{date.today():%Y%m%d}")
    parser.add_argument("--rescore", type=Path, metavar="RUN_DIR",
        help="저장된 cases.jsonl을 현재 판정 코드와 DB citation 검증으로 다시 채점 (API 재호출 없음)")
    parser.add_argument("--rescore-name", default="rescored",
        help="재채점 결과 파일 이름(report-<name>.json, summary-<name>.md). 기존 파일은 덮어쓰지 않는다")
    args = parser.parse_args()
    if args.rescore:
        return _rescore(args.rescore, args.fixtures, args.rescore_name)
    out = args.output_dir
    if out.exists():
        raise SystemExit(f"{out} 가 이미 있습니다. 기존 결과를 덮어쓰지 않습니다.")
    out.mkdir(parents=True)
    run = _start_run(args)
    _write_json(out / "run.json", run)
    scored = _score(_collect(args, out))
    summary = summarize_generation(scored)
    run = {**run, "finished_at": _now(), "observed_generation": sorted(
        {f"{row['final_provider']}/{row['generation_model']}" for row in scored if row["generation_model"]})}
    _write_json(out / "run.json", run)
    _write_json(out / "report.json", {"run": run, "summary": summary, "cases": scored})
    (out / "summary.md").write_text(_summary_markdown(run, summary, scored), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    print(f"결과 저장: {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
