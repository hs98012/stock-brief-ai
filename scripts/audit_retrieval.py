#!/usr/bin/env python3
"""Read-only retrieval audit. Never imports generation or analysis endpoints.
Run inside the backend environment with the repository mounted at /workspace.
Only /api/embed (bge-m3 query embeddings) may be called, never /api/generate.
"""
import argparse
import hashlib
import json
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from sqlalchemy import text
from app.database import SessionLocal
from app.embeddings import OllamaEmbeddingProvider
from app.models import Document
from app.search import SearchFilters, hybrid_search


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', action='store_true')
    args = parser.parse_args()
    fixture = ROOT / 'evals/audit-cases.json'
    output = {'fixture_sha256': hashlib.sha256(fixture.read_bytes()).hexdigest(),
              'read_only': True, 'generation_called': False, 'baseline': args.baseline, 'cases': []}
    provider = OllamaEmbeddingProvider()
    with SessionLocal() as db:
        db.execute(text('SET TRANSACTION READ ONLY'))
        # Exact scan: keep the pre-existing analysis HNSW stability workaround.
        db.execute(text('SET LOCAL enable_indexscan = off'))
        db.execute(text('SET LOCAL enable_bitmapscan = off'))
        for case in json.loads(fixture.read_text()):
            doc = db.query(Document).filter(Document.company_name == case['company_name'],
                Document.published_at == date.fromisoformat(case['published_at'])).one()
            started = time.monotonic()
            result = hybrid_search(db, case['question'], 5, SearchFilters(document_id=doc.id),
                                   provider, rerank=not args.baseline, diagnostics=True)
            output['cases'].append({'id': case['id'], 'question': case['question'],
                'seconds': round(time.monotonic()-started, 4), 'results': result.results,
                'diagnostics': result.diagnostics, 'vector_search_used': result.vector_search_used,
                'vector_error': result.vector_search_unavailable_reason})
        db.rollback()
    print(json.dumps(output, ensure_ascii=False, default=str, indent=2))


if __name__ == '__main__':
    main()
