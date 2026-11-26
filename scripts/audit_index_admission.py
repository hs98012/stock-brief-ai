#!/usr/bin/env python3
"""Rebuild one offline observation's dependency index; never call external services.

Fresh BM25 uses the unchanged production ranker. New vector ranks are deliberately
unavailable because source fixtures contain no embeddings for the new chunks.
Other frozen corpora must be evaluated separately with their immutable ranks.
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
from app.fused_index import retrieval_text, searchable
from app.index_admission import admit_dependencies
from app.metric_annotations import annotation_spans, annotation_valid
from app.primitive_graph import comparison_candidates, comparison_fact_valid
from app.search import rank_rows
from app.structured_cells import extract_cell_facts
from audit_unit_precision import replay


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rebuild_rows(page, document):
    return [(NS(id=uuid5(page.id, f'{s.char_start}:{s.char_end}'), page_id=page.id,
        document_id=document.id, page_number=page.page_number, char_start=s.char_start,
        char_end=s.char_end, content=s.content, section_title=None, embedding=None), page, document)
        for s in structured_spans(page.final_text, page.extraction.provenance)]


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--observations', type=Path, required=True)
    cli.add_argument('--frozen-search', type=Path, required=True)
    cli.add_argument('--case', required=True)
    cli.add_argument('--output', type=Path, required=True)
    args = cli.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    hashes = {str(p): digest(p) for p in (args.observations, args.frozen_search)}
    case = next(c for c in json.loads(args.observations.read_text())['cases'] if c['id'] == args.case)
    frozen = next(c for c in json.loads(args.frozen_search.read_text())['cases'] if c['id'] == args.case)
    document = NS(id=uuid5(NAMESPACE_URL, case['pdf_sha256']), filename='', company_name='',
        stock_code=None, issuer='', published_at=None, document_type='broker_report')
    page = NS(id=uuid5(document.id, str(case['page'])), document_id=document.id,
        page_number=case['page'], final_text=case['final_text'], extraction=NS(
            parser_version=PARSER_VERSION, final_text_sha256=hashlib.sha256(case['final_text'].encode()).hexdigest(),
            provenance=deepcopy(case['provenance']), table_facts=[]))
    pro = page.extraction.provenance
    page.extraction.table_facts = [f for f in case['table_facts']
        if f.get('verification') != 'structured_primitive_cell'] + extract_cell_facts(
            page.final_text, pro['selected_words'], pro.get('native_tables', []) + pro.get('paddle_tables', []),
            page.page_number)
    old_rows = rebuild_rows(page, document)
    before = replay(old_rows, frozen['search'], frozen['question'])
    groups = admit_dependencies(page)
    rows = rebuild_rows(page, document)
    assert all(chunk_matches_page(c, page) for c, _, _ in rows)
    offline = NS(available=False, unavailable_reason='offline: no new embeddings permitted')
    after = rank_rows(rows, frozen['question'], 5, offline, diagnostics=True)
    requirements = requirements_for(frozen['question'])
    comparisons = comparison_candidates(page, requirements)
    validations = []
    matrix = []
    for fact in comparisons:
        requirement = next(r for r in requirements if fact_requirement_match(r, fact)[0])
        validations.append(dict(primitive_id=fact['cell_fact_id'], period=fact['period'],
            value=fact['value'], annotation_valid=annotation_valid(fact, page, requirement),
            comparison_valid=comparison_fact_valid(fact, page),
            requirement_matched=fact_requirement_match(requirement, fact)[0],
            pack_spans_valid=bool(_fact_spans(page, fact, table=True, requirement=requirement))))
        for span in [*fact['source_spans'], *annotation_spans(fact)]:
            covering = [c for c, _, _ in rows if c.char_start < span['char_end'] and c.char_end > span['char_start']]
            selected = [item for item in after.evidence_pack or [] if any(
                s['char_start'] == span['char_start'] and s['char_end'] == span['char_end']
                for s in item['source_spans'])]
            matrix.append(dict(**span, period=fact['period'],
                admitted=span_is_covered(page, covering, span['char_start'], span['char_end'], span['quote']),
                chunk_ids=[str(c.id) for c in covering], selected_pack=bool(selected)))
    trace = {str(c['chunk_id']): c for c in after.diagnostics['chunks']}
    chunks = [dict(chunk_id=str(c.id), char_start=c.char_start, char_end=c.char_end,
        content=c.content, searchable=searchable(c, page), retrieval_text=retrieval_text(c, page),
        bm25_rank=trace[str(c.id)]['bm25_rank'], rrf_rank=trace[str(c.id)]['rrf_rank']) for c, _, _ in rows]
    selected_facts = [f for item in after.evidence_pack or [] for f in item['table_evidence']]
    justified = bool(after.coverage_complete) and all(all(v[k] for k in
        ('annotation_valid', 'comparison_valid', 'requirement_matched', 'pack_spans_valid')) for v in validations)
    assert not after.coverage_complete or justified
    assert not after.coverage_complete or all(m['admitted'] and m['selected_pack'] for m in matrix)
    assert hashes == {str(p): digest(p) for p in (args.observations, args.frozen_search)}
    output = dict(mode='offline dependency admission; fresh unchanged BM25 rank_rows; no vector embeddings',
        calls=dict(db=False, ocr=False, embedding=False, llm=False), source_hashes=hashes,
        case_id=args.case, question=frozen['question'], page=page.page_number,
        final_text_sha256=page.extraction.final_text_sha256,
        before=dict(chunk_count=len(old_rows), evidence_pack=before['evidence_pack'],
            coverage_complete=before['coverage_complete']),
        dependency_groups=groups, index_segments=pro['index_segments'], chunks=chunks,
        provenance_matrix=matrix, chain_validation=validations,
        after=after.__dict__, complete_justified=justified,
        selected_primitive_ids=sorted({p['cell_fact_id'] for f in selected_facts
            for p in f.get('comparison_derivation', {}).get('primitive_cells', [])}),
        frozen_index=dict(documents=[document.__dict__], pages=[dict(id=page.id,
            document_id=document.id, page_number=page.page_number, final_text=page.final_text,
            extraction=page.extraction.__dict__)], chunks=[c.__dict__ for c, _, _ in rows]))
    args.output.write_text(json.dumps(output, ensure_ascii=False, default=str, indent=2) + '\n')
    print(json.dumps(dict(before_complete=before['coverage_complete'], after_complete=after.coverage_complete,
        groups=len(groups), chunks=len(chunks), searchable=sum(c['searchable'] for c in chunks),
        table_candidates=after.diagnostics['table_candidate_count'],
        selected_pack=len(after.evidence_pack or []), justified=justified), ensure_ascii=False))


if __name__ == '__main__':
    main()
