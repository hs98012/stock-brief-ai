#!/usr/bin/env python3
"""Inactive extraction only: no database, embedding or generation calls."""
import hashlib
import json
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.pdf_pipeline import extract_pdf
from app.table_evidence import extract_page_table_facts

output = {'documents': [], 'database_modified': False, 'generation_called': False}
for source in json.loads((ROOT/'evals/audit-documents.json').read_text()):
    pdf = ROOT/'holdout-v1'/source['filename']
    assert hashlib.sha256(pdf.read_bytes()).hexdigest() == source['sha256']
    started = time.monotonic()
    with tempfile.TemporaryDirectory() as temporary:
        pages = extract_pdf(pdf, Path(temporary))
        rows = []
        for page in pages:
            row = asdict(page)
            row['page_image_path'] = None
            row['derived_legacy_table_facts'] = extract_page_table_facts(page.final_text, page.page_number)
            rows.append(row)
    output['documents'].append({**source, 'seconds': round(time.monotonic()-started, 3), 'pages': rows})
print(json.dumps(output, ensure_ascii=False, default=str, indent=2))
