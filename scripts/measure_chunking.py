#!/usr/bin/env python3
"""Read-only chunking experiment on the dev set.

Re-splits each dev document's stored page text in memory with split_page(max_chars,
overlap), embeds the new chunks with the configured Ollama model, and ranks them with
rank_rows(db=None) (exact cosine over the supplied rows, mirroring
shadow_revision.revision_rows). Nothing is written to the database. Applies only to
legacy pages (no page_extractions row); fact-fusion pages are rejected.
"""
import argparse
import json
import sys
import time
import uuid
from datetime import date
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from measure_retrieval import (CASES_PATH, GOLD_PATH, MODES, _metrics, _provenance,  # noqa: E402
                               first_match_rank)

from sqlalchemy import text  # noqa: E402

from app.chunking import split_page  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.embedding_service import BATCH_SIZE  # noqa: E402
from app.embeddings import OllamaEmbeddingProvider  # noqa: E402
from app.models import Document, Page  # noqa: E402
from app.retrieval_metrics import CUTOFF  # noqa: E402
from app.search import rank_rows  # noqa: E402

CHUNK_MODES = ("hybrid_rrf", "hybrid_rrf_with_promotion")


def _document_rows(db, document: Document, provider, max_chars: int, overlap: int) -> list[tuple]:
    pages = db.query(Page).filter(Page.document_id == document.id).order_by(Page.page_number).all()
    if any(page.extraction is not None for page in pages):
        raise ValueError(f"{document.company_name}: fact-fusion pages are not supported by this experiment")
    rows = [(SimpleNamespace(id=uuid.uuid4(), document_id=document.id, page_id=page.id,
                             page_number=page.page_number, section_title=None, content=span.content,
                             char_start=span.char_start, char_end=span.char_end), page, document)
            for page in pages for span in split_page(page.final_text, max_chars, overlap)]
    for start in range(0, len(rows), BATCH_SIZE):
        batch = rows[start:start + BATCH_SIZE]
        for (chunk, _, _), vector in zip(batch, provider.embed([row[0].content for row in batch]), strict=True):
            chunk.embedding, chunk.embedding_provider = vector, provider.provider_name
            chunk.embedding_model, chunk.embedding_dimensions = provider.model, provider.dimensions
    return rows


def _run_case(rows: list[tuple], case: dict, units: list[dict], provider, options: dict) -> dict:
    started = time.monotonic()
    execution = rank_rows(rows, case["question"], CUTOFF, provider, **options)
    results = execution.results
    return {"id": case["id"], "seconds": round(time.monotonic() - started, 4),
            "vector_search_used": execution.vector_search_used,
            "retrieved": [{"rank": r["rank"], "page_number": r["page_number"],
                           "char_start": r["chunk_char_start"], "char_end": r["chunk_char_end"]} for r in results],
            "case_rank": first_match_rank(results, units) if units else None,
            "case_rank_page_only": first_match_rank(results, units, page_only=True) if units else None,
            "unit_ranks": [first_match_rank(results, [unit]) for unit in units],
            "unit_ranks_page_only": [first_match_rank(results, [unit], page_only=True) for unit in units]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-chars", type=int, default=1200)
    parser.add_argument("--overlap", type=int, default=0)
    parser.add_argument("--mode", choices=CHUNK_MODES, default="hybrid_rrf")
    args = parser.parse_args()
    cases = json.loads(CASES_PATH.read_text())
    gold = json.loads(GOLD_PATH.read_text())["units"]
    provider = OllamaEmbeddingProvider()
    report = {**_provenance(provider, args.mode, "regex"), "vector_scan": "exact_in_memory",
              "max_chars": args.max_chars, "overlap": args.overlap, "chunk_counts": {}}
    rows_by_document: dict = {}
    with SessionLocal() as db:
        db.execute(text("SET TRANSACTION READ ONLY"))
        case_rows = []
        for case in cases:
            document = db.query(Document).filter(Document.company_name == case["company_name"],
                Document.published_at == date.fromisoformat(case["published_at"])).one()
            if document.id not in rows_by_document:
                rows_by_document[document.id] = _document_rows(db, document, provider, args.max_chars, args.overlap)
                report["chunk_counts"][f"{document.company_name} {document.published_at}"] = len(
                    rows_by_document[document.id])
            units = [unit for unit in gold if unit["case"] == case["id"]]
            case_rows.append(_run_case(rows_by_document[document.id], case, units, provider, MODES[args.mode]))
        db.rollback()
    report["unanswerable_cases"] = [row["id"] for row in case_rows if not row["unit_ranks"]]
    report["metrics_evidence"] = _metrics(case_rows, "")
    report["metrics_page_only"] = _metrics(case_rows, "_page_only")
    report["cases"] = case_rows
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
