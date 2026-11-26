"""Full literal unit spans; geometry failures must remain incomplete."""
from copy import deepcopy
from pathlib import Path
import json

import pytest

from app.unit_validation import validate_unit
from app.structured_cells import extract_cell_facts, cell_fact_valid
from app.numeric_evidence import extract_numeric_evidence
from tests.test_structured_cells import observed, cell_grid


def test_continuous_compound_surface_is_preserved_in_numeric_prose():
    text, words = observed([('2026F 영업이익은 1.2조 원으로 예상한다.', [0, 0, 230, 16])])
    facts = extract_numeric_evidence(text, words, 1, [])
    assert len(facts) == 1
    fact = facts[0]
    assert (fact['unit_surface'], fact['canonical_unit'], fact['unit']) == ('조 원', '조원', '조원')
    for role in ('unit_span', 'value_span'):
        s = fact[role]
        assert text[s['char_start']:s['char_end']] == s['quote']
        assert s['bbox'] == words[0]['bbox']  # observed word box, no inferred character box


@pytest.mark.parametrize('surface,canonical', [('조 원', '조원'), ('억원', '억원'), ('천원', '천원'), ('%', '%')])
def test_same_cell_full_unit_and_inline_value(surface, canonical):
    entries = [('지표', [2, 2, 50, 16]), ('2025A', [102, 2, 150, 16]), ('2026F', [202, 2, 250, 16]),
        ('영업이익률' if canonical == '%' else '영업이익', [2, 26, 75, 40]),
        ('1.2'+surface, [102, 26, 170, 40]), ('1.4'+surface, [202, 26, 270, 40])]
    # Percent keeps the existing value-suffix chart/table representation.
    if canonical == '%':
        entries = entries[:4] + [('1.2', [102, 26, 120, 40]), ('%', [124, 26, 132, 40]),
                                ('1.4', [202, 26, 220, 40]), ('%', [224, 26, 232, 40])]
    text, words = observed(entries)
    table = dict(bbox=[0, 0, 300, 48], row_count=2, column_count=3,
        cells=[dict(row=r, column=c, text='', bbox=[c*100, r*24, (c+1)*100, (r+1)*24])
               for r in range(2) for c in range(3)])
    facts = extract_cell_facts(text, words, [table], 1)
    assert len(facts) == 2
    assert all(f['unit_surface'] == surface and f['canonical_unit'] == canonical
               and f['unit_source'] == 'same_cell' for f in facts)
    assert all(cell_fact_valid(f, text, words, [table]) for f in facts)


@pytest.mark.parametrize('surface', ['조 원', '억원', '천원'])
def test_suffix_only_span_is_rejected(surface):
    text, words = observed([(surface, [0, 0, 40, 14]), ('1.2', [50, 0, 75, 14])])
    start = text.index('원')
    fact = dict(unit='원', source_spans=[dict(role='unit', char_start=start, char_end=start+1,
        quote='원', bbox=words[0]['bbox'], source='native'), dict(role='value',
        char_start=words[1]['char_start'], char_end=words[1]['char_end'], quote='1.2',
        bbox=words[1]['bbox'], source='native')])
    audit = validate_unit(fact, text, words)
    assert not audit['approved'] and audit['rejection_reason'] == 'unit_suffix_conflict'
    assert audit['conflicting_unit']['quote'] == surface


def test_row_unit_cannot_be_borrowed_from_another_row_or_value_column():
    text, words, tables = cell_grid()
    fact = next(f for f in extract_cell_facts(text, words, tables, 1) if f['metric'] == '매출액')
    bad = deepcopy(fact)
    other = next(w for w in words if w['text'] == '원')
    bad.pop('unit_surface'); bad.pop('canonical_unit'); bad['unit'] = '원'
    bad['source_spans'] = [s for s in bad['source_spans'] if s['role'] != 'unit'] + [
        dict(role='unit', char_start=other['char_start'], char_end=other['char_end'],
             quote=other['text'], bbox=other['bbox'], source=other['source'])]
    assert not validate_unit(bad, text, words, tables)['approved']
    # Unit in a different value column is not a row-wide declaration.
    table = deepcopy(tables[0])
    table['cells'][5]['column'] = 3
    table['cells'][5]['text'] = '99 십억원'
    assert not validate_unit(fact, text, words, [table])['approved']


def test_column_header_requires_actual_same_column_topology():
    entries = [('지표', [2, 2, 50, 16]), ('2025A', [102, 2, 150, 16]),
        ('십억원', [102, 18, 150, 30]), ('매출액', [2, 42, 50, 56]), ('71', [102, 42, 130, 56])]
    text, words = observed(entries)
    unit, value, header = words[2], words[4], words[1]
    spans = [dict(role=role, char_start=w['char_start'], char_end=w['char_end'],
                  quote=w['text'], bbox=w['bbox'], source=w['source'])
             for role, w in [('unit', unit), ('value', value), ('columns', header)]]
    fact = dict(unit='십억원', source_spans=spans)
    table = dict(bbox=[0, 0, 200, 60], cells=[
        dict(row=0, column=1, bbox=[100, 0, 200, 36], text='2025A 십억원'),
        dict(row=1, column=1, bbox=[100, 36, 200, 60], text='71')])
    assert validate_unit(fact, text, words, [table])['unit_source'] == 'column_header'
    bad = deepcopy(table); bad['cells'][0]['column'] = 2
    assert not validate_unit(fact, text, words, [bad])['approved']
    bad = deepcopy(table); bad['cells'][0]['colspan'] = 2
    assert not validate_unit(fact, text, words, [bad])['approved']
    assert not validate_unit(fact, text, words)['approved']


def test_challenge_suffix_facts_cannot_reach_graph_or_complete_pack():
    from types import SimpleNamespace as NS
    from hashlib import sha256
    from uuid import uuid4
    from app.extraction_provenance import validated_stored_facts
    from app.primitive_graph import comparison_candidates
    from app.evidence_bundle import build_evidence_pack, requirements_for
    path = Path(__file__).resolve().parents[2]/'evals/results/paddle/graph-new-observations-20261002.json'
    if not path.exists():
        pytest.skip('local immutable challenge observations unavailable')
    observed_cases = json.loads(path.read_text())['cases']
    case = observed_cases[0]
    text = case['final_text']; doc = NS(id=uuid4())
    page = NS(id=uuid4(), document_id=doc.id, page_number=case['page'], final_text=text,
        extraction=NS(parser_version='fact-fusion-paddle-v3', final_text_sha256=sha256(text.encode()).hexdigest(),
                      provenance=case['provenance'], table_facts=case['table_facts']))
    audits=[]; facts=validated_stored_facts(page, unit_audit=audits)
    rejected = [a for a in audits if a['rejection_reason']=='unit_suffix_conflict' and a['value']=='43.4']
    assert rejected and rejected[0]['conflicting_unit']['quote']=='조 원'
    question='표에서 2022년 영업이익을 2023년과 비교해줘.'
    req=requirements_for(question)
    assert not comparison_candidates(page, req)
    chunk=NS(id=uuid4(), page_id=page.id, document_id=doc.id, page_number=page.page_number,
             char_start=0, char_end=len(text), content=text, section_title=None)
    pack,complete=build_evidence_pack(question, req, [((chunk.id,1,1,1),chunk,page,doc,1)],
                                      {chunk.id:facts}, {})
    assert complete is False


def test_no_corpus_shortcuts_in_unit_validator():
    code = (Path(__file__).resolve().parents[1]/'app/unit_validation.py').read_text()
    for forbidden in ['삼성', '현대차', 'POSCO', '.pdf', 'question_id', '43.4', '6.6']:
        assert forbidden not in code


def test_split_tokens_in_one_cell_preserve_full_surface_span():
    entries=[('지표',[2,2,50,16]),('2025A',[102,2,150,16]),('2026F',[202,2,250,16]),
        ('영업이익',[2,26,75,40]),('1.2조',[102,26,130,40]),('원',[133,26,141,40]),
        ('1.4조',[202,26,230,40]),('원',[233,26,241,40])]
    text,words=observed(entries)
    table=dict(bbox=[0,0,300,48],row_count=2,column_count=3,
        cells=[dict(row=r,column=c,text='',bbox=[c*100,r*24,(c+1)*100,(r+1)*24])
               for r in range(2) for c in range(3)])
    facts=extract_cell_facts(text,words,[table],1)
    assert len(facts)==2
    assert all(f['unit_surface']=='조 원' and f['canonical_unit']=='조원' for f in facts)
    assert all(len(f['unit_span']['boxes'])==2 and cell_fact_valid(f,text,words,[table]) for f in facts)


def test_percent_suffix_in_same_cell_keeps_literal_value():
    entries=[('지표',[2,2,50,16]),('2025A',[102,2,150,16]),('2026F',[202,2,250,16]),
        ('영업이익률',[2,26,75,40]),('3.1%',[102,26,145,40]),('3.4%',[202,26,245,40])]
    text,words=observed(entries)
    table=dict(bbox=[0,0,300,48],row_count=2,column_count=3,
        cells=[dict(row=r,column=c,text='',bbox=[c*100,r*24,(c+1)*100,(r+1)*24])
               for r in range(2) for c in range(3)])
    facts=extract_cell_facts(text,words,[table],1)
    assert len(facts)==2 and {f['value'] for f in facts}=={'3.1%','3.4%'}
    assert all(f['unit_surface']=='%' and cell_fact_valid(f,text,words,[table]) for f in facts)


def test_parenthesized_unit_in_metric_cell_is_a_verified_row_declaration():
    text,words=observed([('영업이익',[2,26,75,40]),('(십억원)',[2,26,75,40]),
        ('2026F',[102,2,150,16]),('23',[102,26,130,40])])
    spans=[dict(role=role,char_start=w['char_start'],char_end=w['char_end'],quote=w['text'],
                bbox=w['bbox'],source=w['source']) for role,w in
           [('row',words[0]),('unit',words[1]),('columns',words[2]),('value',words[3])]]
    table=dict(bbox=[0,0,200,48],cells=[
        dict(row=0,column=1,text='2026F',bbox=[100,0,200,24]),
        dict(row=1,column=0,text='영업이익 (십억원)',bbox=[0,24,100,48]),
        dict(row=1,column=1,text='23',bbox=[100,24,200,48])])
    audit=validate_unit(dict(unit='십억원',source_spans=spans),text,words,[table])
    assert audit['approved'] and audit['unit_source']=='same_row'


def test_full_span_cannot_be_labeled_as_its_short_suffix():
    text,words=observed([('억원',[0,0,24,14]),('12',[30,0,44,14])])
    spans=[dict(role=role,char_start=w['char_start'],char_end=w['char_end'],
                quote=w['text'],bbox=w['bbox'],source=w['source'])
           for role,w in [('unit',words[0]),('value',words[1])]]
    audit=validate_unit(dict(unit='원',source_spans=spans),text,words)
    assert audit['rejection_reason']=='unit_suffix_conflict'
    assert audit['conflicting_unit']['quote']=='억원'


def test_overlapping_compound_in_another_observation_stream_blocks_suffix():
    from app.fact_fusion import serialize_groups
    native=[dict(text=t,bbox=b,source='native',confidence=100,line_id=str(i))
            for i,(t,b) in enumerate([('원',[10,0,20,14]),('12',[30,0,44,14])])]
    paddle=[dict(text='조원',bbox=[0,0,20,14],source='paddle_structure',confidence=99,line_id='p')]
    text,words,_=serialize_groups([native,paddle])
    spans=[dict(role=role,char_start=w['char_start'],char_end=w['char_end'],quote=w['text'],
                bbox=w['bbox'],source=w['source']) for role,w in [('unit',words[0]),('value',words[1])]]
    audit=validate_unit(dict(unit='원',source_spans=spans),text,words)
    assert audit['rejection_reason']=='unit_suffix_conflict'
    assert audit['conflicting_unit']['source']=='paddle_structure'


def test_legacy_comparison_metadata_remains_valid_but_source_tampering_does_not():
    from app.unit_validation import METADATA
    text,words=observed([('신규 리스크인수율',[0,0,110,12]),
        ('2022년',[0,22,40,34]),('4.1%',[60,22,85,34]),
        ('2023년',[0,44,40,56]),('3.9%',[60,44,85,56])])
    def legacy(value):
        if isinstance(value,dict):return {k:legacy(v) for k,v in value.items() if k not in METADATA}
        if isinstance(value,list):return [legacy(v) for v in value]
        return value
    fact=legacy(extract_cell_facts(text,words,[],1)[0])
    assert cell_fact_valid(fact,text,words)
    broken=deepcopy(fact)
    broken['comparison_derivation']['primitive_cells'][1]['bbox']=[0,300,40,310]
    assert not cell_fact_valid(broken,text,words)
