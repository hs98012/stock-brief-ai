#!/usr/bin/env python3
"""Read-only offline provenance audit. No PDF extraction or service calls.

Replays stored hybrid ranks; writes only a new diagnostic JSON specified by CLI.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'scripts')]
from app.chunking import structured_spans
from app.evidence_bundle import _fact_spans, requirements_for
from app.evidence_integrity import chunk_matches_page, span_is_covered
from app.evidence_requirements import fact_requirement_match
from app.fact_fusion import PARSER_VERSION
from app.fused_index import searchable
from app.metric_annotations import annotation_spans, annotation_valid
from app.primitive_graph import comparison_candidates, comparison_fact_valid
from app.structured_cells import extract_cell_facts
from app.table_evidence import verified_table_candidates
from audit_unit_precision import replay


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--output', type=Path, required=True)
    args = cli.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    directory = ROOT / 'evals/results/paddle'
    names = ['graph-new-observations-20261002.json', 'graph-new-search-20261002.json',
             'query-scope-hyundai-final-20261008.json', 'query-scope-final-20261008.json']
    hashes = {n: digest(directory / n) for n in names}
    production = {str(p.relative_to(ROOT)): digest(p) for p in (ROOT / 'backend/app').glob('*.py')}
    data = {n: json.loads((directory / n).read_text()) for n in names}
    case_id = 'new-hyundai-mixed-pair'
    case = next(c for c in data[names[0]]['cases'] if c['id'] == case_id)
    frozen = next(c for c in data[names[1]]['cases'] if c['id'] == case_id)
    prior = data[names[2]]
    question = frozen['question']
    assert question == prior['query']
    document = NS(id=uuid5(NAMESPACE_URL, case['pdf_sha256']), filename='',
                  company_name='', stock_code=None, issuer='', published_at=None,
                  document_type='broker_report')
    page = NS(id=uuid5(document.id, str(case['page'])), document_id=document.id,
              page_number=case['page'], final_text=case['final_text'],
              extraction=NS(parser_version=PARSER_VERSION,
                  final_text_sha256=hashlib.sha256(case['final_text'].encode()).hexdigest(),
                  provenance=deepcopy(case['provenance']), table_facts=[]))
    pro = page.extraction.provenance
    tables = pro.get('native_tables', []) + pro.get('paddle_tables', [])
    rebuilt = extract_cell_facts(page.final_text, pro['selected_words'], tables, page.page_number)
    page.extraction.table_facts = [f for f in case['table_facts']
        if f.get('verification') != 'structured_primitive_cell'] + rebuilt
    rows = []
    for s in structured_spans(page.final_text, pro):
        chunk = NS(id=uuid5(page.id, f'{s.char_start}:{s.char_end}'), page_id=page.id,
                   document_id=document.id, page_number=page.page_number,
                   char_start=s.char_start, char_end=s.char_end, content=s.content, section_title=None)
        rows.append((chunk, page, document))
    trace = {c['chunk_id']: c for c in frozen['search']['diagnostics']['chunks']}
    assert set(trace) == {str(c.id) for c, _, _ in rows}
    assert all(chunk_matches_page(c, page) and
               (c.char_start, c.char_end) == (trace[str(c.id)]['char_start'], trace[str(c.id)]['char_end'])
               for c, _, _ in rows)
    requirements = requirements_for(question)
    comparisons = comparison_candidates(page, requirements)
    assert json.loads(json.dumps(comparisons, default=str)) == prior['comparisons']
    search = replay(rows, frozen['search'], question)
    current = next(c for c in data[names[3]]['challenge_set'] if c['id'] == case_id)
    assert search['evidence_pack'] == current['search']['evidence_pack'] == []
    assert search['coverage_complete'] is current['coverage_complete'] is False
    pool = []
    for c, _, _ in rows:
        rank = trace[str(c.id)]
        bm, vec = rank['bm25_rank'], rank['vector_rank']
        pool.append(dict(chunk_id=str(c.id), page=page.page_number,
            span=[c.char_start, c.char_end], quote=c.content,
            index_segments=[s for s in pro['index_segments']
                if c.char_start < s['char_end'] and c.char_end > s['char_start']],
            searchable=searchable(c, page), **{k: rank[k] for k in ('bm25_rank', 'vector_rank', 'rrf_rank')},
            bm25_score=None, vector_score=None,
            score_status='raw scores not stored in frozen diagnostic; no new retrieval',
            rrf_score=sum(1 / (60 + r) for r in (bm, vec) if r and r <= 20),
            in_frozen_retrieval_pool=bool(rank['rrf_rank']),
            in_selector_pool=bool(rank['rrf_rank'] and rank['rrf_rank'] <= 20)))
    base = next(f for f in comparisons if f['period'] == '2022')
    primitives = base['comparison_derivation']['primitive_cells']
    spans = base['source_spans']
    wanted = [('연결', [s for s in spans if s['role'] == 'metric_context']),
              ('영업이익률', [s for s in spans if s['role'] == 'metric']),
              ('%', [s for s in spans if s['role'] == 'unit']),
              ('2022', [s for s in spans if s['role'] == 'period']),
              ('6.9', [s for s in spans if s['role'] == 'value']),
              ('2023', [s for s in spans if s['role'] == 'comparison_columns']),
              ('9.3', [s for s in spans if s['role'] == 'comparison_value'])]
    matrix = []
    for label, source_spans in wanted:
        details = []
        for s in source_spans:
            covering = [c for c, _, _ in rows if c.char_start < s['char_end'] and c.char_end > s['char_start']]
            covered = span_is_covered(page, covering, s['char_start'], s['char_end'], s['quote'])
            bbox = s['bbox']; x, y = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
            cells = [dict(source='stored native table', table_index=t['index'],
                          row=cell['row'], column=cell['column'], text=cell['text'], bbox=cell['bbox'])
                     for t in pro['native_tables'] for cell in t['cells']
                     if cell['bbox'][0] <= x <= cell['bbox'][2] and cell['bbox'][1] <= y <= cell['bbox'][3]]
            chunks = [dict(chunk_id=str(c.id), local_span=[s['char_start']-c.char_start, s['char_end']-c.char_start],
                           **{k: trace[str(c.id)][k] for k in ('bm25_rank','vector_rank','rrf_rank')})
                      for c in covering]
            details.append(dict(source_span=s, source_exists=page.final_text[s['char_start']:s['char_end']] == s['quote'],
                structured_cells=cells, admitted_index_segments=[i for i in pro['index_segments']
                    if i['char_start'] < s['char_end'] and i['char_end'] > s['char_start']],
                chunk_covered=covered, chunks=chunks))
        all_covered = all(d['chunk_covered'] for d in details)
        retrieved = all(any(trace[c['chunk_id']]['rrf_rank'] for c in d['chunks']) for d in details)
        matrix.append(dict(evidence=label, page=page.page_number, details=details,
            table_id=base['table_id'], row_id=base['row_id'], row_group_id=base['row_group_id'],
            context_id=base['metric_context_ownership']['context_membership']['context_id'],
            ownership_id=base['metric_context_ownership']['ownership_id'],
            primitive_ids=[f['cell_fact_id'] for f in primitives],
            chunk_covered=all_covered, frozen_candidate_included=retrieved,
            selected_pack_included=False, source_requirement_recognized=True,
            pack_requirement_recognized=False, coverage_bit=False,
            first_break='B. CHUNK_MISSING' if not all_covered else 'C. FROZEN_CANDIDATE_MISSING'))
    validations = []
    missing = []
    for fact in comparisons:
        requirement = next(r for r in requirements if r['period'] == fact['period'])
        matched, checks = fact_requirement_match(requirement, fact)
        validations.append(dict(requirement=requirement, period=fact['period'], value=fact['value'],
            primitive_id=fact['cell_fact_id'], graph=fact['graph_comparison'],
            ownership_id=fact['metric_context_ownership']['ownership_id'],
            annotation_valid=annotation_valid(fact, page, requirement),
            graph_valid=comparison_fact_valid(fact, page), requirement_matched=matched,
            checks=checks, pack_spans_valid=bool(_fact_spans(page, fact, table=True, requirement=requirement))))
        for s in [*fact['source_spans'], *annotation_spans(fact)]:
            covering = [c for c, _, _ in rows if c.char_start < s['char_end'] and c.char_end > s['char_start']]
            if not span_is_covered(page, covering, s['char_start'], s['char_end'], s['quote']):
                missing.append(dict(period=fact['period'], span=s))
    assert all(v['requirement_matched'] and v['pack_spans_valid'] and v['graph_valid'] and
               v['annotation_valid'] for v in validations)
    assert not verified_table_candidates(rows, question)
    assert hashes == {n: digest(directory / n) for n in names}
    assert production == {str(p.relative_to(ROOT)): digest(p) for p in (ROOT / 'backend/app').glob('*.py')}
    output = dict(mode='offline frozen-rank replay; source cell rederivation in memory only',
        calls=dict(pdf=False, ocr=False, embedding=False, llm=False, db=False),
        source_hashes=hashes, production_hashes=production, production_unchanged=True,
        case_id=case_id, pdf_sha256=case['pdf_sha256'], final_text_sha256=page.extraction.final_text_sha256,
        page_id=str(page.id), document_id=str(document.id), page=page.page_number, question=question,
        source_of_truth='stored native table / extracted spans / offline observation; original PDF not inspected',
        frozen_fact_summary=[{k:f.get(k) for k in ('metric','period','unit','value','char_start','char_end','source')}
                             for f in case['table_facts']],
        frozen_primitive_count=len(pro['primitive_cells']), rebuilt_cell_fact_count=len(rebuilt),
        index_segments=pro['index_segments'], frozen_chunks=pool, provenance_matrix=matrix,
        requirement_validation=validations, missing_chunk_spans=missing,
        retrieval_limits=dict(candidate_limit=20, rrf_k=60, presentation_top_k=5, pack_limit=5),
        verified_table_candidate_count=0, selected_pack=search['evidence_pack'],
        selection=search['diagnostics']['selection'], coverage_complete=search['coverage_complete'],
        first_failure_layer='1. chunk construction 문제', first_break='B. CHUNK_MISSING',
        root_cause='frozen index_segments omit verified metric/context/unit/value/annotation source spans')
    args.output.write_text(json.dumps(output, ensure_ascii=False, default=str, indent=2) + '\n')
    print(json.dumps(dict(first_break=output['first_break'], chunks=len(rows),
        searchable=sum(c['searchable'] for c in pool), evidence=[(m['evidence'],m['first_break']) for m in matrix],
        coverage_complete=search['coverage_complete']), ensure_ascii=False))


if __name__ == '__main__':
    main()
