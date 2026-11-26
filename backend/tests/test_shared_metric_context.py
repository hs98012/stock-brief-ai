"""Shared membership never licenses shared downstream metric ownership."""
from copy import deepcopy
import hashlib
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest

from app.layout_tables import source_span
from app.structured_cells import metric_context_ownership, extract_cell_facts, cell_fact_valid
from app.primitive_graph import primitive_graph, comparison_candidates, comparison_fact_valid
from app.evidence_requirements import table_requirements, fact_requirement_match
from tests.test_metric_context_ownership import fixture
from tests.test_structured_cells import observed


def shared(extra=(), change=None):
    text, words, table, _ = fixture()
    entries = [(w['text'], w['bbox']) for w in words] + [
        ('영업이익', [42, 32, 90, 42]), ('십억원', [92, 32, 130, 42]),
        ('12', [140, 32, 160, 42]), ('14', [180, 32, 200, 42]), *extra]
    if change:
        change(entries)
    text, words = observed(entries)
    for i, column in [(8, 1), (9, 2), (10, 3), (11, 4)]:
        b = words[i]['bbox']
        table['cells'].append(dict(row=2, column=column,
            bbox=[40 if column == 1 else 90 if column == 2 else b[0], b[1], b[2], b[3]],
            text=words[i]['text']))
    chains = [{role+'_span': source_span(words[i], role, text)
        for role, i in [('metric', m), ('unit', u), ('period', p), ('value', v)]}
        for m, u, p, v in [(2, 3, 4, 5), (8, 9, 4, 10)]]
    return text, words, table, chains


def proof(data, row=0, topology=True):
    text, words, table, chains = data
    return metric_context_ownership(text, words, table['cells'][0],
        [c['metric_span'] for c in chains], chains[row], [table] if topology else [])


def page(data):
    text, words, table, _ = data
    facts = extract_cell_facts(text, words, [table], 1)
    return NS(id=uuid4(), document_id=uuid4(), page_number=1, final_text=text,
        extraction=NS(parser_version=facts[0]['processing_version'] if facts else 'missing',
            final_text_sha256=hashlib.sha256(text.encode()).hexdigest(), table_facts=facts,
            provenance=dict(selected_words=words, native_tables=[table], paddle_tables=[],
                unsafe_spans=[], index_segments=[dict(char_start=0,char_end=len(text),kind='fact_quote')])) )


@pytest.mark.parametrize('topology', [True, False])
def test_shared_membership_has_distinct_metric_owners(topology):
    data = shared()
    a, b = [proof(data, row, topology) for row in (0, 1)]
    assert a['approved'] and b['approved']
    assert a['context_membership']['approved'] and b['context_membership']['approved']
    assert a['context_membership']['context_id'] == b['context_membership']['context_id']
    assert a['ownership_id'] != b['ownership_id']
    assert len(a['context_membership']['members']) == 2
    assert a['context_membership']['status'] == 'shared_metric_context_verified'
    assert not a['coverage_complete']  # membership alone never fills a query


def test_each_row_is_rederived_and_graph_never_connects_sibling_metrics():
    data = shared(); p = page(data)
    assert len(p.extraction.table_facts) == 4
    assert all(cell_fact_valid(f, data[0], data[1], [data[2]]) for f in p.extraction.table_facts)
    graph = primitive_graph(p)
    assert len(graph['nodes']) == 4 and len(graph['edges']) == 2
    by_id = {f['cell_fact_id']: f for f in graph['nodes']}
    assert all(by_id[e['lhs']]['metric'] == by_id[e['rhs']]['metric'] for e in graph['edges'])


def pack(p, question):
    from app.search import rank_rows
    d = NS(id=p.document_id,filename='shared.pdf',company_name='',stock_code=None,
        issuer='',published_at=None,document_type='broker_report')
    c = NS(id=uuid4(),page_id=p.id,document_id=d.id,page_number=1,char_start=0,
        char_end=len(p.final_text),content=p.final_text,section_title=None,embedding=None)
    return rank_rows([(c,p,d)], question, 5, NS(available=False,unavailable_reason='fixture'))


def test_query_selects_only_requested_metric_chain():
    p = page(shared())
    result = pack(p, '표의 2027F와 2028F 매출액을 비교해줘.')
    assert result.coverage_complete
    selected = [f for item in result.evidence_pack for f in item.get('table_evidence', [])]
    assert selected and all(f['metric'] == '매출액' for f in selected)
    assert all(x['metric'] == '매출액' for f in selected
        for x in f['comparison_derivation']['primitive_cells'])
    assert not any(s['role'].endswith('value') and s['quote'] in {'12', '14'}
        for item in result.evidence_pack for s in item['source_spans'])


@pytest.mark.parametrize('role', ['unit', 'value'])
def test_sibling_downstream_span_cannot_belong_to_target(role):
    data = shared()
    data[3][0][role+'_span'] = deepcopy(data[3][1][role+'_span'])
    assert not proof(data)['approved']


def test_identical_value_source_cannot_be_assigned_to_two_metric_rows():
    data = shared()
    data[3][1]['value_span'] = deepcopy(data[3][0]['value_span'])
    assert not proof(data, 1)['approved']


def test_duplicate_value_in_row_period_intersection_holds():
    data = shared([('72', [140,20,160,30])])
    result = proof(data)
    assert not result['approved']
    assert result['context_membership']['approved']
    assert result['rejection_reason'] == 'context_downstream_row_chain_ambiguous'


def test_duplicate_source_cell_ownership_holds():
    data = shared()
    data[2]['cells'].append(deepcopy(data[2]['cells'][1]))
    assert not proof(data)['approved']


def test_overlapping_metric_row_boundaries_hold_even_for_target_aligned_value():
    def move(entries):
        entries[8] = ('영업이익', [42,25,90,35])
    data = shared(change=move)
    assert not proof(data, topology=False)['approved']


def test_unknown_query_metric_never_approves_whole_context():
    result = pack(page(shared()), '표의 2027F와 2028F 수치를 비교해줘.')
    assert result.coverage_complete is False


def test_period_with_unassigned_value_row_holds():
    data = shared([('72', [140,27,160,37])])
    data[3][0]['value_span'] = source_span(data[1][-1], 'value', data[0])
    assert not proof(data, topology=False)['approved']


def test_shared_period_column_ambiguity_holds():
    data = shared([('2029F', [140,11,160,19])])
    result = proof(data, topology=False)
    assert not result['approved']
    assert result['context_membership']['approved']
    assert result['rejection_reason'] == 'context_period_column_ambiguous'


def test_mixed_comparison_pack_is_rejected():
    p = page(shared())
    req = table_requirements('표의 2027F와 2028F 매출액을 비교해줘.')
    a = comparison_candidates(p, req)[0]
    b = comparison_candidates(p, table_requirements('표의 2027F와 2028F 영업이익을 비교해줘.'))[0]
    a['comparison_cell'] = deepcopy(b['comparison_cell'])
    assert not comparison_fact_valid(a, p)
    assert not fact_requirement_match(req[0], a)[0]


def test_same_metric_name_in_two_shared_rows_is_query_ambiguous():
    def rename(entries):
        entries[8] = ('매출액', entries[8][1])
    p = page(shared(change=rename))
    assert len(p.extraction.table_facts) == 4
    assert not pack(p, '표의 2027F와 2028F 매출액을 비교해줘.').coverage_complete


def test_stripping_shared_proof_cannot_bypass_query_ambiguity():
    data = shared()
    f = deepcopy(page(data).extraction.table_facts[0])
    f.pop('metric_context_ownership')
    assert not cell_fact_valid(f, data[0], data[1], [data[2]])


def test_same_name_sibling_without_complete_chain_still_blocks_query_selection():
    def rename(entries):
        entries[8] = ('매출액', entries[8][1])
    p = page(shared(change=rename))
    p.extraction.table_facts = [f for f in p.extraction.table_facts if f['row_group_id'] ==
                               p.extraction.table_facts[0]['row_group_id']]
    assert not pack(p, '표의 2027F와 2028F 매출액을 비교해줘.').coverage_complete


def test_single_period_query_uses_only_target_metric_row():
    result = pack(page(shared()), '표의 2027F 매출액은 얼마인가?')
    assert result.coverage_complete
    assert all(f['metric'] == '매출액' for item in result.evidence_pack
               for f in item.get('table_evidence', []))


def test_unit_span_in_two_cells_cannot_be_owned_by_one_metric():
    data = shared()
    unit_cell = next(c for c in data[2]['cells'] if c['row'] == 1 and c['column'] == 2)
    data[2]['cells'].append({**unit_cell, 'row': 2})
    assert not proof(data)['approved']


def test_borrowing_sibling_owner_id_cannot_validate_fact():
    data = shared(); facts = page(data).extraction.table_facts
    f = deepcopy(facts[0]); other = next(g for g in facts if g['metric'] != f['metric'])
    f['metric_context_ownership']['ownership_id'] = other['metric_context_ownership']['ownership_id']
    assert not cell_fact_valid(f, data[0], data[1], [data[2]])
