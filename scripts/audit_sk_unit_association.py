#!/usr/bin/env python3
"""Read-only offline SK unit diagnosis. Counterfactuals never enter the index/pack."""
import argparse
from copy import deepcopy
import hashlib
import inspect
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'backend'), str(ROOT/'scripts')]
from audit_unseen_table import thaw_rows
from audit_unit_precision import replay
from app import spatial_tables as spatial
from app.evidence_bundle import requirements_for
from app.evidence_integrity import span_is_covered
from app.extraction_provenance import validated_stored_facts
from app.index_admission import dependency_groups
from app.page_layout import area, overlap
from app.paddle_tables import decode_tables
from app.primitive_graph import primitive_graph, comparison_candidates
from app.structured_cells import extract_cell_facts, literal_units, row_groups, _baseline_aligned, _column_aligned
from app.table_evidence import verified_table_candidates
from app.unit_validation import UNIT, located, validate_unit


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def geometry(a, b):
    return dict(row_overlap=max(0, min(a[3],b[3])-max(a[1],b[1]))/max(1,min(a[3]-a[1],b[3]-b[1])),
        column_overlap=max(0,min(a[2],b[2])-max(a[0],b[0]))/max(1,min(a[2]-a[0],b[2]-b[0])),
        baseline_distance=abs(a[3]-b[3]), baseline_aligned=_baseline_aligned(a,b),
        column_aligned=_column_aligned({'bbox':a},{'bbox':b}),
        a_contains_b=a[0]<=b[0] and a[1]<=b[1] and a[2]>=b[2] and a[3]>=b[3],
        b_contains_a=b[0]<=a[0] and b[1]<=a[1] and b[2]>=a[2] and b[3]>=a[3])


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--output', type=Path, required=True)
    args=cli.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    directory=ROOT/'evals/results/paddle'
    inputs=[directory/'extraction-holdout-index-release2-20261002.json',
        directory/'graph-regression-holdout-run1-20261002.json', ROOT/'evals/holdout-cases.json',
        directory/'composite-unit-samsung-final-20261009.json',
        directory/'composite-unit-verification-final-20261009.json',
        directory/'samsung-geometry-audit-20261009.json']
    hashes={str(p):digest(p) for p in inputs}
    production={str(p):digest(p) for base in ('backend/app','frontend/app')
                for p in (ROOT/base).rglob('*') if p.is_file()}
    gold=next(c for c in json.loads(inputs[2].read_text()) if c['id']=='holdout-sk-compound-01')
    index=json.loads(inputs[0].read_text())['cases'][gold['id']]['index']
    frozen=next(c for c in json.loads(inputs[1].read_text())['cases'] if c['id']==gold['id'])
    rows,pages=thaw_rows(index)
    page=pages[2]; text=page.final_text; pro=page.extraction.provenance
    words=pro['selected_words']; tables=pro['native_tables']+pro['paddle_tables']
    table=next(t for t in tables if any(c['text']=='영업이익' for c in t['cells']))
    def memberships(box):
        return [dict(table_index=t.get('index'), row=c['row'], column=c['column'],
            rowspan=c.get('rowspan',1), colspan=c.get('colspan',1), text=c['text'],bbox=c['bbox'],
            cell_id=f"p2:paddle:{t.get('index')}:r{c['row']}:c{c['column']}",
            overlap_ratio=overlap(c['bbox'],box)/max(1,area(box)))
            for t in tables for c in t['cells'] if overlap(c['bbox'],box)/max(1,area(box))>.8]
    observations=[]
    spatial_facts=spatial.extract_spatial_facts(text,words,2,observations=observations)
    declaration=next(w for w in words if spatial._units(w)==['원','조원','%','%pt'])
    target=[o for o in observations if o['metric']=='영업이익']
    assert len(target)==9
    # Observe the unmodified function's actual locals at its decision point.
    source,start=inspect.getsourcelines(__import__('app.structured_cells',fromlist=['_cell_topology'])._cell_topology)
    decision=start+next(i for i,line in enumerate(source) if line.strip()=='if len(chosen) != 1:')
    trace_records=[]
    def trace(frame,event,arg):
        if event=='line' and frame.f_code.co_name=='_cell_topology' and frame.f_lineno==decision:
            loc=frame.f_locals
            if loc.get('label',{}).get('text')=='영업이익':
                trace_records.append(dict(period=loc['period']['text'], facet=loc['header']['text'],
                    value=loc['value']['text'], value_span=loc['value'], metric_span=loc['label'],
                    row=loc['row_index'], column=loc['cell']['column'],
                    buckets={k:deepcopy(loc[k]) for k in ('local','row_units','column_units','table_units','chosen')},
                    predicate='len(chosen) == 1', result=len(loc['chosen'])==1, actual=len(loc['chosen'])))
        return trace
    previous=sys.gettrace()
    association=[]
    try:
        sys.settrace(trace)
        structured=extract_cell_facts(text,words,tables,2,association_audit=association)
    finally:
        sys.settrace(previous)
    assert len(trace_records)==6 and all(r['actual']==0 for r in trace_records)
    candidates=[]
    for number,match in enumerate(UNIT.finditer(declaration['text']),1):
        a=declaration['char_start']+match.start(); b=declaration['char_start']+match.end()
        span=located(text,words,a,b)
        candidates.append(dict(id=f'declared-unit-{number}',raw_unit_text=match.group(),
            canonical_unit=match.group().replace(' ',''), semantic_unit=match.group().replace(' ',''),
            source_span=span, bbox=span['bbox'], row=0, column=0,
            cell_id=None, diagnostic_cell_id=f"p2:paddle:{table.get('index')}:r0:c0",
            raw_declaration=declaration, bbox_granularity='shared recognized text region; no per-unit character bbox',
            page=2, topology=memberships(span['bbox']), scope='table-level declaration in merged header cell',
            ownership_id=None, context_id=None, unit_primitive_id=None,
            ids_note='cell_id is a diagnostic coordinate label; no production unit/ownership ID exists',
            header=True, table_level=True, parser_source=declaration['source'],
            source_verified=text[a:b]==match.group() and span is not None,
            association_verified=False, unit_dependency_verified=False,
            verification_status='literal declaration observed; metric/value binding unresolved',
            eligible_whole_word_unit=literal_units(declaration)))
    assert len(candidates)==4
    value_matrix=[]
    for obs in target:
        spans={s['role']:s for s in obs['source_spans']}
        metric,value,header=(spans[k] for k in ('metric','value','columns'))
        units=spatial._units(declaration)
        amounts=[u for u in units if u in spatial.MONEY]
        rates=[u for u in units if u in {'%','%pt'}]
        explicit=[w for w in ({'text':metric['quote']},{'text':header['quote']}) if spatial._units(w)]
        rate_branch=bool(spatial.RATE.search(metric['quote']) or spatial.RATE_COLUMN.search(header['quote']))
        value_matrix.append(dict(period=obs['period'],facet=obs['column_name'],value=obs['value'],
            source_spans=spans,metric_membership=memberships(metric['bbox']),value_membership=memberships(value['bbox']),
            header_membership=memberships(header['bbox']), associated_unit=None, unit_source=None,
            scope=None, ownership=None, approved=False,
            confidence=dict(metric=metric.get('confidence'),value=value.get('confidence'),declaration=declaration['confidence']),
            proof='source spans/topology only; no unit association proof',
            unit_resolution=spatial._unit({'text':metric['quote']},{'text':header['quote']},{'text':value['quote']},declaration),
            predicates=dict(explicit_single=len(explicit)==1,percent_suffix=value['quote'].endswith('%'),
                percent_point_suffix=value['quote'].endswith('%p'),rate_branch=rate_branch,
                candidate_subset=rates if rate_branch else amounts,unique_subset=len(rates if rate_branch else amounts)==1),
            candidates=[dict(id=c['id'],unit=c['canonical_unit'],scope=c['scope'],ownership_id=None,
                metric_geometry=geometry(metric['bbox'],c['source_span']['bbox']),
                value_geometry=geometry(value['bbox'],c['source_span']['bbox']),
                header_geometry=geometry(header['bbox'],c['source_span']['bbox']),
                topology=c['topology'],associated=False) for c in candidates]))
    assert all(v['unit_resolution'] is None for v in value_matrix)
    excluded=[]
    for word in words:
        if word is declaration or not UNIT.search(word['text']):continue
        excluded.append(dict(word=word,membership=memberships(word['bbox']),
            in_target_table=table['bbox'][0]<=word['bbox'][0]<=table['bbox'][2] and
                table['bbox'][1]-25<=word['bbox'][1]<=table['bbox'][3],
            reason=('regex-only incidental text match' if not spatial._units(word) and not literal_units(word)
                    and '원' not in word['text'] and '%' not in word['text'] else
                    'outside target table; separate valuation table or chart'),scope='other table/chart'))
    counterfactual=[]
    original=spatial._unit
    for policy,forced in [('first_unit','원'),('force_table_amount','조원')]:
        try:
            spatial._unit=lambda row,col,value,decl: (forced,decl,'DIAGNOSTIC_UNVERIFIED_FORCED')
            simulated=spatial.extract_spatial_facts(text,words,2)
        finally:
            spatial._unit=original
        simulated=[f for f in simulated if any(s['role']=='unit' and s['char_start']==declaration['char_start'] for s in f['source_spans'])]
        checks=[dict(metric=f['metric'],period=f['period'],facet=f['column_name'],value=f['value'],forced_unit=f['unit'],
            production_spatial_valid=spatial.spatial_fact_valid(f),
            production_unit_validation=validate_unit(f,text,words,())) for f in simulated]
        counterfactual.append(dict(policy=policy,diagnostic_only=True,synthetic_unverified_count=len(checks),
            target=[c for c in checks if c['metric']=='영업이익'],
            incompatible_examples=[c for c in checks if spatial.RATE.search(c['metric']) or spatial.RATE_COLUMN.search(c['facet'])][:6],
            production_accepted_count=sum(c['production_spatial_valid'] and c['production_unit_validation']['approved'] for c in checks),
            note='No graph/admission/retrieval/pack called with simulated facts; this is unsafe pre-gate construction only'))
    counterfactual.append(dict(policy='nearest_unit',unique=False,
        distances_identical=True,reason='All four units share one OCR region bbox; a nearest choice requires an arbitrary tie-break'))
    graph=primitive_graph(page);groups=dependency_groups(page)
    search=replay(rows,frozen['search'],gold['question'])
    valid=validated_stored_facts(page)
    assert not [f for f in valid if f['metric']=='영업이익']
    assert not [f for f in graph['nodes'] if f['metric']=='영업이익']
    assert not search['coverage_complete'] and search['evidence_pack']==[]
    page_rows=[c for c,p,_ in rows if p.id==page.id]
    admitted={c['id']:span_is_covered(page,page_rows,c['source_span']['char_start'],
        c['source_span']['char_end'],c['source_span']['quote']) for c in candidates}
    raw=pro['paddle_structure'];sx=pro['page_size'][0]/raw['width'];sy=pro['page_size'][1]/raw['height']
    decoded=decode_tables(raw,sx,sy)
    assert decoded==pro['paddle_tables']
    pdf=ROOT/'holdout-v1'/gold['filename'];pdf_proof=dict(path=str(pdf),present=pdf.exists(),expected_sha256=gold['pdf_sha256'])
    if pdf.exists():
        pdf_proof['sha256']=digest(pdf);assert pdf_proof['sha256']==gold['pdf_sha256']
    comparisons=[]
    for case in json.loads(inputs[1].read_text())['cases']:
        if case['id']==gold['id']:continue
        other_index=json.loads(inputs[0].read_text())['cases'][case['id']]['index']
        _,other_pages=thaw_rows(other_index)
        comparisons.extend(dict(case_id=case['id'],metric=f['metric'],period=f['period'],unit=f['unit'],
            value=f['value'],validation=validate_unit(f,p.final_text,p.extraction.provenance['selected_words'],
                () if f.get('verification') in {'coordinate_aligned','spatial_multilevel_grid'} else
                p.extraction.provenance.get('native_tables',[])+p.extraction.provenance.get('paddle_tables',[])))
            for p in other_pages.values() for f in validated_stored_facts(p) if f['metric']=='영업이익')
    samsung=json.loads(inputs[3].read_text());verifier=json.loads(inputs[4].read_text())
    assert hashes=={str(p):digest(p) for p in inputs}
    assert production=={str(p):digest(Path(p)) for p in production}
    out=dict(case_id=gold['id'],question=gold['question'],gold=gold,requirements=requirements_for(gold['question']),
        calls=dict(db_write=False,ocr=False,embedding=False,llm=False,migration=False),source_hashes=hashes,
        production_hashes_before=production,production_unchanged=True,pdf=pdf_proof,
        native_word_count=len(pro['native_words']),native_tables=pro['native_tables'],raw_decode_equal=True,
        table=table,unit_candidates=candidates,excluded_page_unit_regions=excluded,value_matrix=value_matrix,
        structured_actual_trace=trace_records,structured_association_audit=association,
        rebuilt_structured_count=len(structured),rebuilt_spatial_count=len(spatial_facts),
        unresolved_observations=observations,stored_unresolved_exact_equal=observations==pro['unresolved_cell_observations'],
        first_failure=dict(classification='B. MULTIPLE_UNIT_CANDIDATES',secondary=['F. MIXED_UNIT_TABLE','C. UNIT_SCOPE_AMBIGUOUS'],
            structured=dict(function='literal_units → _cell_topology',line=decision,
                false_predicate='UNITS.fullmatch(canonical) for entire mixed declaration; then len(chosen) == 1',
                canonical='원,조원,%,%pt',chosen_count=0),
            spatial=dict(function='_unit → extract_spatial_facts',false_predicate='len(amounts) == 1',
                amounts=['원','조원'],actual_count=2,return_value=None)),
        chain=dict(validated_target_facts=0,graph_target_nodes=0,target_dependency_groups=[g for g in groups if g['metric_raw']=='영업이익'],
            raw_unit_span_chunk_coverage=admitted,comparison_candidates=len(comparison_candidates(page,requirements_for(gold['question']))),
            verified_table_candidates=len(verified_table_candidates(rows,gold['question'])),search=search,
            break_stage='A. source association; not dependency admission',
            narrative_trace=[dict(**d,page=1,content=c.content)
                for d in frozen['search']['diagnostics']['chunks'] for c,p,_ in rows
                if str(c.id)==d['chunk_id'] and p.page_number==1 and
                any(term in c.content for term in ('AMD','NVIDIA','MI455X','Rubin'))]),
        topology_note='Unique declaration cell r0/c0 rowspan=2; metric r6/c0; New/Old r6/c1,c2. No unit-to-row mapping edge.',
        counterfactuals=counterfactual,kia_successful_unit_proofs=comparisons,
        samsung_comparison=dict(strict_pass=verifier['strict_pass'],unit_matrix=verifier['unit_matrix'],
            coverage=samsung['after']['coverage_complete'],geometry=verifier['paddle_geometry'],
            legacy_literal_component_list_match=verifier['legacy_literal_component_list_match']),
        existing_pass_comparisons=json.loads((directory/'samsung-geometry-audit-20261009.json').read_text())['pass_chain_comparisons'])
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(out,ensure_ascii=False,default=str,indent=2)+'\n')
    print(json.dumps(dict(candidates=len(candidates),eligible_whole_word_units=0,target_pairs=len(value_matrix),
        structured_trace=len(trace_records),first_spatial_predicate='len(amounts) == 1: 2 != 1',
        coverage=search['coverage_complete'],production_unchanged=True),ensure_ascii=False))


if __name__=='__main__':
    main()
