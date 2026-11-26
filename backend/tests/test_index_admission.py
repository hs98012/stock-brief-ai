"""Dependency admission is authorized by source rederivation, never proximity."""
from copy import deepcopy
from types import SimpleNamespace as NS
from uuid import uuid5

import pytest

from app.chunking import structured_spans
from app.fused_index import retrieval_text, searchable
from app.index_admission import admit_dependencies, dependency_groups
from app.search import rank_rows
from tests.test_query_scope import scoped_page, request
from tests.test_shared_metric_context import page, shared


def rows(p):
    d = NS(id=p.document_id, filename='fixture.pdf', company_name='', stock_code=None,
           issuer='', published_at=None, document_type='broker_report')
    return [(NS(id=uuid5(p.id, f'{s.char_start}:{s.char_end}'), page_id=p.id, document_id=d.id,
        page_number=p.page_number, content=s.content, char_start=s.char_start, char_end=s.char_end,
        section_title=None, embedding=None), p, d) for s in structured_spans(p.final_text, p.extraction.provenance)]


def clean(p):
    p.extraction.provenance.update(parser_version=p.extraction.parser_version, index_segments=[])
    return p


def test_complete_dependencies_two_periods_searchable_and_exact_source():
    p = clean(page(shared()))
    groups = admit_dependencies(p)
    assert len(groups) == 4
    chunks = rows(p)
    for group in groups:
        assert {'metric_context', 'metric', 'unit', 'period', 'value'} <= {s['role'] for s in group['dependencies']}
        assert all(any(c.char_start <= s['char_start'] and c.char_end >= s['char_end']
                       for c, _, _ in chunks) for s in group['dependencies'])
    assert all(c.content == p.final_text[c.char_start:c.char_end] for c, _, _ in chunks)
    assert sum(searchable(c, p) for c, _, _ in chunks) == 2
    result = rank_rows(chunks, '표의 2027F와 2028F 매출액을 비교해줘.', 5,
                      NS(available=False, unavailable_reason='offline'), diagnostics=True)
    assert result.coverage_complete
    assert result.diagnostics['table_candidate_count'] == 2
    assert any(r['bm25_rank'] for r in result.results)
    assert all(f['metric'] == '매출액' for item in result.evidence_pack for f in item['table_evidence'])


def test_annotation_scope_separation_and_idempotent_shared_references():
    p = clean(scoped_page())
    original = p.final_text
    groups = admit_dependencies(p)
    target = [g for g in groups if g['metric_canonical'] == '영업이익률']
    assert {g['scope'] for g in target} == {'consolidated', 'separate'}
    assert len({g['ownership_id'] for g in target}) == 2
    annotated = [g for g in target if g['scope'] == 'consolidated']
    assert all({'metric_annotation_marker', 'metric_annotation_definition'} <=
               {s['role'] for s in g['dependencies']} for g in annotated)
    assert all(g['metric_raw'] == '영업이익률3)' for g in annotated)
    before = deepcopy(p.extraction.provenance)
    assert admit_dependencies(p) == groups and p.extraction.provenance == before
    assert p.final_text == original
    segments = before['index_segments']
    assert len(segments) == len({(s['char_start'], s['char_end']) for s in segments})
    for scope in ('연결', '별도'):
        result = rank_rows(rows(p), request(scope), 5, NS(available=False, unavailable_reason='offline'))
        assert result.coverage_complete
        assert all(f['metric_identity']['source_scope']['scope'] ==
            ('consolidated' if scope == '연결' else 'separate')
            for item in result.evidence_pack for f in item['table_evidence'])
    assert not rank_rows(rows(p), request(''), 5, NS(available=False, unavailable_reason='offline')).coverage_complete
    assert any('영업이익률3)' in retrieval_text(c, p) and '2027F 10' in retrieval_text(c, p)
               for c, _, _ in rows(p))


@pytest.mark.parametrize('mutation', ['unverified', 'owner', 'context', 'other_value', 'missing_value', 'missing_unit'])
def test_invalid_primitive_never_admitted(mutation):
    p = clean(page(shared()))
    fact = deepcopy(p.extraction.table_facts[0])
    if mutation == 'unverified': fact['verification'] = 'unknown'
    elif mutation == 'owner': fact['metric_context_ownership']['ownership_id'] = 'forged'
    elif mutation == 'context': fact['metric_context_ownership']['context_membership']['context_id'] = 'forged'
    elif mutation == 'other_value':
        peer = next(f for f in p.extraction.table_facts if f['metric'] != fact['metric'])
        fact['value_span'] = deepcopy(peer['value_span'])
    else:
        role = mutation.removeprefix('missing_')
        fact['source_spans'] = [s for s in fact['source_spans'] if s['role'] != role]
    p.extraction.table_facts = [fact]
    assert not admit_dependencies(p)
    assert not rows(p)


def test_canonical_without_annotation_proof_is_not_admitted():
    p = clean(scoped_page())
    p.extraction.provenance['selected_words'] = [w for w in p.extraction.provenance['selected_words']
        if not str(w['line_id']).startswith('note:')]
    groups = admit_dependencies(p)
    assert not any(g['metric_raw'] == '영업이익률3)' for g in groups)


def test_unrelated_page_words_and_other_metric_values_not_in_target_group():
    p = clean(page(shared(extra=[('무관한 문장', [300, 100, 400, 110])])))
    groups = admit_dependencies(p)
    for g in groups:
        quotes = {s['quote'] for s in g['dependencies']}
        assert '무관한 문장' not in quotes
        if g['metric_raw'] == '매출액': assert not {'12', '14'} & quotes
    assert not any('무관한 문장' in c.content for c, _, _ in rows(p))


def test_same_value_source_with_forged_second_owner_is_rejected():
    p = clean(page(shared()))
    facts = p.extraction.table_facts
    forged = deepcopy(facts[0])
    peer = next(f for f in facts if f['metric'] != forged['metric'])
    forged['metric_context_ownership']['ownership_id'] = peer['metric_context_ownership']['ownership_id']
    p.extraction.table_facts = [forged, peer]
    assert all(g['primitive_id'] != forged['cell_fact_id'] for g in dependency_groups(p))


def test_scope_ambiguity_does_not_merge_groups_or_authorize_search():
    p = clean(scoped_page(scopes=('연결 기준', '연결 기준')))
    groups = admit_dependencies(p)
    assert not any(g['metric_canonical'] == '영업이익률' for g in groups)


def test_verified_primitive_retained_outside_fusion_is_admitted():
    p = clean(page(shared()))
    p.extraction.provenance['primitive_cells'] = [{k: v for k, v in f.items()
        if k not in {'comparison_cell', 'comparison_basis', 'comparison_derivation'}}
        for f in p.extraction.table_facts]
    p.extraction.table_facts = []
    groups = admit_dependencies(p)
    assert len(groups) == 4
    assert len(p.extraction.table_facts) == 4
    assert rank_rows(rows(p), '표의 2027F와 2028F 매출액을 비교해줘.', 5,
        NS(available=False, unavailable_reason='offline')).coverage_complete


def test_unverified_provenance_primitive_is_not_an_admission_authority():
    p = clean(page(shared()))
    fact = deepcopy(p.extraction.table_facts[0])
    fact['metric_context_ownership']['ownership_id'] = 'forged'
    p.extraction.provenance['primitive_cells'] = [fact]
    p.extraction.table_facts = []
    assert not admit_dependencies(p)
    assert not rows(p)


def test_touching_different_groups_keep_physical_ranges_separate():
    text = 'AB'
    spans = structured_spans(text, dict(parser_version='fact-fusion-fixture',
        index_admission_contract='verified-dependencies-v1', index_segments=[
            dict(char_start=0, char_end=1, kind='verified_dependency', group_ids=['a']),
            dict(char_start=1, char_end=2, kind='verified_dependency', group_ids=['b'])]))
    assert [(s.content, s.char_start, s.char_end) for s in spans] == [('A', 0, 1), ('B', 1, 2)]
