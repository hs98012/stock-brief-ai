#!/usr/bin/env python3
"""Re-derive candidates from unchanged OCR observations; never call OCR or a model."""
import hashlib
import json
import sys
from pathlib import Path
from dataclasses import asdict
import fitz
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app import pdf_pipeline
from app.fused_extraction import extract_page
source=Path(sys.argv[1]);data=json.loads(source.read_text())
data['observation_source_sha256']=hashlib.sha256(source.read_bytes()).hexdigest()
data['candidate_code_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest()
    for p in (ROOT/'backend/app').glob('*.py') if p.name in (
        'fused_extraction.py','fact_fusion.py','native_tables.py','layout_tables.py')}
for item in data['documents']:
    pdf=ROOT/'holdout-v1'/item['filename']
    assert hashlib.sha256(pdf.read_bytes()).hexdigest()==item['sha256']
    with fitz.open(pdf) as doc:
        output=[]
        for i,old in enumerate(item['pages']):
            pdf_pipeline.ocr_page=lambda *args:pdf_pipeline.OCRPage(
                old.get('ocr_text') or '', '',old['provenance']['ocr_words'])
            result=asdict(extract_page(doc[i],i+1,pdf,Path('/tmp/unused-observation-replay')))
            result['page_image_path']=None;output.append(result)
        item['pages']=output
print(json.dumps(data,ensure_ascii=False,default=str))
