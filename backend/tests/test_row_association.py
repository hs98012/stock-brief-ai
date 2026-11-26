"""Geometry-only row/column association; immutable observations remain untouched."""
from copy import deepcopy
from pathlib import Path
import json

import pytest

from app.structured_cells import extract_cell_facts, cell_fact_valid, row_groups
from tests.test_structured_cells import cell_grid, observed


def test_row_group_and_literal_spans_are_rederivable():
    text, words, tables = cell_grid()
    facts = extract_cell_facts(text, words, tables, 1)
    assert len(facts) == 6
    groups = row_groups(tables[0])
    assert len({g['row_group_id'] for g in groups}) == 4
    for fact in facts:
        assert fact['row_group_id'] and fact['column_association_reason']
        for role in ('metric', 'value', 'period', 'unit'):
            span = fact[role+'_span']
            assert span['bbox'] and text[span['char_start']:span['char_end']] == span['quote']
        assert cell_fact_valid(fact, text, words, tables)


@pytest.mark.parametrize('role', ['metric', 'value', 'period', 'unit'])
def test_borrowed_row_or_column_span_cannot_validate(role):
    text, words, tables = cell_grid()
    facts = extract_cell_facts(text, words, tables, 1)
    fact = deepcopy(facts[0])
    other = next(f for f in facts if f['metric'] != fact['metric']) if role in {'metric', 'unit'} else facts[1]
    borrowed = next(s for s in other['source_spans'] if s['role'] == role)
    fact['source_spans'] = [borrowed if s['role'] == role else s for s in fact['source_spans']]
    fact[role+'_span'] = borrowed
    assert not cell_fact_valid(fact, text, words, tables)


def test_column_header_geometry_and_row_topology_conflicts_abstain():
    text, words, tables = cell_grid()
    bad = deepcopy(tables)
    bad[0]['cells'][2]['bbox'] = [300, 0, 385, 16]
    assert not any(f['period'] == '2025A' for f in extract_cell_facts(text, words, bad, 1))
    bad = deepcopy(tables)
    bad[0]['cells'][4]['bbox'] = [0, 48, 85, 64]
    assert not any(f['metric'] == '매출액' for f in extract_cell_facts(text, words, bad, 1))
    assert any(g['rejection_reason'] for g in row_groups(bad[0]))


def test_overlapping_boundaries_require_unique_literal_cell_membership():
    text, words, tables = cell_grid()
    # Reported columns remain ordered and every literal span has one owner.
    for cell in tables[0]['cells']:
        if cell['column'] == 2:
            cell['bbox'][2] = 302
    facts = extract_cell_facts(text, words, tables, 1)
    assert len(facts) == 6 and all(cell_fact_valid(f, text, words, tables) for f in facts)
    # The overlap now contains a value word in two reported columns.
    tables[0]['cells'][7]['bbox'][0] = 201
    audit = []
    facts = extract_cell_facts(text, words, tables, 1, association_audit=audit)
    assert not any(f['metric'] == '매출액' and f['period'] == '2025A' for f in facts)
    assert any(a.get('rejection_reason') == 'overlapping_span_cell_membership_unverified' for a in audit)


def test_period_and_unit_in_same_column_header_approve():
    entries = [('지표', [2, 2, 50, 14]), ('2025A', [102, 2, 142, 14]),
        ('십억원', [146, 2, 185, 14]), ('2026F', [202, 2, 242, 14]),
        ('십억원', [246, 2, 285, 14]), ('매출액', [2, 26, 50, 38]),
        ('71', [102, 26, 130, 38]), ('75', [202, 26, 230, 38])]
    text, words = observed(entries)
    table = dict(bbox=[0, 0, 300, 48], row_count=2, column_count=3, cells=[
        dict(row=r, column=c, bbox=[c*100, r*24, (c+1)*100, (r+1)*24], text='')
        for r in range(2) for c in range(3)])
    facts = extract_cell_facts(text, words, [table], 1)
    assert len(facts) == 2 and all(f['unit_source'] == 'column_header' for f in facts)
    assert all(cell_fact_valid(f, text, words, [table]) for f in facts)


def test_merged_body_cell_and_missing_span_abstain():
    text, words, tables = cell_grid()
    tables[0]['cells'][4]['rowspan'] = 2
    assert not any(f['metric'] == '매출액' for f in extract_cell_facts(text, words, tables, 1))
    text, words, tables = cell_grid()
    words[4].pop('char_start')
    assert not any(f['metric'] == '매출액' for f in extract_cell_facts(text, words, tables, 1))


def test_multilevel_header_without_parent_geometry_abstains():
    text, words, tables = cell_grid()
    tables[0]['cells'][2]['colspan'] = 2
    audit = []
    facts = extract_cell_facts(text, words, tables, 1, association_audit=audit)
    assert not any(f['period'] == '2025A' for f in facts)
    assert any(a.get('rejection_reason') == 'merged_column_membership_unverified' for a in audit)


def test_observed_challenge_has_bbox_bound_shared_chain_proof():
    root = Path(__file__).resolve().parents[2]
    path = root/'evals/results/paddle/graph-new-observations-20261002.json'
    if not path.exists():
        pytest.skip('immutable local challenge observations unavailable')
    cases = json.loads(path.read_text())['cases']
    golds = json.loads((root/'evals/primitive-graph-unseen-cases.json').read_text())
    case = next(c for c in cases if c['id'] == 'new-hyundai-mixed-pair')
    gold = next(c for c in golds if c['id'] == case['id'])
    p = case['provenance']; audit = []
    extract_cell_facts(case['final_text'], p['selected_words'],
        p['native_tables']+p['paddle_tables'], case['page'], association_audit=audit)
    for cell in gold['cells']:
        rejected = next(a for a in audit if a.get('metric_span', {}).get('quote') == cell['metric']
                        and a.get('value_span', {}).get('quote') == cell['value']
                        and a.get('period_span', {}).get('quote') == cell['period']
                        and a['metric_span']['source'] == 'native')
        assert rejected['approved'] and rejected['coverage_complete'] is False
        assert rejected['rejection_reason'] is None
        assert rejected['metric_context_ownership']['context_membership']['status'] == 'shared_metric_context_verified'
        assert len(rejected['metric_context_ownership']['candidate_metrics']) == 2
        for span in cell['gold_source_spans']:
            actual = rejected[span['role']+'_span']
            assert actual['quote'] == span['quote'] and actual['bbox'] == span['bbox_pdf_points']


def test_association_code_has_no_corpus_or_answer_shortcuts():
    root = Path(__file__).resolve().parents[1]
    for name in ('structured_cells.py', 'primitive_graph.py'):
        code = (root/'app'/name).read_text()
        for forbidden in ('삼성', '현대차', '하이닉스', 'POSCO', '.pdf', 'question_id',
                          '43.4', '6.6', 'new-hyundai', '233,946'):
            assert forbidden not in code
