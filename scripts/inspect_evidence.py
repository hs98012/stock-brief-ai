#!/usr/bin/env python3
"""Read-only candidate audit. Never imports/invokes generation or embedding providers."""
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import text
from app.database import SessionLocal
from app.document_candidates import document_candidates
from app.evidence_facts import grounded_card
from app.models import Document, Page


def inspect(db):
    for document in db.query(Document).order_by(Document.company_name, Document.published_at):
        pages = {page.page_number: page.final_text for page in db.query(Page).filter(
            Page.document_id == document.id)}
        rows = document_candidates(db, document.id)
        counts = Counter()
        for row in rows:
            assert row['document_id'] == document.id
            assert pages[row['page_number']][row['char_start']:row['char_end']] == row['quote']
            assert row['source_chunk_ids']
            card = grounded_card(row, row['analysis_perspective'])
            if card:
                counts[row['analysis_perspective']] += 1
                counts[f"{row['analysis_perspective']}_page_{row['page_number']}"] += 1
        exclusions = Counter(row['exclusion_reason'] for row in rows if row['quality_status'] != 'valid')
        print(document.company_name, document.published_at, dict(counts), 'excluded=', dict(exclusions))


if __name__ == '__main__':
    with SessionLocal() as db:
        if db.bind.dialect.name == 'postgresql':
            db.execute(text('SET TRANSACTION READ ONLY'))
        else:
            db.execute(text('PRAGMA query_only = ON'))
        inspect(db)
        db.rollback()
