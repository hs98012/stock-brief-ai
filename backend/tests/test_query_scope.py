"""Scope disambiguates rows only with literal membership and intact chains."""
from copy import deepcopy
import hashlib

import pytest

from app.evidence_requirements import table_requirements, fact_requirement_match
from app.metric_annotations import annotate_metric_facts, annotation_valid
from app.evidence_bundle import _fact_spans
from app.primitive_graph import comparison_candidates
from app.structured_cells import extract_cell_facts
from tests.test_metric_annotations import annotated_page
from tests.test_structured_cells import observed
from tests.test_shared_metric_context import pack


def scoped_page(duplicate=False, scopes=('연결 기준', '별도 기준')):
    labels = ('영업이익률3)', '영업이익률3)' if duplicate else '순이익률3)',
              '영업이익률', '순이익률')
    p = annotated_page(labels)
    pro = p.extraction.provenance
    table = pro['native_tables'][0]
    entries = [(w['text'], [w['bbox'][0]+110, w['bbox'][1], w['bbox'][2]+110, w['bbox'][3]])
               for w in pro['selected_words']]
    for cell in table['cells']:
        cell['column'] += 1
        cell['bbox'][0] += 110
        cell['bbox'][2] += 110
    table['bbox'][2] += 110
    table['column_count'] += 1
    for i, scope in enumerate(scopes):
        row = 1+2*i
        box = [0, row*24, 110, (row+2)*24]
        table['cells'].append(dict(row=row, column=0, rowspan=2, bbox=box, text=scope))
        entries.append((scope, [2, box[1]+2, 105, box[1]+18]))
    text, words = observed(entries)
    # Preserve the explicit located table footnote's common line identity.
    for w, old in zip(words, pro['selected_words']):
        w['line_id'] = old['line_id']
    p.final_text = text
    p.extraction.final_text_sha256 = hashlib.sha256(text.encode()).hexdigest()
    pro['selected_words'] = words
    pro['index_segments'] = [dict(char_start=0, char_end=len(text), kind='fact_quote')]
    p.extraction.table_facts = extract_cell_facts(text, words, [table], 1)
    return p


def request(scope='연결'):
    return f'표의 {scope} 기준 2027F와 2028F 영업이익률을 비교해줘.'


@pytest.mark.parametrize('surface,expected', [('연결', 'consolidated'), ('별도', 'separate'),
    ('개별', 'separate'), ('consolidated', 'consolidated'), ('separate', 'separate'), ('standalone', 'separate')])
@pytest.mark.parametrize('basis', ['', ' 기준'])
def test_parser_preserves_scope_before_dates(surface, expected, basis):
    clause = f'표의 {surface}{basis} 2027F와 2028F 영업이익률을 비교해줘.'
    for req in table_requirements(clause):
        assert req['scope'] == expected and req['entity'] is None
        assert req['metric']['surface'] == '영업이익률'
        assert all(clause[x['char_start']:x['char_end']] == x['quote'] for x in req['scope_proof'])


@pytest.mark.parametrize('scope,raw', [('연결', '영업이익률3)'), ('별도', '영업이익률')])
def test_scope_local_unique_pack_preserves_global_collision(scope, raw):
    p = scoped_page()
    result = pack(p, request(scope))
    assert result.coverage_complete
    selected = [f for item in result.evidence_pack for f in item.get('table_evidence', [])]
    assert selected and all(f['metric'] == raw for f in selected)
    assert all(len(f['metric_identity']['collision_spans']) == 2 for f in selected)
    assert all(f['metric_identity']['canonical_label'] == '영업이익률' for f in selected)
    assert all(p['metric'] == raw for f in selected for p in f['comparison_derivation']['primitive_cells'])
    forbidden = {'12', '13'} if scope == '연결' else {'10', '11'}
    assert not any(s['role'].endswith('value') and s['quote'] in forbidden
                   for item in result.evidence_pack for s in item['source_spans'])


@pytest.mark.parametrize('scope', ['', '연결 별도', '별도'])
def test_unspecified_conflicting_or_mismatched_scope_holds(scope):
    p = scoped_page(scopes=('연결 기준', '연결 기준')) if scope == '별도' else scoped_page()
    assert not pack(p, request(scope)).coverage_complete


def test_duplicate_metric_inside_requested_scope_holds():
    assert not pack(scoped_page(duplicate=True), request()).coverage_complete


@pytest.mark.parametrize('field,value', [('scope', None), ('scope', 'separate'),
    ('scope_proof', []), ('scope_ambiguous', True)])
def test_parser_proof_deletion_or_mutation_rejects_previous_fact(field, value):
    p = scoped_page(); req = table_requirements(request())[0]
    f = comparison_candidates(p, [req])[0]
    req[field] = value
    assert not fact_requirement_match(req, f)[0]


@pytest.mark.parametrize('mutation', ['membership', 'context_id', 'ownership_id', 'span',
    'annotation', 'period', 'value', 'cross_scope', 'context_literal', 'source_span_delete'])
def test_proof_tampering_rejects_previous_passing_pack(mutation):
    p = scoped_page(); req = table_requirements(request())[0]
    f = deepcopy(comparison_candidates(p, [req])[0])
    assert _fact_spans(p, f, table=True, requirement=req)
    ownership = f['metric_context_ownership']
    if mutation == 'membership': ownership.pop('context_membership')
    elif mutation == 'context_id': ownership['context_membership']['context_id'] = 'forged'
    elif mutation == 'ownership_id': ownership['ownership_id'] = 'forged'
    elif mutation == 'span': f['metric_identity']['source_scope']['membership']['context_spans'] = []
    elif mutation == 'annotation': f['metric_identity']['definition_spans'] = []
    elif mutation == 'period': f['period'] = '2029F'
    elif mutation == 'value': f['value_span'] = deepcopy(f['comparison_derivation']['primitive_cells'][1]['value_span'])
    elif mutation == 'cross_scope':
        other = comparison_candidates(p, table_requirements(request('별도')))[0]
        f['comparison_cell'] = deepcopy(other['comparison_cell'])
    elif mutation == 'context_literal':
        word = next(w for w in p.extraction.provenance['selected_words'] if w['text'] == '연결 기준')
        word['text'] = '별도 기준'
    elif mutation == 'source_span_delete':
        p.extraction.provenance['selected_words'] = [w for w in p.extraction.provenance['selected_words']
                                                   if w['text'] != '연결 기준']
    assert not _fact_spans(p, f, table=True, requirement=req)


def test_removed_or_changed_query_scope_rejects_old_selected_fact():
    p = scoped_page(); req = table_requirements(request())[0]
    f = comparison_candidates(p, [req])[0]
    for query in [request(''), request('별도')]:
        assert not fact_requirement_match(table_requirements(query)[0], f)[0]
        assert not _fact_spans(p, f, table=True, requirement=table_requirements(query)[0])


def test_literal_scope_without_membership_never_passes():
    p = annotated_page(('영업이익률3)',))
    assert not pack(p, request()).coverage_complete


def test_scope_without_annotation_proof_cannot_resolve_collision():
    p = scoped_page()
    p.extraction.provenance['selected_words'] = [w for w in p.extraction.provenance['selected_words']
                                               if not str(w['line_id']).startswith('note:')]
    assert not pack(p, request()).coverage_complete


def test_shared_value_span_cannot_have_two_scope_owners():
    p = scoped_page(); req = table_requirements(request())[0]
    f = deepcopy(comparison_candidates(p, [req])[0])
    peer = next(x for x in annotate_metric_facts(p, p.extraction.table_facts)
                if x['metric'] == '영업이익률' and x['period'] == f['period'])
    f['value_span'] = deepcopy(peer['value_span'])
    assert not _fact_spans(p, f, table=True, requirement=req)


def test_global_collision_requires_explicit_verified_scope_authorization():
    p = scoped_page(); f = annotate_metric_facts(p, p.extraction.table_facts)[0]
    assert not annotation_valid(f, p)
    assert not fact_requirement_match(table_requirements(request(''))[0], f)[0]


@pytest.mark.parametrize('scope', ['연결', '연결 기준', '별도', '별도 기준'])
def test_scope_adjacent_to_metric_is_not_an_entity(scope):
    req = table_requirements(f'표의 {scope} 영업이익률은 얼마인가?')[0]
    assert req['entity'] is None and req['scope']


def test_unsafe_scope_literal_cannot_authorize_selection():
    p = scoped_page()
    w = next(w for w in p.extraction.provenance['selected_words'] if w['text'] == '연결 기준')
    p.extraction.provenance['unsafe_spans'] = [dict(char_start=w['char_start'], char_end=w['char_end'])]
    assert not pack(p, request()).coverage_complete


def test_question_binding_rejects_consistently_forged_parser_scope():
    from app.evidence_bundle import build_evidence_pack, requirements_for
    audit = {}
    _, complete = build_evidence_pack(request(), requirements_for(request('별도')), [], {}, {}, audit=audit)
    assert not complete and audit['candidates'][0]['reason'] == 'query_scope_proof_invalid'


def test_source_context_changed_with_new_hash_rejects_old_fact():
    p = scoped_page(); req = table_requirements(request())[0]
    f = deepcopy(comparison_candidates(p, [req])[0])
    p.final_text = p.final_text.replace('연결 기준', '별도 기준')
    p.extraction.final_text_sha256 = hashlib.sha256(p.final_text.encode()).hexdigest()
    for w in p.extraction.provenance['selected_words']:
        if w['text'] == '연결 기준': w['text'] = '별도 기준'
    assert not _fact_spans(p, f, table=True, requirement=req)
    assert not pack(p, request()).coverage_complete


def test_plain_canonical_collision_also_needs_scope():
    p = scoped_page()
    p.final_text = p.final_text.replace('영업이익률3)', '영업이익률  ')
    p.extraction.final_text_sha256 = hashlib.sha256(p.final_text.encode()).hexdigest()
    for w in p.extraction.provenance['selected_words']:
        if w['text'] == '영업이익률3)':
            w['text'] = '영업이익률'; w['char_end'] -= 2
    pro = p.extraction.provenance
    p.extraction.table_facts = extract_cell_facts(p.final_text, pro['selected_words'], pro['native_tables'], 1)
    assert pack(p, request()).coverage_complete
    assert pack(p, request('별도')).coverage_complete
    assert not pack(p, request('')).coverage_complete


def test_native_merged_scope_geometry_without_rowspan_reuses_row_groups():
    p = scoped_page()
    for c in p.extraction.provenance['native_tables'][0]['cells']:
        c.pop('rowspan', None)
    pro = p.extraction.provenance
    p.extraction.table_facts = extract_cell_facts(p.final_text, pro['selected_words'], pro['native_tables'], 1)
    assert pack(p, request()).coverage_complete
    assert pack(p, request('별도')).coverage_complete
