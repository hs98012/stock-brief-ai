"""Composite proof admission, partial coverage, and membership rejection."""
from copy import deepcopy

import pytest

from app.index_admission import admit_dependencies
from app.unit_dependencies import unit_dependency, unit_is_covered
from app.unit_validation import validate_unit
from app.structured_cells import extract_cell_facts
from app.search import rank_rows
from tests.test_structured_cells import cell_grid, observed
from tests.test_shared_metric_context import page
from tests.test_index_admission import clean, rows
from types import SimpleNamespace as NS


def composite(parts=('조', '원')):
    _, words, tables = cell_grid()
    entries = [(w['text'], w['bbox']) for w in words]
    box = words[5]['bbox']
    entries[5:6] = [(token, [box[0]+i*10, box[1], box[0]+i*10+8, box[3]])
                    for i, token in enumerate(parts)]
    tables[0]['cells'][5]['text'] = ''.join(parts)
    text, words = observed(entries)
    return text, words, tables[0], []


def target(p):
    return [g for g in admit_dependencies(p) if g['metric_raw'] == '매출액']


@pytest.mark.parametrize('parts', [('조', '원'), ('십', '억', '원')])
def test_components_admitted_with_complete_metric_value_chain(parts):
    p = clean(page(composite(parts)))
    groups = target(p)
    assert len(groups) == 2
    for g in groups:
        proof = g['unit_dependency']
        assert proof['kind'] == 'composite'
        assert [s['quote'] for s in proof['components']] == list(parts)
        assert len({s['unit_primitive_id'] for s in proof['components']}) == 1
        assert len({str(s['cell_id']) for s in proof['components']}) == 1
        assert all(s in g['dependencies'] for s in proof['components'])
        assert all(p.final_text[s['char_start']:s['char_end']] == s['quote'] for s in proof['components'])
        assert unit_is_covered(p, [c for c, _, _ in rows(p)], proof)
        assert {s['role'] for s in g['dependencies']} >= {'metric', 'unit', 'period', 'value'}
    result = rank_rows(rows(p), '표의 2025A와 2026F 매출액을 비교해줘.', 5,
                       NS(available=False, unavailable_reason='offline'))
    assert result.coverage_complete and result.evidence_pack


def test_atomic_percent_retains_one_component():
    p = clean(page(composite()))
    groups = [g for g in admit_dependencies(p) if g['metric_raw'] == '영업이익률']
    assert len(groups) == 2
    assert all(g['unit_dependency']['kind'] == 'atomic' and
               [s['quote'] for s in g['unit_dependency']['components']] == ['%'] for g in groups)


def test_partial_unit_search_anchor_cannot_complete_evidence():
    p = clean(page(composite()))
    proof = target(p)[0]['unit_dependency']
    missing = proof['components'][0]
    p.extraction.provenance['index_segments'] = [s for s in p.extraction.provenance['index_segments']
        if not (s['char_start'] <= missing['char_start'] < s['char_end'])]
    chunks = rows(p)
    assert not unit_is_covered(p, [c for c, _, _ in chunks], proof)
    result = rank_rows(chunks, '표의 2025A와 2026F 매출액을 비교해줘.', 5,
                       NS(available=False, unavailable_reason='offline'))
    assert not result.coverage_complete


@pytest.mark.parametrize('key', ['ownership_id', 'row_id', 'table_id', 'context_id', 'unit_primitive_id'])
def test_conflicting_component_owner_or_membership_is_rejected(key):
    data = composite()
    text, words, table, _ = data
    fact = next(f for f in extract_cell_facts(text, words, [table], 1) if f['metric'] == '매출액')
    words = deepcopy(words)
    next(w for w in words if w['text'] == '조')[key] = 'unrelated'
    assert not validate_unit(fact, text, words, [table])['approved']


def test_overlapping_component_observations_are_ambiguous():
    text, words, table, _ = composite()
    fact = next(f for f in extract_cell_facts(text, words, [table], 1) if f['metric'] == '매출액')
    words = [*words, deepcopy(next(w for w in words if w['text'] == '조'))]
    assert not validate_unit(fact, text, words, [table])['approved']


def test_different_row_or_cell_cannot_supply_component():
    text, words, table, _ = composite()
    next(w for w in words if w['text'] == '조')['bbox'][1:4:2] = [74, 86]
    assert not [f for f in extract_cell_facts(text, words, [table], 1) if f['metric'] == '매출액']


def test_unverified_primitive_has_no_admission_even_with_same_page_components():
    p = clean(page(composite()))
    p.extraction.table_facts = [f for f in p.extraction.table_facts if f['metric'] == '매출액']
    for f in p.extraction.table_facts:
        f['verification'] = 'unverified'
    assert not admit_dependencies(p)


def test_unrelated_component_cannot_be_injected_into_proof():
    text, words, table, _ = composite()
    fact = next(f for f in extract_cell_facts(text, words, [table], 1) if f['metric'] == '매출액')
    audit = validate_unit(fact, text, words, [table])
    bad = deepcopy(fact)
    bad['unit_dependency'] = deepcopy(audit['unit_dependency'])
    bad['unit_dependency']['components'].append(dict(quote='unrelated'))
    assert not validate_unit(bad, text, words, [table])['approved']


@pytest.mark.parametrize('tokens', [('million', 'USD'), ('billion', 'KRW'), ('a', 'b', 'c')])
def test_dependency_contract_does_not_use_unit_dictionary(tokens):
    # Parsing/semantic approval belongs to the upstream verifier. This tests the
    # generic contract independently of the existing Korean financial parser.
    text, words = observed([(t, [i*20, 0, i*20+16, 12]) for i, t in enumerate(tokens)])
    from app.unit_validation import located
    span = located(text, words, 0, len(text.rstrip()))
    audit = dict(approved=True, unit_span=span, unit_surface=span['quote'],
                 canonical_unit=''.join(tokens), unit_association={})
    proof = unit_dependency(dict(page_number=1), audit, text, words)
    assert [s['quote'] for s in proof['components']] == list(tokens)
    assert unit_dependency({}, {**audit, 'approved': False}, text, words) is None


def test_verified_header_shares_unit_identity_without_merging_metric_owners():
    text, words = observed([('unit', [0, 0, 20, 12])])
    from app.unit_validation import located
    span = located(text, words, 0, 4)
    audit = dict(approved=True, unit_span=span, unit_surface='unit', canonical_unit='unit',
                 unit_association={}, unit_source='column_header')
    proofs = [unit_dependency(dict(page_number=1, table_id='table', row_id=row), audit, text, words)
              for row in ('row-a', 'row-b')]
    assert proofs[0]['unit_primitive_id'] == proofs[1]['unit_primitive_id']
    assert proofs[0]['binding']['row_id'] != proofs[1]['binding']['row_id']
    audit['unit_source'] = 'same_row'
    a = unit_dependency(dict(page_number=1, table_id='table', row_id='row-a'), audit, text, words)
    b = unit_dependency(dict(page_number=1, table_id='table', row_id='row-b'), audit, text, words)
    assert a['unit_primitive_id'] != b['unit_primitive_id']
