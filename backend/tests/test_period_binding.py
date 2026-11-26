"""Independent source ownership fixtures; no sealed corpus inputs or services."""
from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest

from app.fact_fusion import PARSER_VERSION, serialize_groups
from app.structured_cells import extract_cell_facts
from app.index_admission import admit_dependencies
from app.primitive_graph import primitive_graph
from app.search import rank_rows
from tests.test_structured_cells import observed
from tests.test_index_admission import rows


def grid(headers=('2029A',), second_header=None):
    tokens = [['지표', '단위', *headers], ['매출액', '억원', *['17', '29'][:len(headers)]],
              ['영업이익', '억원', *['3', '5'][:len(headers)]]]
    if second_header:
        tokens.insert(1, ['구분', '단위', *second_header])
    entries, cells = [], []
    for r, row in enumerate(tokens):
        for c, token in enumerate(row):
            box = [c*100, r*24, c*100+85, r*24+16]
            entries.append((token, [box[0]+2, box[1]+2, box[0]+2+len(token)*7, box[3]-2]))
            cells.append(dict(row=r, column=c, text=token, bbox=box))
    text, words = observed(entries)
    return text, words, [dict(index=0, bbox=[0, 0, 385, len(tokens)*24], cells=cells,
                             row_count=len(tokens), column_count=len(tokens[0]))]


def page(data):
    text, words, tables = data
    return NS(id=uuid4(), document_id=uuid4(), page_number=1, final_text=text,
        extraction=NS(parser_version=PARSER_VERSION, final_text_sha256=sha256(text.encode()).hexdigest(),
            table_facts=extract_cell_facts(text, words, tables, 1),
            provenance=dict(selected_words=words, native_tables=tables, paddle_tables=[],
                            unsafe_spans=[], index_segments=[])))


@pytest.mark.parametrize('headers,expected', [(('2029A',), [('2029A', '17')]),
    (('2029A', '2030F'), [('2029A', '17'), ('2030F', '29')])])
def test_one_or_many_owned_headers_reach_graph_admission_and_pack(headers, expected):
    p = page(grid(headers))
    facts = [f for f in p.extraction.table_facts if f['metric'] == '매출액']
    assert [(f['period'], f['value']) for f in facts] == expected
    assert all(f['period_binding']['approved'] for f in facts)
    assert len(primitive_graph(p)['nodes']) == len(headers)*2
    groups = admit_dependencies(p)
    assert len(groups) == len(headers)*2
    assert all(g['period_binding']['approved'] for g in groups)
    query = f'표의 {headers[0]} 매출액 값은 얼마인가?'
    result = rank_rows(rows(p), query, 5, NS(available=False, unavailable_reason='offline'))
    assert result.coverage_complete
    assert result.evidence_pack[0]['table_evidence'][0]['value'] == '17'
    assert result.evidence_pack[0]['table_evidence'][0]['period_binding']['approved']
    assert all(c.content == p.final_text[c.char_start:c.char_end] for c, _, _ in rows(p))


@pytest.mark.parametrize('headers', [('2029A',), ('2029A', '2030F')])
def test_two_headers_owning_one_column_hold_even_when_statuses_agree(headers):
    p = page(grid(headers, second_header=tuple('2029F' for _ in headers)))
    assert not p.extraction.table_facts
    assert not admit_dependencies(p)
    assert not rank_rows(rows(p), '표의 2029F 매출액 값은 얼마인가?', 5,
                         NS(available=False, unavailable_reason='offline')).coverage_complete


@pytest.mark.parametrize('mutation', ['column', 'row', 'table', 'document', 'period_span', 'owner', 'status'])
def test_tampered_period_ownership_cannot_enter_dependency_or_pack(mutation):
    p = page(grid(('2029A', '2030F')))
    f = deepcopy(next(f for f in p.extraction.table_facts if f['metric'] == '매출액'))
    if mutation == 'column': f['column_id'] = 'other-column'
    elif mutation == 'row': f['value_span'] = deepcopy(next(x for x in p.extraction.table_facts if x['metric'] == '영업이익')['value_span'])
    elif mutation == 'table': f['table_id'] = 'other-table'
    elif mutation == 'document': f['document_id'] = uuid4()
    elif mutation == 'period_span': f['source_spans'] = [s for s in f['source_spans'] if s['role'] != 'period']
    elif mutation == 'owner': f['period_binding']['column'] += 1
    elif mutation == 'status': f['status'] = 'forecast'
    p.extraction.table_facts = [f]
    assert not admit_dependencies(p)
    assert not rank_rows(rows(p), '표의 2029A 매출액 값은 얼마인가?', 5,
                         NS(available=False, unavailable_reason='offline')).coverage_complete


def prose(value):
    words = [dict(text=t, bbox=[i*45, 0, i*45+40, 12], line_id='claim', source='native', confidence=100)
             for i, t in enumerate(value.split())]
    return serialize_groups([words])


def test_explicit_sentence_proof_is_rederived_before_numeric_pack():
    from app.fused_extraction import _numeric
    from app.fused_candidates import verified_numeric_candidates
    text, words, segments = prose('2030F 매출액 29억원 예상이다.')
    facts = _numeric(text, words, segments, 1)
    assert len(facts) == 1 and facts[0]['period_binding']['approved']
    p = page(grid())
    p.final_text = text
    p.extraction.final_text_sha256 = sha256(text.encode()).hexdigest()
    p.extraction.table_facts = []
    p.extraction.provenance = dict(selected_words=words, paragraph_segments=segments,
        numeric_evidence=facts, unsafe_spans=[], index_segments=[{**segments[0], 'kind': 'paragraph'}])
    chunks = rows(p)
    assert verified_numeric_candidates(chunks, '2030F 매출액 예상')[0][1]['value'] == '29'
    from app.evidence_bundle import build_evidence_pack
    from app.evidence_requirements import table_requirements
    selected = verified_numeric_candidates(chunks, '2030F 매출액 예상')
    pack, complete = build_evidence_pack('2030F 매출액 예상',
        table_requirements('2030F 매출액 예상', kind='numeric'),
        [((c.id, 1.0, 1, None), c, pg, d, 1) for c, pg, d in chunks],
        {}, {anchor: [fact] for anchor, fact in selected})
    assert complete and pack and pack[0]['numeric_evidence'][0]['value'] == '29'
    facts[0]['period_binding']['char_start'] += 1
    assert not verified_numeric_candidates(chunks, '2030F 매출액 예상')


@pytest.mark.parametrize('claim', [
    '2029A 2030F 매출액 29억원 예상이다.',
    '2029A 매출액 29억원 예상이다.',
    '2030F 매출액 29억원 실제 기록이다.',
    '2030F 매출액 예상이다. 영업이익 3억원 예상이다.',
    '2030F 매출액 29억원 영업이익 3억원 예상이다.',
])
def test_ambiguous_or_other_sentence_metric_period_never_becomes_numeric_fact(claim):
    from app.fused_extraction import _numeric
    text, words, segments = prose(claim)
    facts = _numeric(text, words, segments, 1)
    assert not facts


def multilevel():
    data = grid(('2029F', '2030F'), second_header=('New', 'Old'))
    text, words, tables = data
    # One physical parent owns exactly two explicit child columns.
    words = [w for w in words if w['text'] != '2030F']
    parent = next(w for w in words if w['text'] == '2029F')
    parent['text'] = '2031F'
    entries = [(w['text'], w['bbox']) for w in words]
    text, words = observed(entries)
    cells = tables[0]['cells']
    cells[:] = [c for c in cells if not (c['row'] == 0 and c['column'] == 3)]
    header = next(c for c in cells if c['row'] == 0 and c['column'] == 2)
    header.update(text='2031F', colspan=2, bbox=[200, 0, 385, 16])
    return text, words, tables


def test_multilevel_parent_has_literal_proof_and_distinct_child_membership():
    p = page(multilevel())
    target = [f for f in p.extraction.table_facts if f['metric'] == '매출액']
    assert [(f['period'], f['column_name'], f['value']) for f in target] == [
        ('2031F', 'New', '17'), ('2031F', 'Old', '29')]
    assert {f['period_binding']['column'] for f in target} == {2, 3}
    assert all(f['period_binding']['column_group'] == [2, 4] for f in target)
    assert len(admit_dependencies(p)) == 4
    result = rank_rows(rows(p), '표의 2031F 매출액 New 값은 얼마인가?', 5,
                       NS(available=False, unavailable_reason='offline'))
    assert result.coverage_complete and result.evidence_pack


def test_missing_header_source_and_incompatible_unit_cannot_create_fact():
    text, words, tables = grid()
    assert not extract_cell_facts(text, [w for w in words if w['text'] != '2029A'], tables, 1)
    text, words = observed([(w['text'].replace('억원', '%'), w['bbox']) for w in words])
    assert not extract_cell_facts(text, words, tables, 1)


def test_two_literal_periods_in_one_header_block_only_that_column():
    text, words, tables = grid(('2029A', '2030F'))
    header = next(w for w in words if w['text'] == '2029A')
    text, words = observed([(w['text'], w['bbox']) for w in words] + [('2029F', header['bbox'])])
    facts = extract_cell_facts(text, words, tables, 1)
    assert facts and all(f['period'] == '2030F' for f in facts)


def test_equal_text_in_another_table_is_not_period_ownership():
    p = page(grid())
    assert p.extraction.table_facts
    f = deepcopy(p.extraction.table_facts[0])
    f['period_binding']['table_bbox'] = [500, 0, 885, 72]
    p.extraction.table_facts = [f]
    assert not admit_dependencies(p)


def test_legacy_archive_is_still_source_rederived_without_new_metadata():
    p = page(grid(('2029A', '2030F')))
    archived = [{k: v for k, v in f.items() if k not in
        {'period_binding', 'unit_binding', 'scope_binding', 'comparison_cell', 'comparison_basis', 'comparison_derivation'}}
        for f in p.extraction.table_facts]
    p.extraction.parser_version = 'fact-fusion-paddle-v3'
    # Old observations retain their version and must still rederive ownership.
    for f in archived:
        f['processing_version'] = p.extraction.parser_version
    p.extraction.provenance['primitive_cells'] = archived
    p.extraction.table_facts = []
    assert len(admit_dependencies(p)) == 4
    archived[0]['column_id'] = 'forged'
    p.extraction.table_facts = []
    assert len(admit_dependencies(p)) == 3


@pytest.mark.parametrize('claim', [
    '2030F 매출액 예상이며 EPS 3억원 예상이다.',
    '2030F EPS가 증가하고 매출액 29억원 예상이다.',
    '2030F 매출액은 예상하고 다른 사업 29억원 예상이다.',
])
def test_unrelated_clause_cannot_borrow_the_only_recognized_period_metric(claim):
    from app.fused_extraction import _numeric
    text, words, segments = prose(claim)
    assert not _numeric(text, words, segments, 1)


def test_separate_explicit_actual_forecast_sentences_keep_distinct_owners():
    from app.fused_extraction import _numeric
    text, words, segments = prose('2029A 매출액 17억원 기록이다. 2030F 매출액 29억원 예상이다.')
    facts = _numeric(text, words, segments, 1)
    assert [(f['period'], f['value'], f['status']) for f in facts] == [
        ('2029A', '17', 'actual'), ('2030F', '29', 'forecast')]
    assert facts[0]['period_binding']['char_end'] <= facts[1]['period_binding']['char_start']


def test_forecast_parent_cannot_own_actual_child_header():
    text, words, tables = multilevel()
    text, words = observed([(w['text'].replace('New', '실적치'), w['bbox']) for w in words])
    for cell in tables[0]['cells']:
        if cell['text'] == 'New':cell['text'] = '실적치'
    assert all(f['column_name'] != '실적치' for f in extract_cell_facts(text, words, tables, 1))


def test_new_observation_cannot_remove_period_binding_to_downgrade_validation():
    p = page(grid())
    p.extraction.table_facts[0].pop('period_binding')
    p.extraction.table_facts = p.extraction.table_facts[:1]
    assert not admit_dependencies(p)


@pytest.mark.parametrize('conflict', ['2030년2분기', '예상'])
def test_unsupported_period_or_forecast_header_cannot_hide_a_conflicting_owner(conflict):
    p = page(grid(('2029A',), second_header=(conflict,)))
    assert not p.extraction.table_facts
    assert not admit_dependencies(p)


def test_new_numeric_observation_missing_binding_never_reaches_pack():
    from app.fused_extraction import _numeric
    from app.fused_candidates import verified_numeric_candidates
    text, words, segments = prose('2030F 매출액 29억원 예상이다.')
    facts = _numeric(text, words, segments, 1)
    facts[0].pop('period_binding')
    p = page(grid())
    p.final_text = text
    p.extraction.final_text_sha256 = sha256(text.encode()).hexdigest()
    p.extraction.table_facts = []
    p.extraction.provenance = dict(selected_words=words, paragraph_segments=segments,
        numeric_evidence=facts, unsafe_spans=[], index_segments=[{**segments[0], 'kind': 'paragraph'}])
    assert not verified_numeric_candidates(rows(p), '2030F 매출액 예상')


def test_two_unlabelled_amounts_cannot_claim_one_sentence_metric():
    from app.fused_extraction import _numeric
    text, words, segments = prose('2030F 매출액 17억원 29억원 예상이다.')
    assert not _numeric(text, words, segments, 1)


def test_year_shaped_amount_in_metric_row_is_value_not_a_second_header():
    text, words, tables = grid()
    text, words = observed([(w['text'].replace('17', '2029'), w['bbox']) for w in words])
    facts = extract_cell_facts(text, words, tables, 1)
    assert {(f['metric'], f['period'], f['value']) for f in facts} == {
        ('매출액', '2029A', '2029'), ('영업이익', '2029A', '3')}


def test_unsupported_second_sentence_period_is_still_ambiguity():
    from app.fused_extraction import _numeric
    text, words, segments = prose('2029년과 2030F 매출액 29억원 예상이다.')
    assert not _numeric(text, words, segments, 1)
