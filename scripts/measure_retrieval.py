#!/usr/bin/env python3
"""Read-only retrieval metrics on the dev set (evals/audit-cases.json + evals/pinned-gold.json).

Calls hybrid_search only; never imports generation. Ollama is used for query
embeddings only. Prints one JSON report with hit@1/3/5, unit recall@5 and MRR@5,
at evidence level and page-only level, plus run provenance.
"""
import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from sqlalchemy import text  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.embeddings import OllamaEmbeddingProvider  # noqa: E402
from app.models import Document  # noqa: E402
from app.retrieval_metrics import CUTOFF, first_match_rank, summarize, summarize_by_group  # noqa: E402
from app.search import SearchFilters, char_bigram_tokenize, hybrid_search, tokenize  # noqa: E402

CASES_PATH = ROOT / "evals/audit-cases.json"
GOLD_PATH = ROOT / "evals/pinned-gold.json"
# mode -> hybrid_search options. "hybrid_rrf_with_promotion" is the default /api/v1/search path.
MODES = {
    "bm25": {"rerank": False},
    "vector": {"rerank": False, "use_bm25": False},
    "hybrid_rrf": {"rerank": False},
    "hybrid_rrf_with_promotion": {},
}
TOKENIZERS = {"regex": tokenize, "char_bigram": char_bigram_tokenize}


class _VectorDisabled:
    """Keeps the real provider's identity but reports vector search unavailable (BM25-only)."""

    def __init__(self, provider) -> None:
        self.provider_name, self.model, self.dimensions = provider.provider_name, provider.model, provider.dimensions
        self.available, self.unavailable_reason = False, "ablation: vector disabled"

    def embed(self, texts):
        raise AssertionError("BM25-only mode must not embed.")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def _provenance(provider: OllamaEmbeddingProvider, mode: str, tokenizer: str, bm25_weight: float = 1.0,
                cases_path: Path = CASES_PATH, gold_path: Path = GOLD_PATH) -> dict:
    return {"measured_at": datetime.now(timezone.utc).isoformat(), "commit": _git("rev-parse", "HEAD"),
            "worktree_dirty": bool(_git("status", "--porcelain")),
            "cases_file": cases_path.name, "gold_file": gold_path.name,
            "cases_sha256": _sha256(cases_path), "gold_sha256": _sha256(gold_path),
            "embedding_provider": provider.provider_name, "embedding_model": provider.model,
            "top_k": CUTOFF, "mode": mode, "search_options": MODES[mode], "bm25_tokenizer": tokenizer, "bm25_weight": bm25_weight,
            "vector_scan": "exact",
            "read_only": True, "generation_called": False}


def _run_case(db, case: dict, units: list[dict], provider, options: dict) -> dict:
    document = db.query(Document).filter(Document.company_name == case["company_name"],
        Document.published_at == date.fromisoformat(case["published_at"])).one()
    started = time.monotonic()
    execution = hybrid_search(db, case["question"], CUTOFF, SearchFilters(document_id=document.id), provider, **options)
    seconds = round(time.monotonic() - started, 4)
    results = execution.results
    return {"id": case["id"], "seconds": seconds, "vector_search_used": execution.vector_search_used,
            "vector_error": execution.vector_search_unavailable_reason,
            "retrieved": [{"rank": r["rank"], "page_number": r["page_number"], "chunk_id": str(r["chunk_id"])}
                          for r in results],
            "case_rank": first_match_rank(results, units) if units else None,
            "case_rank_page_only": first_match_rank(results, units, page_only=True) if units else None,
            "unit_ranks": [first_match_rank(results, [unit]) for unit in units],
            "unit_ranks_page_only": [first_match_rank(results, [unit], page_only=True) for unit in units]}


def _metrics(rows: list[dict], suffix: str) -> dict:
    answerable = [row for row in rows if row["unit_ranks"]]
    return summarize([row["case_rank" + suffix] for row in answerable],
                     [rank for row in answerable for rank in row["unit_ranks" + suffix]])


def _metrics_by_type(rows: list[dict], groups: dict[str, str], suffix: str) -> dict:
    answerable = [row for row in rows if row["unit_ranks"]]
    return summarize_by_group({row["id"]: row["case_rank" + suffix] for row in answerable},
                              {row["id"]: row["unit_ranks" + suffix] for row in answerable}, groups)


def _load_query_types(path: Path, cases_path: Path) -> dict[str, str]:
    labels = json.loads(path.read_text())
    if labels.get("dev_cases_sha256") != _sha256(cases_path):
        raise SystemExit(f"{path}: dev_cases_sha256 does not match {cases_path.name}")
    return {label["case_id"]: label["query_type"] for label in labels["labels"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=sorted(MODES), default="hybrid_rrf_with_promotion")
    parser.add_argument("--tokenizer", choices=sorted(TOKENIZERS), default="regex")
    parser.add_argument("--bm25-weight", type=float, default=1.0, help="RRF weight on the BM25 term (default 1.0)")
    parser.add_argument("--query-types", type=Path, help="evals/query-types-dev.json: also report metrics per type")
    parser.add_argument("--cases", type=Path, default=CASES_PATH, help="cases file (default: dev set)")
    parser.add_argument("--gold", type=Path, default=GOLD_PATH, help="gold units file (default: dev set)")
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text())
    gold = json.loads(args.gold.read_text())["units"]
    groups = (_load_query_types(args.query_types, args.cases) if args.query_types
              else {case["id"]: case["query_type"] for case in cases} if all("query_type" in case for case in cases)
              else None)
    mode = args.mode
    options = {**MODES[mode], "bm25_tokenizer": TOKENIZERS[args.tokenizer], "bm25_weight": args.bm25_weight}
    ollama = OllamaEmbeddingProvider()
    provider = _VectorDisabled(ollama) if mode == "bm25" else ollama
    report = _provenance(ollama, mode, args.tokenizer, args.bm25_weight, args.cases, args.gold)
    with SessionLocal() as db:
        db.execute(text("SET TRANSACTION READ ONLY"))
        db.execute(text("SET LOCAL enable_indexscan = off"))
        db.execute(text("SET LOCAL enable_bitmapscan = off"))
        rows = [_run_case(db, case, [u for u in gold if u["case"] == case["id"]], provider, options)
                for case in cases]
        db.rollback()
    report["unanswerable_cases"] = [row["id"] for row in rows if not row["unit_ranks"]]
    report["metrics_evidence"] = _metrics(rows, "")
    report["metrics_page_only"] = _metrics(rows, "_page_only")
    if groups:
        report["query_types_source"] = str(args.query_types or args.cases.name)
        report["query_types_sha256"] = _sha256(args.query_types or args.cases)
        report["metrics_by_query_type_evidence"] = _metrics_by_type(rows, groups, "")
        report["metrics_by_query_type_page_only"] = _metrics_by_type(rows, groups, "_page_only")
    report["cases"] = rows
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
