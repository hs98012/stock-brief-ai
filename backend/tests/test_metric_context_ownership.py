"""Metric row ownership must be unique before any chain can be promoted."""
from copy import deepcopy

import pytest

from app.layout_tables import source_span
from app.structured_cells import metric_context_ownership, extract_cell_facts, cell_fact_valid
from tests.test_structured_cells import observed


def fixture(extra=()):
    entries = [('문맥', [0, 20, 40, 30]), ('(범위)', [0, 32, 40, 42]),
        ('매출액', [42, 20, 90, 30]), ('십억원', [92, 20, 130, 30]),
        ('2027F', [140, 0, 160, 10]), ('71', [140, 20, 160, 30]),
        ('2028F', [180, 0, 200, 10]), ('75', [180, 20, 200, 30]), *extra]
    text, words = observed(entries)
    spans = {role+'_span': source_span(words[i], role, text)
             for role, i in [('metric', 2), ('unit', 3), ('period', 4), ('value', 5)]}
    table = dict(bbox=[0, 0, 200, 50], row_count=3, column_count=5, cells=[
        dict(row=1, column=0, rowspan=2, bbox=[0, 20, 40, 42], text='문맥\n(범위)'),
        dict(row=1, column=1, bbox=[40, 20, 90, 30], text='매출액'),
        dict(row=1, column=2, bbox=[90, 20, 130, 30], text='십억원'),
        *[dict(row=r, column=c, bbox=b, text=t) for r, c, b, t in [
            (0, 3, [140, 0, 160, 10], '2027F'), (1, 3, [140, 20, 160, 30], '71'),
            (0, 4, [180, 0, 200, 10], '2028F'), (1, 4, [180, 20, 200, 30], '75')]]])
    return text, words, table, spans


@pytest.mark.parametrize('topology', [True, False])
def test_clear_merged_context_has_unique_geometry_backed_owner(topology):
    text, words, table, chain = fixture()
    context = table['cells'][0]
    proof = metric_context_ownership(text, words, context, [chain['metric_span']],
                                     chain, [table] if topology else [])
    assert proof['approved'] and proof['rejection_reason'] is None
    assert all(proof['checks'].values()) and proof['ownership_id']
    assert proof['mode'] == ('cell_geometry' if topology else 'literal_geometry_fallback')
    assert [s['quote'] for s in proof['context_spans']] == ['문맥', '(범위)']


def test_approved_context_is_preserved_in_facts_and_revalidated():
    text, words, table, _ = fixture()
    facts = extract_cell_facts(text, words, [table], 1)
    assert len(facts) == 2 and all(f['metric_context_ownership']['approved'] for f in facts)
    assert all(cell_fact_valid(f, text, words, [table]) for f in facts)
    damaged = deepcopy(facts[0])
    damaged['metric_context_ownership']['ownership_id'] = 'different'
    assert not cell_fact_valid(damaged, text, words, [table])


@pytest.mark.parametrize('topology', [True, False])
def test_context_covering_two_metric_rows_shares_membership_only(topology):
    text, words, table, chain = fixture([('영업이익', [42, 32, 90, 42])])
    other = source_span(words[-1], 'metric', text)
    if topology:
        table['cells'].append(dict(row=2, column=1, bbox=[40, 32, 90, 42], text=other['quote']))
    proof = metric_context_ownership(text, words, table['cells'][0],
        [chain['metric_span'], other], chain, [table] if topology else [])
    assert proof['approved'] and proof['coverage_complete'] is False
    assert proof['context_membership']['status'] == 'shared_metric_context_verified'
    assert len(proof['candidate_metrics']) == 2


def test_aligned_y_does_not_prove_horizontal_ownership():
    text, words, table, chain = fixture()
    context = {**table['cells'][0], 'bbox': [250, 20, 290, 42]}
    proof = metric_context_ownership(text, words, context, [chain['metric_span']], chain)
    assert not proof['approved']


def test_unit_in_different_row_blocks_context_chain():
    text, words, table, chain = fixture()
    words[3]['bbox'] = [92, 45, 130, 55]
    chain['unit_span']['bbox'] = words[3]['bbox']
    proof = metric_context_ownership(text, words, table['cells'][0], [chain['metric_span']], chain)
    assert proof['rejection_reason'] == 'context_downstream_row_chain_unverified'


def test_ambiguous_period_column_holds():
    text, words, table, chain = fixture([('2029F', [140, 11, 160, 19])])
    proof = metric_context_ownership(text, words, table['cells'][0], [chain['metric_span']], chain)
    assert proof['rejection_reason'] == 'context_period_column_ambiguous'


def test_source_span_in_two_cells_or_topologies_holds():
    text, words, table, chain = fixture()
    other = deepcopy(table)
    proof = metric_context_ownership(text, words, table['cells'][0], [chain['metric_span']],
                                     chain, [table, other])
    assert proof['rejection_reason'] == 'context_source_multiple_cell_owners'


def test_second_value_in_same_column_and_row_holds():
    text, words, table, chain = fixture([('72', [140, 20, 160, 30])])
    proof = metric_context_ownership(text, words, table['cells'][0], [chain['metric_span']], chain)
    assert proof['rejection_reason'] == 'context_downstream_row_chain_ambiguous'


def test_changed_period_geometry_does_not_relax_column_thresholds():
    text, words, table, chain = fixture()
    words[4]['bbox'] = [150, 0, 170, 10]
    chain['period_span']['bbox'] = words[4]['bbox']
    proof = metric_context_ownership(text, words, table['cells'][0], [chain['metric_span']], chain)
    assert proof['rejection_reason'] == 'context_period_column_unverified'


def test_two_equally_valid_metric_candidates_on_one_baseline_hold():
    text, words, table, chain = fixture([('이익', [100, 20, 130, 30])])
    other = source_span(words[-1], 'metric', text)
    proof = metric_context_ownership(text, words, table['cells'][0],
        [chain['metric_span'], other], chain)
    assert proof['rejection_reason'] == 'merged_context_metric_not_unique'


def test_graph_cannot_join_different_context_owners():
    from app.primitive_graph import relation
    text, words, table, _ = fixture()
    facts = extract_cell_facts(text, words, [table], 1)
    for f in facts:
        f['document_id'] = 'fixture'
    assert relation(*facts)['linkable']
    facts[1]['metric_context_ownership']['ownership_id'] = 'another context'
    assert not relation(*facts)['linkable']
