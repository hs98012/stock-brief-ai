#!/usr/bin/env python3
"""Re-derive fact spans from immutable OCR observations; no OCR, DB or model calls.
Useful for testing reading-order/column changes against exactly the same pixels
and recognized words. Input/output files must differ. The source PDF hash is checked.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.layout_tables import extract_layout_facts
from app.numeric_evidence import extract_numeric_evidence

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('observations',type=Path)
args=parser.parse_args()
result=json.loads(args.observations.read_text())
result['observation_cache_sha256']=hashlib.sha256(args.observations.read_bytes()).hexdigest()
result['derivation_code_sha256']={name:hashlib.sha256((ROOT/'backend/app'/name).read_bytes()).hexdigest()
                                  for name in ('layout_tables.py','numeric_evidence.py')}
for doc in result['documents']:
    assert hashlib.sha256((ROOT/'holdout-v1'/doc['filename']).read_bytes()).hexdigest()==doc['sha256']
    for page in doc['pages']:
        text,pro=page['final_text'],page['provenance']
        page['table_facts']=extract_layout_facts(text,pro['selected_words'],page['page_number'],pro['unsafe_spans'])
        pro['numeric_evidence']=extract_numeric_evidence(text,pro['selected_words'],page['page_number'],pro['unsafe_spans'])
        pro['table_fact_count']=len(page['table_facts'])
print(json.dumps(result,ensure_ascii=False,indent=2))
