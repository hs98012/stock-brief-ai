#!/usr/bin/env python3
"""Stage immutable processing revisions from original PDFs; no DB or model calls.

Stdout is a versioned manifest. This intentionally has NO activate/delete/update
operation: unreviewed OCR and missing embeddings must never replace active DB rows.
Use /tmp for ephemeral images; raw PDF hash is checked before and after extraction.
"""
import argparse
import hashlib
import json
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
import fitz
import pytesseract
from app.chunking import split_page
from app.pdf_pipeline import extract_pdf, OCR_DPI
from app.table_evidence import extract_page_table_facts, PROCESSING_VERSION


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf-dir', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    args = parser.parse_args()
    if OCR_DPI != 300:
        raise ValueError('This revision audit requires OCR_DPI=300')
    code = b''.join((ROOT / 'backend/app' / name).read_bytes() for name in
                    ['pdf_pipeline.py', 'chunking.py', 'table_evidence.py'])
    processing = {'parser_version': 'ocr300-forced-review-v1',
                  'source_sha256': hashlib.sha256(code).hexdigest(), 'dpi': OCR_DPI,
                  'pymupdf': fitz.VersionBind, 'tesseract': str(pytesseract.get_tesseract_version()),
                  'languages': 'kor+eng', 'table_version': PROCESSING_VERSION}
    documents = []
    for source in json.loads(args.manifest.read_text()):
        pdf = args.pdf_dir / source['filename']
        digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
        if digest != source['sha256']:
            raise ValueError('Raw PDF hash mismatch')
        revision = hashlib.sha256((digest + json.dumps(processing, sort_keys=True)).encode()).hexdigest()
        pages = []
        with tempfile.TemporaryDirectory(prefix='rag-revision-') as temporary:
            for page in extract_pdf(pdf, Path(temporary), force_ocr=True):
                chunks = []
                for chunk in split_page(page.final_text):
                    chunks.append({**asdict(chunk), 'processing_version': revision,
                        'embedding': {'processing_version': revision, 'provider': 'ollama',
                                      'model': 'bge-m3', 'dimensions': 1024, 'status': 'not_created'}})
                facts = [{**fact, 'parser_processing_version': revision} for fact in
                         extract_page_table_facts(page.final_text, page.page_number)]
                pages.append({**asdict(page), 'page_image_path': None,
                              'processing_version': revision, 'chunks': chunks, 'table_facts': facts})
        if hashlib.sha256(pdf.read_bytes()).hexdigest() != digest:
            raise ValueError('Raw PDF changed during extraction')
        documents.append({'filename': pdf.name, 'raw_pdf_sha256': digest, 'revision': revision,
            'active': False, 'validation_status': 'pending_pdf_review_and_embeddings',
            'activation_eligible': False, 'pages': pages,
            'counts': {'pages': len(pages), 'chunks': sum(len(p['chunks']) for p in pages),
                       'table_facts': sum(len(p['table_facts']) for p in pages),
                       'ocr_attempted_pages': len(pages),
                       'ocr_selected_pages': sum(p['text_source'].value == 'ocr' for p in pages)}})
    print(json.dumps({'processing': processing, 'documents': documents, 'db_modified': False},
                     ensure_ascii=False, default=str, indent=2))


if __name__ == '__main__':
    main()
