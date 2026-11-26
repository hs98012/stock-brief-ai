#!/usr/bin/env python3
"""Validate a human source-reviewed, fixed 12-unit Paddle retrieval audit."""
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
raw=Path(sys.argv[1]);review_path=Path(sys.argv[2])
review=json.loads(review_path.read_text());data=json.loads(raw.read_text())
assert hashlib.sha256(raw.read_bytes()).hexdigest()==review['artifact_sha256']
assert hashlib.sha256((ROOT/'evals/audit-cases.json').read_bytes()).hexdigest()==review['fixture_sha256']
assert data['generation_called'] is False and data['activation_available'] is False
assert data['active_before']==data['active_after']
assert data['prior_shadows_before']==data['prior_shadows_after']
cases={c['id']:c for c in data['cases']}
original=json.loads((ROOT/'evals/results/shadow/run.json').read_text())
for old in original['cases']:
    now=cases[old['id']]['active']['results']
    signature=lambda rows:[(r['chunk_id'],r['quote'],r['table_evidence']) for r in rows]
    assert signature(now)==signature(old['active']['results']), 'Active retrieval regression'
pages={p['id']:p for rev in data['revisions'] for p in rev['pages']}
chunks={c['id']:c for rev in data['revisions'] for c in rev['chunks']}
for rev in data['revisions']:
    assert rev['status']=='ready' and rev['embedded_count']==len(rev['chunks'])
    for page in rev['pages']:
        assert hashlib.sha256(page['final_text'].encode()).hexdigest()==page['final_text_sha256']
compact=lambda text:re.sub(r'\s+','',str(text))
for unit in review['units']:
    assert unit['failure_category'] in (None,'Paddle 인식 실패','표 구조 실패','읽기 순서 실패','fact 연결 실패')
    if not unit['shadow_hit']:continue
    case=cases[unit['case']]
    assert case['shadow']['vector_search_used']
    if case['scope']=='unchanged_active_control':continue
    hits=[r for r in case['shadow']['results'] if r['chunk_id'] in unit['chunk_ids']]
    assert len(hits)==len(unit['chunk_ids']) and all(r['rank']<=5 for r in hits)
    texts=[]
    for hit in hits:
        chunk=chunks[hit['chunk_id']];page=pages[chunk['page_id']]
        assert page['page_number']==unit['page_number']
        assert page['final_text'][chunk['char_start']:chunk['char_end']]==chunk['content']==hit['quote']
        texts.append(hit['quote'])
        selected=page['provenance']['selected_words']
        words=[w for w in selected if w['char_start']<chunk['char_end'] and w['char_end']>chunk['char_start']]
        assert words and all(w.get('bbox') for w in words)
        for span in page['provenance'].get('unsafe_spans',[]):
            assert not (span['char_start']<chunk['char_end'] and span['char_end']>chunk['char_start'])
    if unit.get('table'):
        fact=next(f for hit in hits for f in hit['table_evidence'] if all(
            compact(f.get(key))==compact(value) for key,value in unit['table'].items()))
        page=pages[fact['page_id']]
        assert fact['source']=='paddle_structure' and fact['source_chunk_ids']
        for span in fact['source_spans']:
            assert page['final_text'][span['char_start']:span['char_end']]==span['quote'] and span['bbox']
            assert any(w['char_start']==span['char_start'] and w['char_end']==span['char_end']
                and w['bbox']==span['bbox'] and w['source']==span['source'] for w in page['provenance']['selected_words'])
    for expected in unit.get('numeric',[]):
        fact=next(f for hit in hits for f in hit['numeric_evidence'] if all(
            compact(f.get(key))==compact(value) for key,value in expected.items()))
        page=pages[fact['page_id']]
        assert fact['source']=='paddle_structure' and fact['bbox']
        for span in fact['source_spans']:
            assert page['final_text'][span['char_start']:span['char_end']]==span['quote']
            assert span['boxes'] and 'paddle_structure' in span['sources']
    for token in unit.get('literal_conditions',[]):
        assert compact(token) in compact(' '.join(texts)), token
assert len(review['units'])==12
before=sum(u['active_hit'] for u in review['units']);after=sum(u['shadow_hit'] for u in review['units'])
print(f'Active recall@5 {before}/12; Paddle shadow recall@5 {after}/12')
print('Failures: '+', '.join(u['unit'] for u in review['units'] if not u['shadow_hit']))
