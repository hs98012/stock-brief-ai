"""Independent unit ownership fixtures; no corpus/gold coordinates."""
from copy import deepcopy
import pytest
from types import SimpleNamespace as NS
from app.structured_cells import extract_cell_facts
from app.index_admission import admit_dependencies
from app.primitive_graph import primitive_graph
from app.search import rank_rows
from tests.test_structured_cells import observed
from tests.test_period_binding import page
from tests.test_index_admission import rows


def fixture(mode, extra=None):
    entries, cells = [], []
    matrix = [['지표', '단위', '2032A'], ['매출액', '', '41'], ['영업이익', '', '7']]
    if mode == 'cell':
        matrix[1][2] = '41억원'; matrix[2][2] = '7억원'
    elif mode == 'row':
        matrix[1][1] = matrix[2][1] = '억원'
    elif mode == 'mixed':
        matrix[1][1] = '조원'; matrix[2][1] = '억원'
    elif mode == 'column':
        matrix[0][2] = '2032A 억원'
    elif mode == 'english':
        matrix[1][1] = matrix[2][1] = 'million USD'
    elif mode == 'composite':
        matrix[1][1] = matrix[2][1] = '조 원'
    for r, row in enumerate(matrix):
        for c, token in enumerate(row):
            cells.append(dict(row=r, column=c, text=token, bbox=[c*120,r*32,c*120+110,r*32+26]))
            x = c*120+3
            for part in token.split():
                entries.append((part, [x,r*32+3,x+len(part)*7,r*32+19]))
                x += len(part)*7+3
    if mode in {'table','table_label'}:
        entries.append(('(단위:억원)' if mode=='table_label' else '(억원)', [3,-19,48,-5]))
    if extra: entries.extend(extra)
    text, words = observed(entries)
    return text, words, [dict(index=0,bbox=[0,0,350,96], row_count=3,column_count=3,cells=cells)]


@pytest.mark.parametrize('mode', ['cell','row','column','table','composite','mixed','english','table_label'])
def test_owned_units_reach_graph_pack_coverage(mode):
    p = page(fixture(mode))
    assert len(p.extraction.table_facts) == 2
    assert len(primitive_graph(p)['nodes']) == 2
    groups = admit_dependencies(p)
    assert len(groups) == 2
    assert all(g['unit_binding']['approved'] for g in groups)
    result = rank_rows(rows(p), '표의 2032A 매출액 값은 얼마인가?', 5,
                       NS(available=False, unavailable_reason='offline'))
    assert result.coverage_complete
    f = result.evidence_pack[0]['table_evidence'][0]
    assert f['unit_binding']['approved'] and f['period_binding']['approved']
    if mode == 'composite':
        assert [c['quote'] for c in f['unit_binding']['unit_dependency']['components']] == ['조','원']
    if mode == 'english':
        assert [c['quote'] for c in f['unit_binding']['unit_dependency']['components']] == ['million','USD']
    if mode == 'mixed':
        assert {f['unit'] for f in p.extraction.table_facts} == {'조원','억원'}


@pytest.mark.parametrize('mode,extra', [
    ('table', [('(조원)',[65,-19,110,-5])]),
    ('row', [('(조원)',[3,-19,48,-5])]),
    ('column', [('조원',[294,3,322,19])]),
    ('cell', [('조원',[300,35,328,51])]),
])
def test_multiple_applicable_declarations_never_choose_first(mode, extra):
    p = page(fixture(mode, extra))
    assert not any(f['metric'] == '매출액' for f in p.extraction.table_facts)
    admit_dependencies(p)
    assert not rank_rows(rows(p),'표의 2032A 매출액 값은 얼마인가?',5,
        NS(available=False,unavailable_reason='offline')).coverage_complete


@pytest.mark.parametrize('mutation', ['source_delete','component_delete','owner','scope',
                                      'canonical','source_tamper','proof_delete','foreign_row','foreign_column'])
def test_mutated_proof_cannot_reach_admission_or_complete(mutation):
    p = page(fixture('composite'))
    f = deepcopy(p.extraction.table_facts[0])
    proof = f['unit_binding']
    if mutation == 'source_delete': f['source_spans'] = [s for s in f['source_spans'] if s['role'] != 'unit']
    elif mutation == 'component_delete': proof['unit_dependency']['components'].pop()
    elif mutation == 'owner': proof['row_id'] = 'foreign'
    elif mutation == 'scope': proof['context'] = {'scope':'foreign'}
    elif mutation == 'canonical': f['unit'] = '원'
    elif mutation == 'source_tamper': proof['unit_span']['quote'] = '억원'
    elif mutation == 'proof_delete': f.pop('unit_binding')
    elif mutation == 'foreign_row':
        foreign = p.extraction.table_facts[1]['unit_span']
        f['source_spans'] = [{**foreign,'role':'unit'} if s['role']=='unit' else s for s in f['source_spans']]
    elif mutation == 'foreign_column': proof['column_id'] = 'foreign'
    p.extraction.table_facts = [f]
    assert not admit_dependencies(p)
    assert not rank_rows(rows(p),'표의 2032A 매출액 값은 얼마인가?',5,
        NS(available=False,unavailable_reason='offline')).coverage_complete


def test_unspecified_unit_is_never_inferred():
    p = page(fixture('none'))
    assert not p.extraction.table_facts and not admit_dependencies(p)


@pytest.mark.parametrize('declaration', ['(억원,%)','(단위:억원,%)'])
@pytest.mark.parametrize('mode', ['row','cell','column','table'])
def test_unmapped_mixed_table_header_cannot_be_overridden_by_a_local_unit(mode, declaration):
    p = page(fixture(mode, [(declaration,[52,-19,108,-5])]))
    assert not p.extraction.table_facts


@pytest.mark.parametrize('unit', ['조원','원','%pt'])
def test_other_value_column_cannot_supply_the_missing_unit(unit):
    text, words, tables = fixture('none', [(unit,[125,3,155,19])])
    # Literal unit is in a different header column, without a period owner.
    p = page((text,words,tables))
    assert not p.extraction.table_facts


def test_missing_original_component_observation_holds():
    text,words,tables = fixture('composite')
    words = [w for w in words if w['text'] != '원']
    p = page((text,words,tables))
    assert not p.extraction.table_facts and not admit_dependencies(p)


def test_new_topology_fallback_cannot_bypass_mixed_unit_hold():
    from app.native_tables import extract_native_facts
    from app.fact_fusion import PARSER_VERSION
    from app.unit_validation import validate_unit
    text,words,tables = fixture('row', [('(조원)',[3,-19,48,-5])])
    candidates = extract_native_facts(text,words,tables,1)
    assert candidates
    for f in candidates:
        f['processing_version'] = PARSER_VERSION
        assert not validate_unit(f,text,words,tables)['approved']


def test_external_unit_cannot_borrow_a_neighboring_table_declaration():
    text,words,tables = fixture('table')
    tables.append(dict(bbox=[0,-24,110,-2],row_count=1,column_count=1,
        cells=[dict(row=0,column=0,text='(억원)',bbox=[0,-24,110,-2])]))
    p = page((text,words,tables))
    assert not p.extraction.table_facts and not admit_dependencies(p)


def test_equal_canonical_units_do_not_make_two_owners_unique():
    p = page(fixture('table', [('(억원)',[65,-19,110,-5])]))
    assert not p.extraction.table_facts and not admit_dependencies(p)


def test_percentage_point_is_not_the_percentage_unit():
    from app.unit_validation import validate_unit
    text,words = observed([('%pt',[0,0,24,14]),('1.7',[30,0,50,14])])
    spans=[dict(role=role,char_start=w['char_start'],char_end=w['char_end'],
        quote=w['text'],bbox=w['bbox'],source=w['source'])
        for role,w in [('unit',words[0]),('value',words[1])]]
    assert not validate_unit(dict(unit='%',source_spans=spans),text,words)['approved']
