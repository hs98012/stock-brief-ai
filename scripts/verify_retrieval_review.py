#!/usr/bin/env python3
"""Verify artifacts against a PDF-reviewed retrieval judgment; never call a model.
This checks reproducibility, not an independent automated semantic adjudication.
Changed artifacts require a fresh human source review, not relaxed assertions.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
review = json.loads((ROOT / 'evals/retrieval-reviewed.json').read_text())
artifacts = ROOT / 'evals/results/retrieval'
for name, digest in review['artifacts'].items():
    assert hashlib.sha256((artifacts / name).read_bytes()).hexdigest() == digest, f'Review is stale: {name}'
before = json.loads((artifacts / 'before.json').read_text())
after = json.loads((artifacts / 'after.json').read_text())
assert before['fixture_sha256'] == after['fixture_sha256'] == review['fixture_sha256']
b = {c['id']: c for c in before['cases']}
a = {c['id']: c for c in after['cases']}
for key in review['retained_case_units']:
    assert [(r['chunk_id'], r['quote']) for r in b[key]['results']] == [
        (r['chunk_id'], r['quote']) for r in a[key]['results']], f'Retained judgment must be re-reviewed: {key}'
fact = review['new_hit']
matching_cases = [c for c in after['cases'] if any(fact in r['table_evidence'] for r in c['results'])]
assert len(matching_cases) == 1
assert not any(fact['quote'] in r['quote'] for r in b[matching_cases[0]['id']]['results'])
assert {span['role'] for span in fact['source_spans']} == {'title', 'unit', 'columns', 'metric', 'row'}
assert fact['source_chunk_ids'] and fact['period'] == fact['column_name']
assert len(review['retained_case_units']) == review['before']['total']
assert review['after']['total'] == review['before']['total'] + 1
print(f"PDF-reviewed evidence recall@5: {review['before']['total']}/{review['before']['denominator']} -> "
      f"{review['after']['total']}/{review['after']['denominator']}")
print('Generation not evaluated; staged revisions remain inactive.')
