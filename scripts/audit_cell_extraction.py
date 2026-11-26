#!/usr/bin/env python3
"""Re-derive NEW facts from immutable observations in memory; no DB/OCR writes."""
import argparse
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid5

from audit_unseen_table import (ROOT, digest, thaw_rows, freeze_rows, strict,
    SessionLocal, snapshot, OllamaEmbeddingProvider, rank_rows, structured_spans, retrieval_text)
from app.fact_fusion import PARSER_VERSION, fuse_candidates
from app.structured_cells import extract_cell_facts, merge_cell_facts, unit_compatible
from app.spatial_tables import extract_spatial_facts


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--input',type=Path,required=True)
    cli.add_argument('--cases',type=Path,required=True)
    cli.add_argument('--pdf-dir',type=Path,required=True)
    cli.add_argument('--output',type=Path,required=True)
    cli.add_argument('--write-index',type=Path)
    args=cli.parse_args()
    if args.output.exists() or args.write_index and args.write_index.exists():
        raise FileExistsError('Immutable output already exists')
    original=json.loads(args.input.read_text()); cases=json.loads(args.cases.read_text())
    if original['cases_sha256'] != digest(args.cases):
        raise ValueError('Frozen cases changed')
    provider=OllamaEmbeddingProvider()
    if not provider.available:
        raise RuntimeError(provider.unavailable_reason)
    report=dict(input_sha256=digest(args.input),cases_sha256=digest(args.cases),
        parser_version=PARSER_VERSION,generator_called=False,ocr_called=False,
        source_hashes={name:digest(ROOT/'backend/app'/name) for name in
            ('structured_cells.py','fused_extraction.py','spatial_tables.py','fact_fusion.py')},cases=[])
    frozen=dict(cases_sha256=digest(args.cases),parser_version=PARSER_VERSION,
        embedding=['ollama','bge-m3',1024],cases={})
    with SessionLocal() as db:
        report['active_before']=snapshot(db); db.rollback()
    for case in cases:
        if digest(args.pdf_dir/case['filename']) != case['pdf_sha256']:
            raise ValueError('PDF identity mismatch')
        stored=original['cases'][case['id']]
        if stored['pdf_sha256'] != case['pdf_sha256']:
            raise ValueError('Observation identity mismatch')
        old_rows,pages=thaw_rows(deepcopy(stored['index'])); document=old_rows[0][2]
        old_vectors={(str(c.page_id),c.char_start,c.char_end,retrieval_text(c,p)):c.embedding
                     for c,p,_ in old_rows}
        rows=[]; diagnostics=[]
        for page in pages.values():
            obs=page.extraction; pro=obs.provenance; words=pro['selected_words']
            if obs.final_text_sha256 != hashlib.sha256(page.final_text.encode()).hexdigest():
                raise ValueError('Frozen text hash mismatch')
            raw=pro.get('paddle_structure')
            if raw and pro.get('page_size'):
                from app.paddle_tables import decode_tables
                pro['paddle_tables']=decode_tables(raw,pro['page_size'][0]/raw['width'],
                                                   pro['page_size'][1]/raw['height'])
            cells=extract_cell_facts(page.final_text,words,
                pro.get('native_tables',[])+pro.get('paddle_tables',[]),page.page_number)
            unresolved=[]
            extract_spatial_facts(page.final_text,words,page.page_number,observations=unresolved)
            facts,_=fuse_candidates([f for f in merge_cell_facts(obs.table_facts,cells)
                                    if unit_compatible(f['metric'],f['unit'])])
            for f in facts:
                f['processing_version']=PARSER_VERSION
            obs.parser_version=PARSER_VERSION; obs.table_facts=facts
            pro['parser_version']=PARSER_VERSION; pro['primitive_cells']=cells
            pro['unresolved_cell_observations']=unresolved
            pro['numeric_evidence']=[{**f,'processing_version':PARSER_VERSION}
                                     for f in pro.get('numeric_evidence',[])]
            # Rebuild admitted support ranges exactly as new ingestion does.
            # A rejected old fact must not leave a searchable ghost anchor.
            pro['index_segments']=[s for s in pro['index_segments'] if s.get('kind')=='paragraph']
            for f in [*facts,*pro['numeric_evidence']]:
                pro['index_segments'].append(dict(char_start=f['char_start'],char_end=f['char_end'],
                    kind='fact_quote',source=f['source'],bbox=f['bbox']))
                for s in f['source_spans']:
                    pro['index_segments'].append(dict(char_start=s['char_start'],char_end=s['char_end'],
                        kind='fact_span',source=f['source'],bbox=s.get('bbox',f['bbox'])))
            chunks=[]
            for span in structured_spans(page.final_text,pro):
                chunk=SimpleNamespace(id=uuid5(page.id,f'{span.char_start}:{span.char_end}'),
                    page_id=page.id,document_id=document.id,page_number=page.page_number,
                    content=span.content,char_start=span.char_start,char_end=span.char_end,
                    section_title=None,embedding=None,embedding_provider='ollama',
                    embedding_model='bge-m3',embedding_dimensions=1024)
                key=(str(page.id),chunk.char_start,chunk.char_end,retrieval_text(chunk,page))
                chunk.embedding=old_vectors.get(key);chunks.append(chunk);rows.append((chunk,page,document))
            obs.table_facts=[{**f,'source_chunk_ids':sorted({str(c.id) for s in f['source_spans']
                for c in chunks if c.char_start<s['char_end'] and c.char_end>s['char_start']})} for f in facts]
            diagnostics.append(dict(page=page.page_number,primitive_cells=cells,
                unresolved_cells=unresolved,table_fact_count=len(facts),
                original_table_fact_count=len(next(p['extraction']['table_facts'] for p in
                    stored['index']['pages'] if p['page_number']==page.page_number))))
        pending=[row for row in rows if row[0].embedding is None]
        for i in range(0,len(pending),8):
            batch=pending[i:i+8]; vectors=provider.embed([retrieval_text(c,p) for c,p,_ in batch])
            for (c,_,_),v in zip(batch,vectors,strict=True):c.embedding=v
        result=rank_rows(rows,case['question'],5,provider,diagnostics=True)
        passed,stage=strict(case,result,pages)
        report['cases'].append(dict(id=case['id'],pdf_sha256=case['pdf_sha256'],question=case['question'],
            strict_pass=passed,failure_stage=stage,search=result.__dict__,extraction=diagnostics,
            embedding_created=len(pending)))
        frozen['cases'][case['id']]=dict(pdf_sha256=case['pdf_sha256'],index=freeze_rows(rows))
    with SessionLocal() as db:
        report['active_after']=snapshot(db);db.rollback()
    if report['active_before']!=report['active_after'] or digest(args.cases)!=report['cases_sha256']:
        raise ValueError('Active or cases changed')
    if args.write_index:
        with args.write_index.open('x') as f:json.dump(frozen,f,ensure_ascii=False,default=str)
        report['evaluation_index_sha256']=digest(args.write_index)
    with args.output.open('x') as f:json.dump(report,f,ensure_ascii=False,default=str)
    print('strict='+str(sum(c['strict_pass'] for c in report['cases']))+'/'+str(len(cases)))
    print('failures='+','.join(c['id']+':'+str(c['failure_stage']) for c in report['cases'] if not c['strict_pass']))


if __name__=='__main__':main()
