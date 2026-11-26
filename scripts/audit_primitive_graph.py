#!/usr/bin/env python3
"""Frozen observed-page graph evaluation; memory index, no ingestion/generator."""
import argparse
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

from audit_unseen_table import (digest, snapshot, SessionLocal, structured_spans,
    retrieval_text, rank_rows, OllamaEmbeddingProvider, ROOT)
from app.extraction_provenance import validated_stored_facts
from app.fact_fusion import PARSER_VERSION


def run(cases, observed, provider):
    result=[]; vectors={}
    for case in cases:
        old=next(c for c in observed['cases'] if c['id']==case['id'])
        if old['pdf_sha256']!=case['pdf_sha256']:raise ValueError('PDF identity changed')
        doc=SimpleNamespace(id=uuid5(NAMESPACE_URL,case['pdf_sha256']),filename=case['filename'],
            company_name='',stock_code=None,issuer='',published_at=None,document_type='broker_report')
        page=SimpleNamespace(id=uuid5(doc.id,str(case['page'])),document_id=doc.id,
            page_number=case['page'],final_text=old['final_text'],extraction=SimpleNamespace(
                parser_version=PARSER_VERSION,final_text_sha256=hashlib.sha256(old['final_text'].encode()).hexdigest(),
                provenance=old['provenance'],table_facts=old['table_facts']))
        unit_audit=[]
        facts=validated_stored_facts(page, unit_audit=unit_audit)
        rows=[]
        for span in structured_spans(page.final_text,page.extraction.provenance):
            chunk=SimpleNamespace(id=uuid5(page.id,f'{span.char_start}:{span.char_end}'),
                document_id=doc.id,page_id=page.id,page_number=page.page_number,
                content=span.content,char_start=span.char_start,char_end=span.char_end,
                section_title=None,embedding=None,embedding_provider='ollama',
                embedding_model='bge-m3',embedding_dimensions=1024)
            rows.append((chunk,page,doc))
        pending=list(dict.fromkeys(retrieval_text(c,p) for c,p,_ in rows if retrieval_text(c,p) not in vectors))
        for i in range(0,len(pending),8):
            vectors.update(zip(pending[i:i+8],provider.embed(pending[i:i+8]),strict=True))
        for chunk,p,_ in rows:chunk.embedding=vectors[retrieval_text(chunk,p)]
        cells=case['cells']; compare=case.get('comparison_required',False)
        question=case.get('question') or ('표에서 '+cells[0]['period']+' '+cells[0]['row_label']+'을 '+
            cells[1]['period']+'와 비교해줘.' if compare else '표에서 '+str(cells[0]['period'] or '')+
            ' '+cells[0]['row_label']+'과 '+cells[1]['row_label']+'의 값을 알려줘.')
        execution=rank_rows(rows,question,5,provider,diagnostics=True)
        compact=lambda x:''.join(str(x or '').split())
        states=[]
        for gold in cells:
            exact=[f for f in facts if all(compact(f.get(k))==compact(gold.get(k))
                for k in ('row_label','period','unit','value'))]
            # Diagnostic only: separated row+unit presentation is NOT an automatic pass.
            components=[f for f in facts if all(compact(f.get(k))==compact(gold.get(k))
                for k in ('period','unit','value')) and compact(f.get('row_label')) in compact(gold['row_label'])]
            cell_observations=[f for f in facts if compact(f.get('value'))==compact(gold['value'])
                and compact(f.get('period')).removesuffix('년')==compact(gold.get('period')).removesuffix('년')]
            states.append(dict(expected=gold,primitive_literal=exact,component_observations=components,
                cell_observations=cell_observations,primitive_exists=bool(components),
                component_validation=bool(components),
                validated=bool(exact),first_failing_stage=None if exact else
                    'requirement matching' if components else 'period association' if gold.get('period') is None
                    else 'unit association' if cell_observations and not any(f.get('unit')==gold['unit'] for f in cell_observations)
                    else 'metric association' if cell_observations
                    else 'primitive fact construction'))
        pack=execution.evidence_pack or []
        selected=[f for item in pack for f in item.get('table_evidence',[])]
        link=any(f.get('comparison_cell') and compact(f['period'])==compact(cells[0]['period'])
            and compact(f['comparison_cell']['period'])==compact(cells[1]['period'])
            for f in selected) if compare else None
        strict=all(s['validated'] for s in states) and (not compare or link is True) and bool(
            execution.coverage_complete) and all(any(all(compact(f.get(k))==compact(gold.get(k))
            for k in ('row_label','period','unit','value')) or f.get('comparison_cell') and all(
            compact(f['comparison_cell'].get(k))==compact(gold.get(k)) for k in ('period','unit','value'))
            for f in selected) for gold in cells)
        try:
            from app.primitive_graph import primitive_graph
            graph=primitive_graph(page)
        except ImportError:
            graph=None
        result.append(dict(id=case['id'],question=question,unit_audit=unit_audit,
            evaluation_scope='challenge set', requested_metric=cells[0].get('metric',cells[0]['row_label']),
            requested_periods=[c['period'] for c in cells],primitive_states=states,
            validated_graph=graph,
            graph_link_selected=link,coverage_complete=execution.coverage_complete,strict_pass=strict,
            first_failing_stage=next((s['first_failing_stage'] for s in states if s['first_failing_stage']),
                None if strict else 'comparison linking' if compare and not link else 'requirement matching'),
            search=execution.__dict__))
    return result


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--cases',type=Path,required=True)
    cli.add_argument('--observations',type=Path,required=True)
    cli.add_argument('--output',type=Path,required=True)
    args=cli.parse_args()
    if args.output.exists():raise FileExistsError(args.output)
    provider=OllamaEmbeddingProvider()
    if not provider.available:raise RuntimeError(provider.unavailable_reason)
    out=dict(fixture_sha256=digest(args.cases),observation_sha256=digest(args.observations),
        parser_version=PARSER_VERSION,generator_called=False,ocr_called=False,
        source_hashes={p.name:digest(p) for p in (ROOT/'backend/app').glob('*.py')})
    with SessionLocal() as db:out['active_before']=snapshot(db);db.rollback()
    out['cases']=run(json.loads(args.cases.read_text()),json.loads(args.observations.read_text()),provider)
    with SessionLocal() as db:out['active_after']=snapshot(db);db.rollback()
    assert out['active_before']==out['active_after'] and out['fixture_sha256']==digest(args.cases)
    args.output.write_text(json.dumps(out,ensure_ascii=False,default=str))
    print('strict='+str(sum(c['strict_pass'] for c in out['cases']))+'/'+str(len(out['cases'])))


if __name__=='__main__':main()
