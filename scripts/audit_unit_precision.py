#!/usr/bin/env python3
"""Offline unit gate replay over immutable observations and frozen hybrid ranks.

No OCR, embedding, generator, database, or active revision is called. This is a
validation/selection replay, not a fresh retrieval or live database hash check.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
from uuid import UUID, NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'backend'), str(ROOT/'scripts')]
from app.evidence_bundle import build_evidence_pack, requirements_for
from app.extraction_provenance import validated_stored_facts
from app.fused_candidates import deduplicate_verified, verified_numeric_candidates
from app.search import reciprocal_rank_fusion
from app.table_evidence import verified_table_candidates
from app.fact_fusion import PARSER_VERSION
from app.chunking import structured_spans
from audit_unseen_table import thaw_rows, strict
from pinned_manifest import verify_manifest, code_identity
from verify_pinned_shadow import validate_binding, binding_for
from verify_evidence_bundle import evaluate


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def replay(rows, old, question):
    if not rows:
        assert not old['results'] and old['diagnostics'] is None
        return {**deepcopy(old), 'unit_audit': [], 'replay_mode': 'empty frozen index'}
    by_id = {str(c.id): (c, p, d) for c, p, d in rows}
    trace = old['diagnostics']['chunks']
    if set(by_id) != {c['chunk_id'] for c in trace}:
        raise ValueError('Frozen rank/page/chunk identity mismatch')
    def ordered(key):
        return [by_id[c['chunk_id']][0].id for c in sorted(
            (c for c in trace if c[key] is not None and c[key] <= 20), key=lambda c:c[key])]
    fused = reciprocal_rank_fusion(ordered('bm25_rank'), ordered('vector_rank'))
    ranks = {str(x[0]): i for i, x in enumerate(fused, 1)}
    assert all(ranks.get(c['chunk_id']) == c['rrf_rank'] for c in trace)
    table, numeric = {}, {}
    for anchor, fact in deduplicate_verified(verified_table_candidates(rows, question)):
        table.setdefault(anchor, []).append(fact)
    for anchor, fact in deduplicate_verified(verified_numeric_candidates(rows, question)):
        numeric.setdefault(anchor, []).append(fact)
    promoted = sorted(set(table) | set(numeric), key=lambda a:(ranks.get(str(a), len(fused)+1), str(a)))
    lookup = {x[0]: x for x in fused}
    top = ([lookup.get(a, (a,0,None,None)) for a in promoted] +
           [x for x in fused if x[0] not in promoted])[:5]
    pool = fused[:20] + [lookup.get(a, (a,0,None,None)) for a in promoted
                        if a not in {x[0] for x in fused[:20]}]
    requirements = requirements_for(question)
    audit = {}
    pack, complete = (build_evidence_pack(question, requirements,
        [(x, *by_id[str(x[0])], ranks.get(str(x[0]),len(fused)+1)) for x in pool],
        table, numeric, audit=audit) if requirements else (None, None))
    results=[]
    for rank, (anchor,score,bm,vec) in enumerate(top,1):
        c,p,d=by_id[str(anchor)]
        results.append(dict(rank=rank,rrf_score=score,bm25_rank=bm,vector_rank=vec,
            chunk_id=c.id,document_id=d.id,document_name=d.filename,company_name=d.company_name,
            ticker=d.stock_code,publisher=d.issuer,published_at=d.published_at,document_type=d.document_type,
            page_number=p.page_number,section_title=c.section_title,quote=c.content,
            chunk_char_start=c.char_start,chunk_char_end=c.char_end,rrf_rank=ranks.get(str(anchor)),
            retrieval_reason='verified_table_conditions' if anchor in table else
                'verified_numeric_conditions' if anchor in numeric else 'hybrid_rrf',
            table_evidence=table.get(anchor,[]), **({'numeric_evidence':numeric[anchor]} if anchor in numeric else {})))
    unit_audit=[]
    for page in {p.id:p for _,p,_ in rows}.values():
        validated_stored_facts(page, unit_audit=unit_audit)
    return dict(results=results,evidence_pack=pack,coverage_complete=complete,
        requirements=requirements,diagnostics=dict(selection=audit),unit_audit=unit_audit,
        vector_search_used=old['vector_search_used'], replay_mode='frozen hybrid ranks')


def revision_rows(revision, old_search):
    prototype=old_search['results'][0]
    doc=NS(id=UUID(revision['document_id']),filename=prototype['document_name'],
        company_name=prototype['company_name'],stock_code=prototype['ticker'],issuer=prototype['publisher'],
        published_at=prototype['published_at'],document_type=prototype['document_type'])
    pages={}
    for p in revision['pages']:
        page=NS(id=UUID(p['id']),document_id=doc.id,page_number=p['page_number'],final_text=p['final_text'],
            extraction=NS(parser_version=revision['parser_version'].split('+pin-')[0],
                final_text_sha256=p['final_text_sha256'],provenance=p['provenance'],table_facts=p['table_facts']))
        pages[p['id']]=page
    rows=[]
    for c in revision['chunks']:
        page=pages[c['page_id']]
        chunk=NS(**{**c,'id':UUID(c['id']),'page_id':page.id,'document_id':doc.id,
                    'page_number':page.page_number,'section_title':None})
        rows.append((chunk,page,doc))
    return rows


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--output',type=Path,required=True)
    cli.add_argument('--row-association',action='store_true',
        help='Rebuild challenge cell facts from frozen text/bboxes only; no parser/OCR/index changes')
    args=cli.parse_args()
    if args.output.exists(): raise FileExistsError(args.output)
    production_hashes={p.name:digest(p) for p in (ROOT/'backend/app').glob('*.py')}
    directory=ROOT/'evals/results/paddle'
    sources={}
    def load(name):
        path=directory/name;sources[name]=digest(path);return read(path)
    base=load('graph-dev-run4-20261002.json')
    validate_binding(base,read(directory/'graph-dev-final-binding-20261002.json'))
    after=deepcopy(base)
    for case in after['cases']:
        if case['scope']=='unchanged_active_control':continue
        revision=next(r for r in base['revisions'] if r['document_id']==case['document_id'])
        verify_manifest(revision,next(m for m in base['manifests'] if m['revision_id']==revision['id']))
        case['shadow']=replay(revision_rows(revision,case['shadow']),case['shadow'],case['question'])
        print('development replay: '+case['id'], flush=True)
    # Canonical JSON keeps UUID identity identical to the immutable baseline.
    after=json.loads(json.dumps(after,default=str))
    head, diff_hash = code_identity()
    after['evaluation_code']={'mode':'offline frozen-rank unit gate replay',
        'git_head':head, 'working_tree_diff_sha256':diff_hash}
    metrics=evaluate(after,binding_for(after),base,binding_for(base),read(ROOT/'evals/pinned-gold.json'))
    print('development gate passed', flush=True)
    regression=[]
    challenge=[]
    for artifact,index_name,cases_file in [
        ('graph-regression-unseen-final-20261002.json','extraction-unseen-index-release2-20261002.json','table-integrity-unseen-cases.json'),
        ('graph-regression-holdout-run1-20261002.json','extraction-holdout-index-release2-20261002.json','holdout-cases.json')]:
        baseline=load(artifact);index=load(index_name);cases=read(ROOT/'evals'/cases_file)
        assert index['cases_sha256']==digest(ROOT/'evals'/cases_file)
        for case in cases:
            original=next(c for c in baseline['cases'] if c['id']==case['id'])
            rows,pages=thaw_rows(index['cases'][case['id']]['index'])
            search=replay(rows,original['search'],case['question'])
            passed,failure=strict(case,NS(**search),pages)
            print('fixed regression replay: '+case['id'], flush=True)
            regression.append(dict(id=case['id'],cohort='fixed regression',strict_pass=passed,
                failure_stage=failure,coverage_complete=search['coverage_complete'],
                search=search,previous_complete=original['search']['coverage_complete']))
    for observation_name, search_name in [
        ('graph-before-tables-20261002.json','graph-after-final-search-20261002.json'),
        ('graph-new-observations-20261002.json','graph-new-search-20261002.json')]:
      observed=load(observation_name);baseline=load(search_name)
      for case in observed['cases']:
          original=next(c for c in baseline['cases'] if c['id']==case['id'])
          doc=NS(id=uuid5(NAMESPACE_URL,case['pdf_sha256']),filename=case.get('filename',''),
              company_name='',stock_code=None,issuer='',published_at=None,document_type='broker_report')
          page=NS(id=uuid5(doc.id,str(case['page'])),document_id=doc.id,page_number=case['page'],final_text=case['final_text'],
              extraction=NS(parser_version=PARSER_VERSION if args.row_association else case['provenance']['parser_version'],
                            final_text_sha256=hashlib.sha256(case['final_text'].encode()).hexdigest(),
                            provenance=case['provenance'],table_facts=case['table_facts']))
          association_audit=[]
          if args.row_association:
              from app.structured_cells import extract_cell_facts
              page.extraction.table_facts = [f for f in case['table_facts']
                  if f.get('verification') != 'structured_primitive_cell'] + extract_cell_facts(
                      page.final_text, page.extraction.provenance['selected_words'],
                      page.extraction.provenance.get('native_tables', []) +
                      page.extraction.provenance.get('paddle_tables', []), page.page_number,
                      association_audit=association_audit)
          rows=[]
          for s in structured_spans(page.final_text,page.extraction.provenance):
              c=NS(id=uuid5(page.id,f'{s.char_start}:{s.char_end}'),page_id=page.id,document_id=doc.id,
                  page_number=page.page_number,char_start=s.char_start,char_end=s.char_end,content=s.content,section_title=None)
              rows.append((c,page,doc))
          search=replay(rows,original['search'],original['question'])
          print('challenge replay: '+case['id'], flush=True)
          expected=next(c for c in read(ROOT/'evals'/('extraction-unseen-table-cases.json' if observation_name.startswith('graph-before') else 'primitive-graph-unseen-cases.json')) if c['id']==case['id'])
          compact=lambda x:''.join(str(x or '').split())
          selected=[f for item in search['evidence_pack'] or [] for f in item.get('table_evidence',[])]
          facts=validated_stored_facts(page)
          passed=bool(search['coverage_complete']) and all(any(all(compact(f.get(k))==compact(g.get(k)) for k in ('row_label','period','unit','value')) for f in facts) for g in expected['cells']) and bool(selected)
          if args.row_association:
              primitives = selected + [p for f in selected for p in
                  f.get('comparison_derivation', {}).get('primitive_cells', [])]
              def proves(f, gold):
                  return (all(compact(f.get(k)) == compact(gold.get(k))
                              for k in ('row_label', 'metric', 'period', 'unit', 'value') if k in gold) and
                      all(any(s['role'] == g['role'] and s['quote'] == g['quote']
                              and s['bbox'] == g['bbox_pdf_points']
                              and page.final_text[s['char_start']:s['char_end']] == s['quote']
                              for s in f['source_spans']) for g in gold.get('gold_source_spans', [])))
              passed = bool(search['coverage_complete']) and all(
                  any(proves(f, g) for f in primitives) for g in expected['cells'])
          challenge.append(dict(id=case['id'],cohort='challenge set',strict_pass=passed,
              coverage_complete=search['coverage_complete'],previous_complete=original['coverage_complete'],
              association_audit=association_audit, validated_cell_facts=facts, search=search))
    out=dict(mode='offline validation/selection replay; no new retrieval',generator_called=False,
        ocr_called=False,embedding_called=False,db_called=False,active_hash_live_verified=False,
        active_control_mode='two unchanged controls from immutable baseline; no live DB replay',
        development=metrics,fixed_regression=regression,challenge_set=challenge,development_replay=after,
        source_hashes=sources,production_hashes=production_hashes)
    out['challenge_cell_rebuild'] = args.row_association
    assert sources=={name:digest(directory/name) for name in sources}
    assert production_hashes=={p.name:digest(p) for p in (ROOT/'backend/app').glob('*.py')}
    args.output.write_text(json.dumps(out,ensure_ascii=False,default=str))
    print({k:v for k,v in metrics.items() if k not in {'units','gate_definition'}})
    print('regression',[(c['id'],c['coverage_complete'],c['strict_pass']) for c in regression])
    print('challenge',[(c['id'],c['coverage_complete'],c['strict_pass']) for c in challenge])


if __name__=='__main__':main()
