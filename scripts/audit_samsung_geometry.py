#!/usr/bin/env python3
"""Offline geometry/provenance diagnosis; never changes inputs or production state."""
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
from app.chunking import structured_spans
from app.evidence_bundle import requirements_for
from app.evidence_integrity import span_is_covered
from app.evidence_requirements import fact_requirement_match
from app.fact_fusion import PARSER_VERSION
from app.page_layout import overlap, area
from app.paddle_tables import decode_tables
from app.primitive_graph import comparison_candidates, primitive_graph
from app.structured_cells import extract_cell_facts, row_groups, _column_aligned, _baseline_aligned
from app.table_evidence import verified_table_candidates
from app.unit_validation import validate_unit
from audit_unit_precision import replay


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def geometry(a, b):
    h = min(a[3]-a[1], b[3]-b[1])
    w = min(a[2]-a[0], b[2]-b[0])
    yo = max(0, min(a[3], b[3])-max(a[1], b[1]))
    xo = max(0, min(a[2], b[2])-max(a[0], b[0]))
    baseline = abs(a[3]-b[3])
    left, right = abs(a[0]-b[0]), abs(a[2]-b[2])
    yr, br, xr, cr = yo/h, baseline/h, xo/w, max(left, right)/w
    return dict(box_a=a, box_b=b, row=dict(y_overlap=yo, y_overlap_ratio=yr, baseline_distance=baseline,
        min_height=h, baseline_ratio=br, y_overlap_pass=yr >= .8, baseline_pass=br <= .2,
        passed=_baseline_aligned(a,b), overlap_delta=yr-.8, baseline_delta=br-.2),
        column=dict(x_overlap=xo, x_overlap_ratio=xr, left_boundary_difference=left,
        right_boundary_difference=right, min_width=w, boundary_ratio=cr,
        x_overlap_pass=xr >= .9, boundary_pass=cr <= .1,
        passed=_column_aligned({'bbox':a},{'bbox':b}), overlap_delta=xr-.9, boundary_delta=cr-.1))


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--output', type=Path, required=True)
    args = cli.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    directory = ROOT/'evals/results/paddle'
    names = ['graph-new-observations-20261002.json','graph-new-search-20261002.json',
             'graph-before-tables-20261002.json','offline-hybrid-regression-20261009.json',
             'offline-hybrid-reviewed-20261009.json']
    hashes = {n:digest(directory/n) for n in names}
    data = {n:json.loads((directory/n).read_text()) for n in names}
    case = next(c for c in data[names[0]]['cases'] if c['id']=='new-samsung-annual-pair')
    frozen = next(c for c in data[names[1]]['cases'] if c['id']==case['id'])
    gold = next(c for c in json.loads((ROOT/'evals/primitive-graph-unseen-cases.json').read_text())
                if c['id']==case['id'])
    pro = deepcopy(case['provenance'])
    tables = pro['native_tables']+pro['paddle_tables']
    doc = NS(id=uuid5(NAMESPACE_URL,case['pdf_sha256']),filename='',company_name='',
             stock_code=None,issuer='',published_at=None,document_type='broker_report')
    page = NS(id=uuid5(doc.id,str(case['page'])),document_id=doc.id,page_number=case['page'],
        final_text=case['final_text'],extraction=NS(parser_version=PARSER_VERSION,
        final_text_sha256=hashlib.sha256(case['final_text'].encode()).hexdigest(),
        provenance=pro,table_facts=deepcopy(case['table_facts'])))
    rows = [(NS(id=uuid5(page.id,f'{s.char_start}:{s.char_end}'),page_id=page.id,
        document_id=doc.id,page_number=page.page_number,char_start=s.char_start,
        char_end=s.char_end,content=s.content,section_title=None),page,doc)
        for s in structured_spans(page.final_text,pro)]
    requirements = requirements_for(gold['question'])
    original_audits = [dict(period=f['period'],source=f['source'],unit=f['unit'],
        unit_spans=[s for s in f['source_spans'] if s['role']=='unit'],
        validation=validate_unit(f,page.final_text,pro['selected_words'],tables))
        for f in page.extraction.table_facts if f['metric']=='영업이익']
    original_graph = primitive_graph(page)
    association = []
    rebuilt = extract_cell_facts(page.final_text,pro['selected_words'],tables,page.page_number,
                                 association_audit=association)
    page.extraction.table_facts = [f for f in case['table_facts']
        if f.get('verification')!='structured_primitive_cell'] + rebuilt
    comparisons = comparison_candidates(page,requirements)
    search = replay(rows,frozen['search'],gold['question'])
    prior = next(c for c in data[names[3]]['challenge_set'] if c['id']==case['id'])
    assert search['evidence_pack']==prior['search']['evidence_pack']
    assert not search['coverage_complete'] and not verified_table_candidates(rows,gold['question'])
    target = [a for a in association if a.get('metric_span',{}).get('quote')=='영업이익']
    t = pro['paddle_tables'][0]
    def cell(r,c):
        return next(x for x in t['cells'] if x['row']==r and x['column']==c)
    metrics = []
    for col in (2,3,4):
        metrics.append(dict(edge=f'metric → value c{col}', applicable='row',
            topology_same_row=True, **geometry(cell(2,0)['bbox'],cell(2,col)['bbox'])))
        metrics.append(dict(edge=f'period c{col} → value c{col}', applicable='column',
            topology_same_column=True, **geometry(cell(0,col)['bbox'],cell(2,col)['bbox'])))
        metrics.append(dict(edge=f'unit → value c{col}', applicable='row',
            topology_same_row=True, **geometry(cell(2,1)['bbox'],cell(2,col)['bbox'])))
    metrics.append(dict(edge='metric → unit',applicable='row',topology_same_row=True,
        **geometry(cell(2,0)['bbox'],cell(2,1)['bbox'])))
    metrics.append(dict(edge='value 2022 → value 2023',applicable='row',topology_same_row=True,
        **geometry(cell(2,3)['bbox'],cell(2,4)['bbox'])))
    span_dump = []
    for a in target:
        for role in ('metric','unit','period','value'):
            s = a[role+'_span']
            owners = [dict(table_index=tt['index'],**cc) for tt in tables for cc in tt['cells']
                if overlap(cc['bbox'],s['bbox'])/max(1,area(s['bbox']))>.8]
            span_dump.append(dict(period=a['period_span']['quote'],role=role,raw_text=s['quote'],
                bbox=s['bbox'],page=page.page_number,source=s['source'],
                source_offsets=[s['char_start'],s['char_end']],assigned_cells=owners,
                candidate_row=owners[0]['row'] if len(owners)==1 else None,
                candidate_column=owners[0]['column'] if len(owners)==1 else None,
                ownership_id=a.get('metric_context_ownership',{}).get('ownership_id'),
                context_id=a.get('metric_context_ownership',{}).get('context_membership',{}).get('context_id'),
                ownership_status='unique cell + row group; no merged context ID required',
                row_group_id=a['row_group_id']))
    # Paddle 2023 value never reaches _association: token membership fails first.
    ow = next(w for w in pro['selected_words'] if w['source']=='paddle_structure'
              and w['text']=='6.6' and 98<w['bbox'][1]<113)
    vc = cell(2,4)
    coverage = overlap(vc['bbox'],ow['bbox'])/max(1,area(ow['bbox']))
    membership = dict(word=ow,expected_cell=vc,intersection_area=overlap(vc['bbox'],ow['bbox']),
        source_area=area(ow['bbox']),ratio=coverage,required_strictly_greater_than=.8,
        delta=coverage-.8,passed=coverage>.8,
        matching_cells=[c for c in t['cells'] if overlap(c['bbox'],ow['bbox'])/max(1,area(ow['bbox']))>.8],
        production_break='_cell_topology token assignment → numbers=[] → len(numbers)!=1 → continue',
        classification=['I. SOURCE_CELL_COVERAGE_BELOW_MINIMUM'],
        excluded_classifications=['E: zero qualifying owner, not ambiguous owners',
                                 'F: source span has no multiple-cell assignment'],
        topology='D. source span extends outside predicted cell boundary')
    assert coverage <= .8
    span_dump.append(dict(role='value',period='2023년',raw_text=ow['text'],bbox=ow['bbox'],
        source=ow['source'],page=page.page_number,source_offsets=[ow['char_start'],ow['char_end']],
        assigned_cells=[],candidate_row=2,candidate_column=4,ownership_id=None,context_id=None))
    gaps = []
    for f in comparisons:
        spans=[]
        for s in f['source_spans']:
            covering=[c for c,_,_ in rows if c.char_start<s['char_end'] and c.char_end>s['char_start']]
            valid=span_is_covered(page,covering,s['char_start'],s['char_end'],s['quote'])
            spans.append(dict(span=s,covered=valid,chunks=[dict(id=str(c.id),start=c.char_start,
                end=c.char_end,quote=c.content) for c in covering]))
        gaps.append(dict(period=f['period'],value=f['value'],fact_id=f['cell_fact_id'],
            graph=f['graph_comparison'],requirement_match=fact_requirement_match(
                next(r for r in requirements if r['period']==f['period'].removesuffix('년')),f),
            source_coverage=spans,first_uncovered=next(x for x in spans if not x['covered'])))
    # Pure arithmetic counterfactual: leave code/thresholds and candidates untouched.
    risks=[]
    for c in t['cells']:
        if c['column']==4 and c['row'] in (1,2,3):
            risks.append(dict(row=c['row'],text=c['text'],bbox=c['bbox'],
                target_source_overlap=overlap(c['bbox'],ow['bbox'])/area(ow['bbox']),
                target_metric_row=geometry(cell(2,0)['bbox'],c['bbox'])['row'],
                header_column=geometry(cell(0,4)['bbox'],c['bbox'])['column'],
                topology_same_target_row=c['row']==2))
    raw = pro['paddle_structure']
    ocr=raw['overall_ocr_res']
    raw_word_box=ocr.get('rec_boxes')
    if raw_word_box is not None:
        raw_word_box=raw_word_box[ow['observation_index']]
    else:
        poly=ocr['rec_polys'][ow['observation_index']]
        raw_word_box=[min(p[0] for p in poly),min(p[1] for p in poly),
                      max(p[0] for p in poly),max(p[1] for p in poly)]
    raw_cell_box=raw['table_res_list'][0]['cell_box_list'][14]
    membership['raw_ocr_bbox_pixels']=raw_word_box
    membership['raw_cell_bbox_pixels']=raw_cell_box
    membership['raw_pixel_ratio']=overlap(raw_cell_box,raw_word_box)/area(raw_word_box)
    sx,sy=pro['page_size'][0]/raw['width'],pro['page_size'][1]/raw['height']
    decoded=decode_tables(raw,sx,sy)
    import fitz
    # decode_page_result applies even the identity derotation through fitz.Rect,
    # whose coordinates have float32 precision. Preserve that observed step.
    scaled_value_cell=deepcopy(decoded[0]['cells'][14]['bbox'])
    identity=fitz.Matrix(1,0,0,1,0,0)
    for tt in decoded:
        tt['bbox']=list(fitz.Rect(tt['bbox'])*identity)
        for cc in tt['cells']:
            cc['bbox']=list(fitz.Rect(cc['bbox'])*identity)
    assert decoded==pro['paddle_tables']
    pdf=directory/'graph-new-pdfs'/gold['filename']
    assert digest(pdf)==case['pdf_sha256']
    with fitz.open(pdf) as document:
        pdfpage=document[page.page_number-1]
        fresh=pdfpage.get_text('words')
        pdf_native=[]
        for span in gold['cells'][1]['gold_source_spans']:
            hits=[w for w in fresh if w[4]==span['quote'] and list(w[:4])==span['bbox_pdf_points']]
            pdf_native.append(dict(role=span['role'],quote=span['quote'],bbox=span['bbox_pdf_points'],
                                   exact_pdf_word_match=len(hits)==1))
        native_table_count=len(pdfpage.find_tables().tables)
        rotation=pdfpage.rotation
    # Compare passing source chains; no changes to frozen PASS fixtures.
    comparisons_pass=[]
    for name,case_id in [(names[0],'new-hyundai-mixed-pair'),(names[2],'new-period-cashflow')]:
        observed=next((x for x in data[name]['cases'] if x['id']==case_id),None)
        if observed is None:
            observed=next((x for x in data[name]['cases'] if 'posco' in x['id']),None)
        if observed is None: continue
        pp=observed['provenance']; aa=[]
        extract_cell_facts(observed['final_text'],pp['selected_words'],pp['native_tables']+
                           pp.get('paddle_tables',[]),observed['page'],association_audit=aa)
        approved=[a for a in aa if a.get('approved') and a.get('column_association_reason')]
        # Hyundai target and two distinct POSCO chains when available.
        if 'hyundai' in case_id:
            approved=[a for a in approved if a['metric_span']['quote'].startswith('영업이익률')]
        unique={}
        for a in approved:
            key=(a['metric_span']['quote'],a['period_span']['quote'],a['value_span']['quote'])
            unique.setdefault(key,a)
        for a in list(unique.values())[:3]:
            g=a['column_association_reason']
            comparisons_pass.append(dict(case_id=observed['id'],metric=a['metric_span']['quote'],
                period=a['period_span']['quote'],value=a['value_span']['quote'],
                row=geometry(g['metric_cell'],g['value_cell'])['row'],
                column=geometry(g['header_cell'],g['value_cell'])['column']))
    output=dict(case_id=case['id'],requirements=requirements,source_hashes=hashes,
        calls=dict(ocr=False,embedding=False,llm=False,db_write=False),
        original_stored_fact_audits=original_audits,
        original_graph_target_nodes=[n for n in original_graph['nodes'] if n['metric']=='영업이익'],
        source_spans=span_dump,cells=[c for c in t['cells'] if c['row']<=3],
        association_audit=target,chain_geometry=metrics,paddle_value_membership=membership,
        source_span_geometry=[dict(period=a['period_span']['quote'],source=a['metric_span']['source'],
            metric_unit=geometry(a['metric_span']['bbox'],a['unit_span']['bbox']),
            metric_value=geometry(a['metric_span']['bbox'],a['value_span']['bbox']),
            period_value=geometry(a['period_span']['bbox'],a['value_span']['bbox']),
            applicability='raw span arithmetic only; production row/column predicates use assigned cell boxes')
            for a in target],
        rebuilt_comparison_chains=gaps,search=search,
        first_current_replay_break=dict(classification='I. SOURCE_CHUNK_UNIT_DEPENDENCY_MISSING',
            function='table_evidence.verified_table_candidates',predicate='span_is_covered(...) is False',
            span=[31,34],quote='조 원',missing_literal_span=[31,32],missing_literal='조'),
        geometry_transform=dict(scale_x=sx,scale_y=sy,rotation=rotation,
            raw_value_cell=raw['table_res_list'][0]['cell_box_list'][14],
            scaled_value_cell=scaled_value_cell,
            float32_rounding_delta=[a-b for a,b in zip(vc['bbox'],scaled_value_cell)],
            raw_table_cell_to_stored_exact=True,structured_uses_stored_bbox_exact=True,
            native_table_count=native_table_count,pdf_native_words=pdf_native,
            operations='pixel → PDF point scale; identity derotation through fitz float32; no clipping/padding/row or column union'),
        counterfactual=dict(mode='arithmetic only, no monkeypatch or selection',neighbors=risks,
            risk='ignoring membership alone gives no neighboring owner; removing row ownership too admits wrong-row values'),
        pass_chain_comparisons=comparisons_pass)
    assert hashes=={n:digest(directory/n) for n in names}
    args.output.write_text(json.dumps(output,ensure_ascii=False,default=str,indent=2)+'\n')
    print(json.dumps(dict(first_break=output['first_current_replay_break'],
        paddle_membership_ratio=coverage,comparisons=len(comparisons),coverage=search['coverage_complete'],
        pass_comparisons=len(comparisons_pass)),ensure_ascii=False))


if __name__=='__main__':
    main()
