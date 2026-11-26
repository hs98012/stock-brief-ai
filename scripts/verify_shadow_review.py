#!/usr/bin/env python3
"""Verify fixed, source-reviewed evidence units. Not a general semantic grader."""
import hashlib
import json
import re
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
raw = ROOT/'evals/results/shadow/run.json'
review = json.loads((ROOT/'evals/shadow-reviewed.json').read_text())
assert hashlib.sha256(raw.read_bytes()).hexdigest() == review['artifact_sha256'], 'Review stale'
x = json.loads(raw.read_text())
assert x['active_before'] == x['active_after']
previous = {c['id']: c for c in json.loads((ROOT/'evals/results/ingestion/retrieval-after.json').read_text())['cases']}
cases = {c['id']: c for c in x['cases']}
for case in cases.values():
    assert case['active']['vector_search_used'] and case['shadow']['vector_search_used']
    assert [(r['chunk_id'], r['quote'], r['table_evidence']) for r in case['active']['results']] == [
        (r['chunk_id'], r['quote'], r['table_evidence']) for r in previous[case['id']]['results']]
pages = {str(p['id']): p for rev in x['revisions'] for p in rev['pages']}
chunks = {str(c['id']): c for rev in x['revisions'] for c in rev['chunks']}
for rev in x['revisions']:
    assert rev['status'] == 'ready' and rev['embedded_count'] == len(rev['chunks'])
for unit in review['units']:
    if not unit['shadow_hit'] or unit['case'].startswith('old-'):
        continue
    results = cases[unit['case']]['shadow']['results']
    r = next(r for r in results if r['chunk_id'] == unit['chunk_id'])
    assert r['rank'] <= 5 and r['page_number'] == unit['page_number']
    chunk = chunks[r['chunk_id']]; page = pages[str(chunk['page_id'])]
    assert page['final_text'][chunk['char_start']:chunk['char_end']] == r['quote'] == chunk['content']
    if 'table' in unit:
        fact = next(f for f in r['table_evidence'] if all(
            re.sub(r'\s+', '', str(f[k])) == v for k, v in unit['table'].items()))
        for span in fact['source_spans']:
            assert page['final_text'][span['char_start']:span['char_end']] == span['quote']
            assert span.get('bbox') and span.get('source')
    elif 'numeric_values' in unit:
        facts = [f for f in page['provenance']['numeric_evidence'] if f['value'] in unit['numeric_values']]
        assert {f['value'] for f in facts} == set(unit['numeric_values'])
        for fact in facts:
            assert fact['period'] == '2분기' and fact['metric'] == '순이익' and fact['status'] == 'forecast'
            assert chunk['char_start'] <= fact['char_start'] < fact['char_end'] <= chunk['char_end']
            assert page['final_text'][fact['char_start']:fact['char_end']] == fact['quote']
            for span in fact['source_spans']:
                assert page['final_text'][span['char_start']:span['char_end']] == span['quote']
    else:
        compact = re.sub(r'\s+', '', r['quote'])
        assert all(token in compact for token in unit['literal_conditions'])
assert len(review['units']) == 12
before = sum(u['active_hit'] for u in review['units'])
after = sum(u['shadow_hit'] for u in review['units'])
assert (before, after) == (7, 8)
print(f'Active recall@5 {before}/12; shadow cohort {after}/12 (2 unchanged Samsung controls + 6/10 shadow).')
print('Active data/top-5 unchanged; shadow regression: posco-forecast. Target 9/12 not met.')
