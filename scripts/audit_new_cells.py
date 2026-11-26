#!/usr/bin/env python3
"""Frozen extra TABLE holdout; page parsing only, no DB ingestion or generation."""
import argparse
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

import fitz
from audit_unseen_table import ROOT, digest, snapshot, SessionLocal
from app.fused_extraction import extract_page
from app.extraction_provenance import validated_stored_facts
from app.fact_fusion import PARSER_VERSION


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--cases',type=Path,required=True)
    cli.add_argument('--pdf-dir',type=Path,required=True)
    cli.add_argument('--output',type=Path,required=True)
    cli.add_argument('--observations',type=Path,help='Revalidate identical pixels/OCR without calling the worker')
    args=cli.parse_args()
    if args.output.exists():raise FileExistsError(args.output)
    frozen=digest(args.cases); cases=json.loads(args.cases.read_text())
    output=dict(cases_sha256=frozen,parser_version=PARSER_VERSION,generator_called=False,
        production_source_hashes={p.name:digest(p) for p in (ROOT/'backend/app').glob('*.py')},cases=[])
    cached=json.loads(args.observations.read_text()) if args.observations else None
    if cached and cached['cases_sha256']!=frozen:raise ValueError('Frozen table cases changed')
    if cached:output['observation_artifact_sha256']=digest(args.observations)
    with SessionLocal() as db:output['active_before']=snapshot(db);db.rollback()
    for case in cases:
        pdf=args.pdf_dir/case['filename']
        if digest(pdf)!=case['pdf_sha256']:raise ValueError('PDF hash mismatch')
        if cached:
            from app.structured_cells import extract_cell_facts,merge_cell_facts,unit_compatible
            from app.fact_fusion import fuse_candidates
            old=next(c for c in cached['cases'] if c['id']==case['id'])
            if old['pdf_sha256']!=case['pdf_sha256']:raise ValueError('Observation PDF changed')
            pro=old['provenance'];text=old['final_text']
            cells=extract_cell_facts(text,pro['selected_words'],
                pro['native_tables']+pro['paddle_tables'],case['page'])
            existing=[f for f in old['table_facts'] if f.get('verification')!='structured_primitive_cell']
            facts,_=fuse_candidates([f for f in merge_cell_facts(existing,cells) if unit_compatible(f['metric'],f['unit'])])
            extracted=SimpleNamespace(final_text=text,provenance=pro,table_facts=facts)
        else:
            with fitz.open(pdf) as document, tempfile.TemporaryDirectory() as temp:
                extracted=extract_page(document[case['page']-1],case['page'],pdf,Path(temp))
        page=SimpleNamespace(page_number=case['page'],final_text=extracted.final_text,
            extraction=SimpleNamespace(parser_version=PARSER_VERSION,
                final_text_sha256=__import__('hashlib').sha256(extracted.final_text.encode()).hexdigest(),
                provenance=extracted.provenance,table_facts=extracted.table_facts))
        valid=validated_stored_facts(page); results=[]
        for gold in case['cells']:
            compact=lambda x:''.join(str(x or '').split())
            found=[f for f in valid if all(compact(f.get(k))==compact(gold[k])
                   for k in ('row_label','period','unit','value'))]
            results.append(dict(expected=gold,primitive_hit=bool(found),matches=found))
        comparison_hit=(not case.get('comparison_required') or any(
            f.get('comparison_cell') and f['comparison_cell']['period']==case['cells'][0]['period']
            and f['comparison_cell']['value']==case['cells'][0]['value']
            for f in results[-1]['matches']))
        output['cases'].append(dict(id=case['id'],pdf_sha256=case['pdf_sha256'],page=case['page'],
            strict_pass=all(r['primitive_hit'] for r in results) and comparison_hit,
            primitive_results=results,derived_comparison_hit=comparison_hit,
            final_text=page.final_text,provenance=extracted.provenance,table_facts=valid,
            failure_stage=None if all(r['primitive_hit'] for r in results) and comparison_hit else
                'fact_construction' if all(r['primitive_hit'] for r in results) else 'header_or_unit_association'))
    with SessionLocal() as db:output['active_after']=snapshot(db);db.rollback()
    if output['active_before']!=output['active_after'] or digest(args.cases)!=frozen:
        raise ValueError('Active data or fixed table cases changed')
    with args.output.open('x') as f:json.dump(output,f,ensure_ascii=False,default=str)
    print('new_table_strict='+str(sum(c['strict_pass'] for c in output['cases']))+'/'+str(len(cases)))


if __name__=='__main__':main()
