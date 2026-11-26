#!/usr/bin/env python3
"""Read-only analysis-packet inclusion measurement (plan step 13). Never calls generation.

Runs collect_analysis_evidence (the analysis packet builder) per case inside a READ ONLY
transaction and checks whether gold evidence reaches the packet:
- dev (evals/fixtures/): page level — any packet span on an expected page.
- test-v2 (evals/test-v2-cases.json + test-v2-gold.json): unit level — a packet span on the
  unit's page holds every literal condition. Final check only; needs --confirm-final.
Ollama is used for query embeddings only. Refuses to reuse an output folder.
"""
import argparse
import hashlib
import json
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from sqlalchemy import text  # noqa: E402

from app.analysis_retrieval import collect_analysis_evidence  # noqa: E402
from app.database import SessionLocal, engine, require_postgresql  # noqa: E402
from app.embeddings import get_embedding_provider  # noqa: E402
from app.evaluation import DocumentSelector, match_document, validate_fixture  # noqa: E402
from app.models import Document  # noqa: E402
from app.packet_metrics import (  # noqa: E402
    check_split_allowed, dev_case_result, expected_page_exclusions, gold_unit_result, summarize_dev, summarize_units)

FIXTURES_DIR = ROOT / "evals" / "fixtures"
TEST_CASES_PATH = ROOT / "evals" / "test-v2-cases.json"
TEST_GOLD_PATH = ROOT / "evals" / "test-v2-gold.json"
DEFAULT_TOP_K = 10  # AnalysisRequest.top_k default
LABELS = {"dev": "dev 기준 (기대 페이지 단위)",
    "test-v2": "test-v2 최종 확인 (gold 단위, test-v2 두 번째 사용: 첫 사용은 10단계 검색 측정)"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _document_dicts(db) -> list[dict]:
    return [{"id": str(doc.id), "filename": doc.filename, "company_name": doc.company_name,
        "published_at": doc.published_at.isoformat(), "file_hash": doc.file_hash,
        "document_type": getattr(doc.document_type, "value", doc.document_type)} for doc in db.query(Document)]


def _packet(db, document_id: str, question: str, top_k: int, provider) -> tuple[list[dict], dict]:
    diagnostics: dict = {}
    packet = collect_analysis_evidence(db, UUID(document_id), question, top_k, provider, diagnostics)
    return packet, diagnostics


def _measure_dev(db, provider, top_k: int) -> tuple[dict, list[dict], dict]:
    documents, rows, hashes = _document_dicts(db), [], {}
    for path in sorted(FIXTURES_DIR.glob("*.json")):
        hashes[path.name] = _sha256(path)
        fixture = validate_fixture(json.loads(path.read_text(encoding="utf-8")))
        document = match_document(documents, DocumentSelector(**fixture["document"]))
        if document is None:
            raise SystemExit(f"{path.name}: 일치하는 DB 문서가 없습니다.")
        for case in fixture["cases"]:
            packet, diagnostics = _packet(db, document["id"], case["question"], top_k, provider)
            row = {"fixture": path.stem, **dev_case_result(case, packet),
                "expected_page_exclusions": expected_page_exclusions(diagnostics, case.get("expected_pages") or []),
                "early_exit": diagnostics.get("early_exit")}
            print(f"{path.stem}/{case['id']} in={row['expected_page_in_packet']} "
                f"polarity={row['expected_page_polarity_in_packet']} packet={row['packet_size']}", flush=True)
            rows.append(row)
    return summarize_dev(rows), rows, {"fixtures_sha256": hashes}


def _measure_test(db, provider, top_k: int) -> tuple[dict, list[dict], dict]:
    cases = json.loads(TEST_CASES_PATH.read_text(encoding="utf-8"))
    units = json.loads(TEST_GOLD_PATH.read_text(encoding="utf-8"))["units"]
    by_hash = {doc["file_hash"]: doc for doc in _document_dicts(db)}
    rows = []
    for case in cases:
        document = by_hash.get(case["pdf_sha256"])
        if document is None:
            raise SystemExit(f"{case['id']}: pdf_sha256과 일치하는 DB 문서가 없습니다.")
        packet, _ = _packet(db, document["id"], case["question"], top_k, provider)
        rows += [gold_unit_result(unit, packet) for unit in units if unit["case"] == case["id"]]
    return summarize_units(rows), rows, {"cases_sha256": _sha256(TEST_CASES_PATH), "gold_sha256": _sha256(TEST_GOLD_PATH)}


def _summary_markdown(run: dict, summary: dict, rows: list[dict]) -> str:
    lines = [f"# 분석 packet 근거 포함 측정 ({run['label']})", "",
        f"- commit `{run['commit']}` (worktree_dirty={run['worktree_dirty']}), {run['measured_at']}",
        f"- embedding {run['embedding']}, top_k={run['top_k']}, 생성 호출 없음", "",
        "```json", json.dumps(summary, ensure_ascii=False, indent=2), "```", ""]
    if run["split"] == "dev":
        lines += ["| fixture | case | 기대 | 기대 페이지 | packet | 포함 | 관점 일치 | 기대 페이지 필터 제외 |",
            "|---|---|---|---|---|---|---|---|"]
        lines += [f"| {r['fixture']} | {r['case_id']} | {r['expected_polarity']} | {r['expected_pages']} | "
            f"{r['packet_size']} | {r['expected_page_in_packet']} | {r['expected_page_polarity_in_packet']} | "
            f"{r['expected_page_exclusions']} |" for r in rows]
    else:
        lines += ["| case | unit | page | 포함 |", "|---|---|---|---|"]
        lines += [f"| {r['case']} | {r['unit']} | {r['page_number']} | {r['in_packet']} |" for r in rows]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("dev", "test-v2"), default="dev")
    parser.add_argument("--confirm-final", action="store_true", help="test-v2 최종 확인 1회 실행에만 사용")
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    check_split_allowed(args.split, confirm_final=args.confirm_final)
    require_postgresql(engine)
    out = args.output_dir or ROOT / "evals" / "results" / f"analysis-packet-{args.split}-{date.today():%Y%m%d}"
    if out.exists():
        raise SystemExit(f"{out} 가 이미 있습니다. 기존 결과를 덮어쓰지 않습니다.")
    provider = get_embedding_provider()
    run = {"label": LABELS[args.split], "split": args.split, "measured_at": datetime.now(timezone.utc).isoformat(),
        "commit": _git("rev-parse", "HEAD"), "worktree_dirty": bool(_git("status", "--porcelain")),
        "top_k": args.top_k, "embedding": f"{provider.provider_name}/{provider.model}/{provider.dimensions}"}
    measure = _measure_dev if args.split == "dev" else _measure_test
    with SessionLocal() as db:
        db.execute(text("SET TRANSACTION READ ONLY"))
        summary, rows, inputs = measure(db, provider, args.top_k)
        db.rollback()
    run = {**run, **inputs, "finished_at": datetime.now(timezone.utc).isoformat()}
    out.mkdir(parents=True)
    _write_json(out / "report.json", {"run": run, "summary": summary, "cases": rows})
    (out / "summary.md").write_text(_summary_markdown(run, summary, rows), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    print(f"결과 저장: {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
