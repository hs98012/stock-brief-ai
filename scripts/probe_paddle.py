#!/usr/bin/env python3
"""Read-only PP-Structure probe; stdout is raw JSON, never a score."""
import json
import sys
from pathlib import Path
import fitz
import httpx
ROOT=Path(__file__).resolve().parents[1]
source=json.loads((ROOT/'evals/audit-documents.json').read_text())[int(sys.argv[1])]
page=fitz.open(ROOT/'holdout-v1'/source['filename'])[int(sys.argv[2])-1]
pix=page.get_pixmap(matrix=fitz.Matrix(3,3),alpha=False)
response=httpx.post('http://ocr-worker:8090/parse',content=pix.tobytes('png'),
                    headers={'Content-Type':'image/png'},timeout=600)
response.raise_for_status()
print(json.dumps(response.json(),ensure_ascii=False))
