#!/usr/bin/env python3
"""Independent offline gold/component and frozen regression checks; no services."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'backend'))
from app.chunking import structured_spans
from app.evidence_integrity import span_is_covered
from app.unit_dependencies import unit_is_covered
from app.unit_validation import validate_unit
from app.page_layout import overlap, area


def read(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ('fixture', 'gold', 'regression', 'baseline', 'geometry', 'output'):
        cli.add_argument('--'+name, type=Path, required=True)
    args = cli.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    fixture = read(args.fixture)
    assert all(digest(Path(p)) == sha for p, sha in fixture['source_hashes'].items())
    gold = next(c for c in read(args.gold) if c['id'] == fixture['case_id'])
    index = fixture['frozen_index']
    stored = index['pages'][0]
    page = NS(**{**stored, 'extraction': NS(**stored['extraction'])})
    chunks = [NS(**c) for c in index['chunks']]
    selected = [f for i in fixture['after']['evidence_pack'] or [] for f in i['table_evidence']]
    primitives = selected + [p for f in selected for p in f.get('comparison_derivation', {}).get('primitive_cells', [])]
    compact = lambda x: ''.join(str(x or '').split())
    def proof_spans(fact):
        provenance = page.extraction.provenance
        audit = validate_unit(fact, page.final_text, provenance['selected_words'],
            provenance.get('native_tables', []) + provenance.get('paddle_tables', []))
        if not audit['approved']:
            return []
        proof = audit['unit_dependency']
        groups = [g for g in fixture['dependency_groups'] if g['primitive_id'] == fact.get('cell_fact_id')
                  and g['unit_dependency'] == proof]
        if not groups or not unit_is_covered(page, chunks, proof):
            return []
        return [*fact['source_spans'], *[{**s, 'role': 'unit'} for s in proof['components']]]
    def proves(fact, expected):
        return (all(compact(fact.get(k)) == compact(expected.get(k))
                    for k in ('row_label', 'metric', 'period', 'unit', 'value') if k in expected)
            and all(any(s['role'] == g['role'] and s['quote'] == g['quote']
                and s['bbox'] == g['bbox_pdf_points']
                and page.final_text[s['char_start']:s['char_end']] == s['quote']
                for s in proof_spans(fact)) for g in expected.get('gold_source_spans', [])))
    gold_checks = [dict(gold=g, proved=any(proves(f, g) for f in primitives)) for g in gold['cells']]
    strict = bool(fixture['after']['coverage_complete']) and all(g['proved'] for g in gold_checks)
    assert strict and fixture['complete_justified']
    observation_path = next(Path(p) for p in fixture['source_hashes'] if 'observations' in p)
    case = next(c for c in read(observation_path)['cases'] if c['id'] == fixture['case_id'])
    before_chunks = [NS(id=str(i), page_id=page.id, document_id=page.document_id,
        page_number=page.page_number, char_start=s.char_start, char_end=s.char_end, content=s.content)
        for i, s in enumerate(structured_spans(page.final_text, case['provenance']))]
    unit_matrix = []
    selected_ids = set(fixture['selected_primitive_ids'])
    for group in fixture['dependency_groups']:
        if group['primitive_id'] not in selected_ids:
            continue
        proof = group['unit_dependency']
        def covered(rows, s):
            return span_is_covered(page, [c for c in rows if c.char_start < s['char_end'] and c.char_end > s['char_start']],
                s['char_start'], s['char_end'], s['quote'])
        unit_matrix.append(dict(primitive_id=group['primitive_id'], group_id=group['group_id'],
            proof=proof, before=unit_is_covered(page, before_chunks, proof),
            after=unit_is_covered(page, chunks, proof), components=[dict(**s,
                before=covered(before_chunks, s), after=covered(chunks, s),
                chunk_ids=[c.id for c in chunks if c.char_start <= s['char_start'] and c.char_end >= s['char_end']])
                for s in proof['components']]))
    assert unit_matrix and all(u['after'] for u in unit_matrix)
    regression, baseline = read(args.regression), read(args.baseline)
    pack_checks = []
    for cohort in ('fixed_regression', 'challenge_set'):
        for case in regression[cohort]:
            old = next(c for c in baseline[cohort] if c['id'] == case['id'])
            same = case['search']['evidence_pack'] == old['search']['evidence_pack']
            pack_checks.append(dict(cohort=cohort, id=case['id'], unchanged=same))
    for case in regression['development_replay']['cases']:
        old = next(c for c in baseline['development_replay']['cases'] if c['id'] == case['id'])
        pack_checks.append(dict(cohort='development', id=case['id'],
            unchanged=case['shadow']['evidence_pack'] == old['shadow']['evidence_pack']))
    assert len(pack_checks) == 20 and all(c['unchanged'] for c in pack_checks)
    directory = args.fixture.parent
    review = read(directory/'offline-hybrid-reviewed-20261009.json')
    policy = {c['id']: c['manual_strict_retained'] for c in review['cases']}
    states = [dict(id=c['id'], coverage_complete=c['coverage_complete'], automatic_strict=c['strict_pass'],
        manual_review=policy.get(c['id'], False)) for cohort in ('fixed_regression', 'challenge_set')
        for c in regression[cohort]]
    false_complete = sum(c['coverage_complete'] is True and not c['automatic_strict'] and not c['manual_review'] for c in states)
    assert false_complete == 0
    hyundai = []
    for name in ('offline-hybrid-evaluation-20261008.json', 'offline-hybrid-weaker-evaluation-20261009.json'):
        artifact = read(directory/name)
        assert all(digest(ROOT/p) == sha for p, sha in artifact['source_hashes'].items())
        assert digest(Path(artifact['embedding_artifact'])) == artifact['embedding_sha256']
        assert artifact['challenge_pass_candidate']
        hyundai.extend(artifact['outcomes'])
    assert len(hyundai) == 15
    effective_states = [dict(c) for c in states]
    for state in effective_states:
        if state['id'] == fixture['case_id']:
            state.update(coverage_complete=True, automatic_strict=strict,
                mode='new offline fixture; exact verified component proof strict')
        elif state['id'] == artifact['case_id']:
            state.update(coverage_complete=True, automatic_strict=True,
                mode='immutable hash-bound cached PASS')
    effective_false_complete = sum(c['coverage_complete'] is True and not c['automatic_strict']
        and not c['manual_review'] for c in effective_states)
    assert effective_false_complete == 0
    geometry = read(args.geometry)
    membership = geometry['paddle_value_membership']
    ratio = overlap(membership['expected_cell']['bbox'], membership['word']['bbox']) / max(1, area(membership['word']['bbox']))
    assert ratio == membership['ratio'] and ratio <= membership['required_strictly_greater_than']
    protected = ['structured_cells.py', 'primitive_graph.py', 'search.py', 'chunking.py',
                 'query_scope.py', 'metric_annotations.py', 'fused_index.py']
    protected_checks = {name: digest(ROOT/'backend/app'/name) == baseline['production_hashes'][name] for name in protected}
    assert all(protected_checks.values())
    source_hashes = {str(p): digest(p) for p in (args.fixture, args.gold, args.regression, args.baseline, args.geometry)}
    output = dict(source_hashes=source_hashes, strict_pass=strict, gold_checks=gold_checks,
        strict_contract='exact gold plus revalidated admitted semantic unit components; no gold mutation',
        legacy_literal_component_list_match=all(any(all(compact(f.get(k)) == compact(g.get(k))
            for k in ('row_label', 'metric', 'period', 'unit', 'value') if k in g)
            and all(any(s['role'] == gs['role'] and s['quote'] == gs['quote'] and s['bbox'] == gs['bbox_pdf_points']
                for s in f['source_spans']) for gs in g.get('gold_source_spans', [])) for f in primitives)
            for g in gold['cells']),
        unit_matrix=unit_matrix, selected_pack_checks=pack_checks, unchanged_pack_count=len(pack_checks),
        development=regression['development'], regression_states=states,
        reviewed_effective_states=effective_states,
        reviewed_effective_false_complete=effective_false_complete,
        review_aware_false_complete=false_complete, new_fixture_false_complete=int(not strict),
        hyundai_cached_pass_outcomes=len(hyundai), hyundai_mode='immutable hash-bound freeze; no new retrieval',
        paddle_geometry=membership, paddle_geometry_recomputed_ratio=ratio,
        protected_source_hashes_unchanged=protected_checks,
        calls=dict(db_write=False, ocr=False, embedding=False, llm=False))
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(dict(strict_pass=strict, units=len(unit_matrix), unchanged_pack_count=len(pack_checks),
        review_aware_false_complete=false_complete, hyundai_cached_pass_outcomes=len(hyundai))))


if __name__ == '__main__':
    main()
