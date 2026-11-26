#!/usr/bin/env python3
"""Ingest and embed the sealed test-v2 PDFs with the current backend code.

Reads document metadata from evals/drafts/test-v2-draft.json, refuses any PDF whose
SHA-256 differs from that record, then runs the same ingest_document / embed_document
service calls as the API. Runs no search. Prints one JSON line per document.
"""
import hashlib
import io
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from starlette.datastructures import UploadFile  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.embedding_service import embed_document  # noqa: E402
from app.embeddings import OllamaEmbeddingProvider  # noqa: E402
from app.models import DocumentType  # noqa: E402
from app.service import ingest_document  # noqa: E402

DRAFT_PATH = ROOT / "evals/drafts/test-v2-draft.json"
PDF_DIR = ROOT / "test-v2"


def _ingest_one(db, record: dict, provider: OllamaEmbeddingProvider) -> dict:
    data = (PDF_DIR / record["filename"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != record["sha256"]:
        raise SystemExit(f"sha256 mismatch: {record['filename']}")
    upload = UploadFile(file=io.BytesIO(data), filename=record["filename"])
    document, duplicate = ingest_document(db, upload, record["company_name"], record["stock_code"],
                                          DocumentType.broker_report, record["issuer"],
                                          date.fromisoformat(record["published_at"]))
    run = embed_document(db, document, provider)
    db.refresh(document)
    return {"filename": record["filename"], "document_id": str(document.id), "duplicate": duplicate,
            "status": document.status.value, "embedding_status": document.embedding_status.value,
            "embedding_run": {key: value for key, value in vars(run).items() if not key.startswith("_")}}


def main() -> None:
    records = json.loads(DRAFT_PATH.read_text())["documents"]
    provider = OllamaEmbeddingProvider()
    with SessionLocal() as db:
        for record in records:
            print(json.dumps(_ingest_one(db, record, provider), ensure_ascii=False, default=str), flush=True)


if __name__ == "__main__":
    main()
