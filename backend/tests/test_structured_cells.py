"""Extraction regression: observed cells, never company-specific answers."""
from copy import deepcopy

from app.fact_fusion import serialize_groups
from app.structured_cells import extract_cell_facts, cell_fact_valid, unit_compatible


def observed(entries, source='native'):
    return serialize_groups([[dict(text=t, bbox=b, source=source, confidence=99,
                                  line_id=str(i)) for i, (t, b) in enumerate(entries)]])[:2]


def test_vertical_period_comparison_requires_literal_full_year_confirmation():
    text, words = observed([
        ('2022년', [0, 0, 35, 10]), ('2023년', [40, 0, 75, 10]),
        ('신규 리스크인수율', [100, 30, 180, 40]),
        ("'22년", [100, 50, 125, 60]), ('4.1%', [150, 50, 180, 60]),
        ("'23년", [100, 70, 125, 80]), ('3.9%', [150, 70, 180, 80]),
    ])
    # Remote full years cannot silently turn the observed two-digit years into 20xx.
    assert not extract_cell_facts(text, words, [], 1)


def test_vertical_full_years_preserve_primitive_and_derived_comparison():
    text, words = observed([
        ('신규 리스크인수율', [0, 0, 110, 12]),
        ('2022년', [0, 22, 40, 34]), ('4.1%', [60, 22, 85, 34]),
        ('2023년', [0, 44, 40, 56]), ('3.9%', [60, 44, 85, 56]),
    ])
    facts = extract_cell_facts(text, words, [], 1)
    assert {(f['period'], f['unit'], f['value']) for f in facts} == {
        ('2022년', '%', '4.1%'), ('2023년', '%', '3.9%')}
    newer = next(f for f in facts if f['period'] == '2023년')
    assert newer['comparison_cell']['value'] == '4.1%'
    assert newer['row_id'] == facts[0]['row_id']
    assert len({f['column_id'] for f in facts}) == 2
    assert all(cell_fact_valid(f, text, words) for f in facts)
    damaged = deepcopy(newer)
    damaged['comparison_cell']['unit'] = '원'
    assert not cell_fact_valid(damaged, text, words)
    from app.evidence_requirements import table_requirements
    requirement=table_requirements('표에서 2023년 신규 리스크인수율은 2022년과 비교해 얼마인가?')[0]
    assert requirement['entity']=='신규'


def cell_grid():
    tokens = [
        ['지표', '단위', '2025A', '2026F'],
        ['매출액', '십억원', '101', '112'],
        ['영업이익률', '%', '7.1', '7.3'],
        ['EPS', '원', '810', '910'],
    ]
    entries = []; cells = []
    for r, row in enumerate(tokens):
        for c, token in enumerate(row):
            box = [c*100, r*24, c*100+85, r*24+16]
            entries.append((token, [box[0]+2, box[1]+2, box[0]+2+len(token)*7, box[3]-2]))
            cells.append(dict(row=r, column=c, text=token, bbox=box))
    text, words = observed(entries)
    return text, words, [dict(index=0, bbox=[0, 0, 385, 88], cells=cells,
                             row_count=4, column_count=4)]


def test_explicit_unit_column_never_leaks_between_metrics():
    text, words, tables = cell_grid()
    facts = extract_cell_facts(text, words, tables, 1)
    assert len(facts) == 6
    assert {(f['metric'], f['unit']) for f in facts} == {
        ('매출액', '십억원'), ('영업이익률', '%'), ('EPS', '원')}
    assert all(cell_fact_valid(f, text, words, tables) for f in facts)
    future = next(f for f in facts if f['metric'] == '매출액' and f['period'] == '2026F')
    assert future['comparison_cell']['period'] == '2025A'
    assert future['comparison_cell']['value'] == '101'
    assert all(text[s['char_start']:s['char_end']] == s['quote'] for s in future['source_spans'])


def test_metric_unit_compatibility_rejects_cross_family_and_unknown():
    assert not unit_compatible('영업이익', '%')
    assert not unit_compatible('영업이익률', '십억원')
    assert unit_compatible('EPS', '원')
    assert not unit_compatible('EPS', '조원')
    assert unit_compatible('인원', '명')
    assert not unit_compatible('인원', '원')


def test_tampered_column_and_missing_comparison_cannot_be_complete():
    from app.evidence_requirements import table_requirements, fact_requirement_match
    text, words, tables = cell_grid()
    f = next(f for f in extract_cell_facts(text, words, tables, 1)
             if f['metric'] == '매출액' and f['period'] == '2026F')
    requirement = table_requirements('표의 2026F 매출액을 2025A와 비교해줘')[0]
    assert fact_requirement_match(requirement, f)[0]
    missing = deepcopy(f); missing['comparison_cell'] = None
    assert not fact_requirement_match(requirement, missing)[0]
    damaged = deepcopy(f); damaged['column_id'] = 'elsewhere'
    assert not cell_fact_valid(damaged, text, words, tables)


def test_mixed_declaration_does_not_assign_units_by_list_position():
    text, words, tables = cell_grid()
    # Remove explicit unit cells. No amount unit is inferred from the table's
    # mixed list, and a nearby ratio unit does not fill the missing amount unit.
    words = [w for w in words if not (100 <= w['bbox'][0] < 200 and w['bbox'][1] > 20)]
    assert not extract_cell_facts(text, words, tables, 1)


def test_metric_unit_mismatch_is_rejected_during_construction():
    text, words, tables = cell_grid()
    for w in words:
        if w['text'] == '십억원':
            w['text'] = '%'
    # Original-text integrity is separately checked; the extractor already
    # refuses cross-family units even before that check.
    facts = extract_cell_facts(text, words, tables, 1)
    assert not any(f['metric'] == '매출액' for f in facts)


def test_merged_header_preserves_column_membership_and_comparison():
    from app.paddle_tables import decode_tables
    entries = [('지표', [0, 0, 90, 18]), ('(십억원)', [0, 20, 90, 38]),
        ('2Q28F', [100, 0, 270, 18]), ('New', [100, 20, 170, 38]),
        ('Old', [200, 20, 270, 38]), ('영업이익', [0, 40, 90, 58]),
        ('13', [100, 40, 170, 58]), ('15', [200, 40, 270, 58]),
        ('매출액', [0, 60, 90, 78]), ('100', [100, 60, 170, 78]), ('110', [200, 60, 270, 78])]
    text, words = observed([(t,[b[0]+2,b[1]+2,b[2]-2,b[3]-2]) for t,b in entries], 'paddle_structure')
    raw={'table_res_list':[dict(pred_html='<table><tr><td>지표</td><td colspan="2">2Q28F</td></tr>'
        '<tr><td>(십억원)</td><td>New</td><td>Old</td></tr>'
        '<tr><td>영업이익</td><td>13</td><td>15</td></tr>'
        '<tr><td>매출액</td><td>100</td><td>110</td></tr></table>',
        cell_box_list=[b for _,b in entries])]} # Boxes are physical-cell order.
    # Put boxes in the same order as HTML (heading spans two columns).
    raw['table_res_list'][0]['cell_box_list']=[entries[i][1] for i in [0,2,1,3,4,5,6,7,8,9,10]]
    tables=decode_tables(raw,1,1)
    assert tables and tables[0]['column_count']==3
    facts=extract_cell_facts(text,words,tables,1)
    f=next(f for f in facts if f['metric']=='영업이익' and f['column_name']=='New')
    assert (f['period'],f['value'],f['unit']) == ('2Q28F','13','십억원')
    assert f['comparison_cell']['label']=='Old' and f['comparison_cell']['value']=='15'
    assert cell_fact_valid(f,text,words,tables)


def test_verified_comparison_reaches_search_pack_with_all_source_cells():
    from hashlib import sha256
    from types import SimpleNamespace
    from uuid import uuid4
    from app.extraction_provenance import validated_stored_facts
    from app.evidence_bundle import requirements_for, build_evidence_pack
    from app.fact_fusion import PARSER_VERSION
    text,words,tables=cell_grid();facts=extract_cell_facts(text,words,tables,1)
    doc=SimpleNamespace(id=uuid4(),company_name='fixture')
    page=SimpleNamespace(id=uuid4(),document_id=doc.id,page_number=1,final_text=text,extraction=SimpleNamespace(
        parser_version=PARSER_VERSION,final_text_sha256=sha256(text.encode()).hexdigest(),
        provenance=dict(selected_words=words,native_tables=tables,paddle_tables=[],unsafe_spans=[]),
        table_facts=facts))
    chunk=SimpleNamespace(id=uuid4(),page_id=page.id,document_id=doc.id,page_number=1,
        char_start=0,char_end=len(text),content=text,section_title=None)
    valid=validated_stored_facts(page)
    assert len(valid)==6
    query='표의 2026F 매출액을 2025A와 비교해줘'
    pack,complete=build_evidence_pack(query,requirements_for(query),[((chunk.id,1.0,1,1),chunk,page,doc,1)],
        {chunk.id:valid},{})
    assert complete and len(pack)==1
    assert pack[0]['table_evidence'][0]['comparison_cell']['value']=='101'
    assert all(text[s['char_start']:s['char_end']]==s['quote'] for s in pack[0]['source_spans'])


def test_short_year_requires_same_metric_and_value_corroboration():
    entries=[('신규',[10,0,30,10]),('리스크인수율은',[32,0,95,10]),
        ('2022년',[100,0,135,10]),('4.1%에서',[138,0,175,10]),
        ('2023년',[178,0,213,10]),('3.9%로',[216,0,250,10]),
        ('신규',[150,30,170,40]),('리스크인수율',[173,30,235,40])]
    native=[dict(text=t,bbox=b,source='native',confidence=100,line_id='prose' if i<6 else 'heading')
            for i,(t,b) in enumerate(entries)]
    paddle=[dict(text=t,bbox=b,source='paddle_structure',confidence=99,line_id=str(i))
            for i,(t,b) in enumerate([('신규 리스크인수율',[150,30,235,40]),
                ("'22년",[150,50,175,60]),('4.1%',[210,50,240,60]),
                ("'23년",[150,70,175,80]),('3.9%',[210,70,240,80])])]
    text,words,_=serialize_groups([native,paddle]);facts=extract_cell_facts(text,words,[],1)
    assert len(facts)==2 and {f['period'] for f in facts}=={'2022년','2023년'}
    assert all(f['row_subject']=='신규' and cell_fact_valid(f,text,words) for f in facts)
    damaged=deepcopy(facts[0]);damaged['row_subject']='다른 사업'
    assert not cell_fact_valid(damaged,text,words)


def test_body_cell_unit_cannot_become_a_later_metrics_column_header():
    entries=[('지표',[2,2,40,14]),('2025A',[102,2,145,14]),('2026F',[202,2,245,14]),
        ('매출액',[2,26,40,38]),('31',[102,26,116,38]),('(십억원)',[120,26,185,38]),
        ('34',[202,26,216,38]),('(십억원)',[220,26,285,38]),
        ('영업이익',[2,50,50,62]),('4',[102,50,110,62]),('5',[202,50,210,62])]
    text,words=observed(entries)
    table=dict(index=0,bbox=[0,0,300,72],row_count=3,column_count=3,
        cells=[dict(row=r,column=c,bbox=[c*100,r*24,(c+1)*100,(r+1)*24],text='')
               for r in range(3) for c in range(3)])
    facts=extract_cell_facts(text,words,[table],1)
    assert any(f['metric']=='매출액' for f in facts)
    assert not any(f['metric']=='영업이익' for f in facts)
