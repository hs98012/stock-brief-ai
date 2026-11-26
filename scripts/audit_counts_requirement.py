#!/usr/bin/env python3
"""Offline count diagnosis; observations only, no gold-driven requirement repair."""
import argparse
import hashlib
import inspect
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'backend'), str(ROOT/'scripts')]
from app.chunking import structured_spans
from app.evidence_bundle import requirements_for
from app.evidence_requirements import PERIOD, METRIC, table_requirements
from app.extraction_provenance import validated_stored_facts
from app.fact_fusion import PARSER_VERSION
from app.primitive_graph import primitive_graph
from app.structured_cells import extract_cell_facts, _cell_topology, PERIOD_CELL


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def diagnose(question, observation):
    text = observation['final_text']
    provenance = observation['provenance']
    page = NS(page_number=observation['page'], final_text=text, extraction=NS(
        parser_version=PARSER_VERSION, final_text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        provenance=provenance, table_facts=observation['table_facts']))
    words = provenance['selected_words']
    tables = provenance.get('native_tables', []) + provenance.get('paddle_tables', [])
    lines, start = inspect.getsourcelines(_cell_topology)
    decision = start + next(i for i, line in enumerate(lines) if line.strip() == 'if not headers:')
    traces = []
    def trace(frame, event, arg):
        if event == 'line' and frame.f_code is _cell_topology.__code__ and frame.f_lineno == decision:
            traces.append(dict(header_count=len(frame.f_locals['headers']),
                predicate='at least one source-owned period header', passed=bool(frame.f_locals['headers'])))
        return trace
    previous = sys.gettrace()
    try:
        sys.settrace(trace)
        rebuilt = extract_cell_facts(text, words, tables, page.page_number)
    finally:
        sys.settrace(previous)
    # These are raw observations, never admitted facts or a completeness proof.
    observed_tables = [dict(index=t['index'], bbox=t['bbox'], row_count=t['row_count'],
        column_count=t['column_count'], header_and_first_data_cells=[c for c in t['cells'] if c['row'] <= 2])
        for t in tables]
    literal_words = [dict(quote=w['text'], char_start=w['char_start'], char_end=w['char_end'],
        bbox=w['bbox'], source=w['source'], exact=text[w['char_start']:w['char_end']] == w['text'])
        for w in words if any(overlap_box(c['bbox'], w['bbox']) for t in tables
                             for c in t['cells'] if c['row'] <= 2)]
    return dict(question=question, requirements=requirements_for(question),
        query_predicates=dict(period_present=bool(PERIOD.search(question)),
            supported_metric_present=bool(METRIC.search(question))),
        direct_table_parser=table_requirements(question),
        source_period_tokens=[w['text'] for w in words if PERIOD_CELL.fullmatch(w['text'])],
        observed_tables=observed_tables, observed_words=literal_words,
        stored_fact_count=len(observation['table_facts']),
        validated_fact_count=len(validated_stored_facts(page)),
        rebuilt_fact_count=len(rebuilt), primitive_trace=traces,
        graph_node_count=len(primitive_graph(page)['nodes']),
        admitted_segment_count=len(provenance.get('index_segments', [])),
        chunk_count=len(structured_spans(text, provenance)),
        completeness_proof=None, automatic_pass_justified=False,
        decision='C: query target ambiguous and source-bound count proof unsupported; HOLD')


def overlap_box(a, b):
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--observations', type=Path, required=True)
    cli.add_argument('--search', type=Path, required=True)
    cli.add_argument('--case-id', required=True)
    cli.add_argument('--db-reason', default='Offline audit does not connect to PostgreSQL')
    cli.add_argument('--output', type=Path, required=True)
    args = cli.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    inputs = {str(p): digest(p) for p in (args.observations, args.search)}
    production = {str(p): digest(p) for base in ('backend/app', 'frontend/app')
                  for p in (ROOT/base).rglob('*') if p.is_file()}
    observed = next(c for c in json.loads(args.observations.read_text())['cases'] if c['id'] == args.case_id)
    frozen = next(c for c in json.loads(args.search.read_text())['cases'] if c['id'] == args.case_id)
    output = diagnose(frozen['question'], observed)
    output.update(case_id=args.case_id, pdf_sha256=observed['pdf_sha256'],
        source_hashes=inputs, production_hashes_before=production,
        frozen_state={k: frozen[k] for k in ('coverage_complete', 'strict_pass')},
        db_status='NOT_VERIFIED', db_reason=args.db_reason,
        calls=dict(db=False, ocr=False, embedding=False, llm=False, production_write=False))
    assert inputs == {p: digest(Path(p)) for p in inputs}
    assert production == {p: digest(Path(p)) for p in production}
    output['production_unchanged'] = True
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({k: output[k] for k in ('question', 'requirements', 'rebuilt_fact_count',
        'graph_node_count', 'chunk_count', 'frozen_state', 'decision')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
