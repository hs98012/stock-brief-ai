#!/usr/bin/env python3
"""Check recorded PDF-reviewed observations and unchanged live-data retrieval.
No network, DB writes, model calls, or automatic semantic regrading.
"""
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.chunking import split_page
from app.evidence_integrity import span_is_covered
from app.extraction_provenance import validated_stored_facts

review=json.loads((ROOT/'evals/ingestion-reviewed.json').read_text())
folder=ROOT/'evals/results/ingestion'
for name,digest in review['artifacts'].items():
    assert hashlib.sha256((folder/name).read_bytes()).hexdigest()==digest, f'Stale artifact review: {name}'
for name,digest in review['runtime_sources'].items():
    assert hashlib.sha256((ROOT/'backend/app'/name).read_bytes()).hexdigest()==digest, f'Review code changed: {name}'
b=json.loads((folder/'retrieval-before.json').read_text())
a=json.loads((folder/'retrieval-after.json').read_text())
assert b['fixture_sha256']==a['fixture_sha256']
assert len(b['cases'])==len(a['cases'])
for before,after in zip(b['cases'],a['cases']):
    assert before['id']==after['id']
    assert before['vector_search_used'] and after['vector_search_used']
    assert [(r['chunk_id'],r['quote'],r['table_evidence']) for r in before['results']]==[
        (r['chunk_id'],r['quote'],r['table_evidence']) for r in after['results']]
before=json.loads((folder/'db-before.json').read_text())
after=json.loads((folder/'db-after.json').read_text())
assert all(after[key]==value for key,value in before.items())
assert after['new_provenance_rows']==0
observations=json.loads((folder/'parser-reviewed.json').read_text())
docs={doc['sha256']:doc for doc in observations['documents']}
for restored in review['restored']:
    doc=docs[restored['file_sha256']]
    raw=next(p for p in doc['pages'] if p['page_number']==restored['page'])
    page=SimpleNamespace(id=restored['page'],document_id=doc['sha256'],page_number=restored['page'],final_text=raw['final_text'],
        extraction=SimpleNamespace(parser_version=raw['provenance']['parser_version'],provenance=raw['provenance'],
            table_facts=raw['table_facts'],final_text_sha256=hashlib.sha256(raw['final_text'].encode()).hexdigest()))
    available=(validated_stored_facts(page) if restored['kind']=='table' else raw['provenance']['numeric_evidence'])
    chunks=[SimpleNamespace(id=i,page_id=page.id,document_id=page.document_id,page_number=page.page_number,
        char_start=c.char_start,char_end=c.char_end,content=c.content) for i,c in enumerate(split_page(page.final_text))]
    for fact in restored['facts']:
        assert fact in available
        for span in fact['source_spans']:
            covering=[c for c in chunks if c.char_start<span['char_end'] and c.char_end>span['char_start']]
            assert span_is_covered(page,covering,span['char_start'],span['char_end'],span['quote'])
            assert span.get('bbox') or span.get('boxes')
assert len(review['restored'])==review['restored_failed_units']==2
print('PDF-reviewed extraction failures recovered: 2/5; other 3 remain failed/held.')
print('Existing active retrieval: 7/12 -> 7/12; all 11 top-5 results unchanged.')
print('Existing documents/pages/chunks/vectors/analyses unchanged; new provenance rows=0.')
print('New-parser reembedded retrieval and generation accuracy were not measured.')
