#!/usr/bin/env python3
"""Offline scope proof audit over an existing observation; no external calls."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'backend'), str(ROOT/'scripts')]
from app.evidence_requirements import table_requirements
from app.metric_annotations import annotate_metric_facts, annotation_spans
from app.primitive_graph import comparison_candidates
from app.structured_cells import extract_cell_facts
from app.search import rank_rows
from app.chunking import structured_spans
from app.fact_fusion import PARSER_VERSION


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--observations', type=Path, required=True)
    cli.add_argument('--case', required=True)
    cli.add_argument('--query', required=True)
    cli.add_argument('--output', type=Path, required=True)
    args = cli.parse_args()
    if args.output.exists(): raise FileExistsError(args.output)
    case = next(c for c in json.loads(args.observations.read_text())['cases'] if c['id'] == args.case)
    doc = NS(id=uuid5(NAMESPACE_URL, case['pdf_sha256']), filename=case.get('filename', ''),
        company_name='', stock_code=None, issuer='', published_at=None, document_type='broker_report')
    p = NS(id=uuid5(doc.id, str(case['page'])), document_id=doc.id, page_number=case['page'],
        final_text=case['final_text'], extraction=NS(parser_version=PARSER_VERSION,
            final_text_sha256=hashlib.sha256(case['final_text'].encode()).hexdigest(),
            provenance=deepcopy(case['provenance']), table_facts=[]))
    pro = p.extraction.provenance
    p.extraction.table_facts = extract_cell_facts(p.final_text, pro['selected_words'],
        pro.get('native_tables', [])+pro.get('paddle_tables', []), p.page_number)
    req = table_requirements(args.query)
    canonical = req[0]['metric']['surface']
    facts = [f for f in annotate_metric_facts(p, p.extraction.table_facts)
             if f.get('metric_identity', {}).get('canonical_label') == canonical]
    candidates = {}
    for f in facts:
        identity = f['metric_identity']
        candidates.setdefault(identity['raw_span']['char_start'], dict(raw=f['metric'],
            canonical=identity['canonical_label'], row=f['cell_geometry']['row'], unit=f['unit'],
            identity=identity, values={} ))['values'][f['period']] = f['value']
    rows = []
    for span in structured_spans(p.final_text, pro):
        c = NS(id=uuid5(p.id, f'{span.char_start}:{span.char_end}'), page_id=p.id, document_id=doc.id,
            page_number=p.page_number, char_start=span.char_start, char_end=span.char_end,
            content=span.content, section_title=None, embedding=None)
        rows.append((c, p, doc))
    result = rank_rows(rows, args.query, 5, NS(available=False, unavailable_reason='offline fixture'))
    from app.evidence_integrity import span_is_covered
    from app.table_evidence import verified_table_candidates
    comparisons = comparison_candidates(p, req)
    from app.evidence_bundle import _fact_spans
    from app.primitive_graph import comparison_fact_valid
    from app.metric_annotations import annotation_valid
    validations = [dict(period=f['period'],
        annotation_valid=annotation_valid(f, p, r), graph_valid=comparison_fact_valid(f, p),
        source_pack_spans_valid=bool(_fact_spans(p, f, table=True, requirement=r)))
        for f in comparisons for r in req if r['period'] == f['period']]
    missing = [dict(period=f['period'], span=s) for f in comparisons
        for s in [*f['source_spans'], *annotation_spans(f)]
        if not span_is_covered(p, [c for c, _, _ in rows if c.char_start < s['char_end']
            and c.char_end > s['char_start']], s['char_start'], s['char_end'], s['quote'])]
    output = dict(mode='offline fixture, lexical presentation; no embedding/LLM/OCR/DB',
        observation_sha256=hashlib.sha256(args.observations.read_bytes()).hexdigest(),
        pdf_sha256=case['pdf_sha256'], query=args.query, requirements=req,
        candidates=list(candidates.values()), comparisons=comparisons, chain_validation=validations, missing_chunk_spans=missing,
        verified_table_candidate_count=len(verified_table_candidates(rows, args.query)),
        coverage_complete=result.coverage_complete, evidence_pack=result.evidence_pack)
    args.output.write_text(json.dumps(output, ensure_ascii=False, default=str, indent=2)+'\n')
    print(dict(coverage_complete=result.coverage_complete, candidates=len(candidates),
               comparisons=len(output['comparisons'])))


if __name__ == '__main__': main()
