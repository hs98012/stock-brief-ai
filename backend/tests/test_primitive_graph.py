"""Query period pairs over literal cells; no corpus/answer shortcuts."""
import hashlib
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.structured_cells import extract_cell_facts
from app.evidence_requirements import table_requirements, fact_requirement_match
from app.primitive_graph import primitive_graph, comparison_candidates, comparison_fact_valid, period_identity
from tests.test_structured_cells import observed


def page_grid(periods=('2022','2023','2024'), metrics=('영업이익','영업이익률')):
    tokens=[['지표','단위',*periods]]
    for i,metric in enumerate(metrics):
        tokens.append([metric,'%' if metric.endswith('률') else '십억원',
                       *[str(10+i+j) for j in range(len(periods))]])
    entries=[];cells=[]
    for r,row in enumerate(tokens):
        for c,t in enumerate(row):
            b=[c*110,r*24,c*110+105,r*24+20]
            entries.append((t,[b[0]+1,b[1]+1,b[2]-1,b[3]-1]))
            cells.append(dict(row=r,column=c,text=t,bbox=b))
    text,words=observed(entries)
    tables=[dict(bbox=[0,0,len(tokens[0])*110,len(tokens)*24],cells=cells,
                 row_count=len(tokens),column_count=len(tokens[0]))]
    facts=extract_cell_facts(text,words,tables,1)
    return SimpleNamespace(id=uuid4(),document_id=uuid4(),page_number=1,final_text=text,
        extraction=SimpleNamespace(parser_version=facts[0]['processing_version'],
            final_text_sha256=hashlib.sha256(text.encode()).hexdigest(),table_facts=facts,
            provenance={'selected_words':words,'native_tables':tables,'paddle_tables':[],
                        'unsafe_spans':[]}))


def test_three_period_table_selects_only_requested_pair():
    page=page_grid()
    req=table_requirements('표의 2023년과 2024년 영업이익을 비교해줘.')
    assert [r['period'] for r in req]==['2023','2024']
    assert all(r['requested_periods']==['2023','2024'] for r in req)
    graph=primitive_graph(page)
    assert len(graph['nodes'])==6 and graph['edges']
    facts=comparison_candidates(page,req)
    assert len(facts)==2
    assert {(f['period'],f['comparison_cell']['period']) for f in facts}=={
        ('2023','2024'),('2024','2023')}
    assert all(comparison_fact_valid(f,page) for f in facts)
    assert all(f['metric']=='영업이익' for f in facts)
    for r in req:assert any(fact_requirement_match(r,f)[0] for f in facts)


@pytest.mark.parametrize('raw,year,quarter,status,qualifier,fiscal',[
    ('2024',2024,None,'unspecified',None,False),('2024A',2024,None,'actual','A',False),
    ('2024F',2024,None,'forecast','F',False),('FY2024',2024,None,'unspecified',None,True),
    ('4Q24',2024,4,'unspecified',None,False),('4Q24P',2024,4,'preliminary','P',False)])
def test_period_identity_preserves_every_qualifier(raw,year,quarter,status,qualifier,fiscal):
    p=period_identity(raw)
    assert p==dict(raw=raw,year=year,quarter=quarter,status=status,qualifier=qualifier,fiscal=fiscal)


@pytest.mark.parametrize('requested', ['2024','2025A','FY2025','1Q25F'])
def test_wrong_qualifier_missing_period_never_links(requested):
    page=page_grid(('2024A','2025F','2026F'))
    assert not comparison_candidates(page,table_requirements(f'표의 {requested}와 2026F 영업이익을 비교해줘.'))


def test_forecast_pair_keeps_qualifier_and_original_spans():
    page=page_grid(('2024A','2025F','2026F'))
    facts=comparison_candidates(page,table_requirements('표의 2025F와 2026F 영업이익을 비교해줘.'))
    assert len(facts)==2
    assert all(f['graph_comparison']['lhs_period']['status']=='forecast' for f in facts)
    assert all(page.final_text[s['char_start']:s['char_end']]==s['quote']
               for f in facts for s in f['source_spans'])
    bad=deepcopy(facts[0]);bad['comparison_cell']['value']='999'
    assert not comparison_fact_valid(bad,page)


def test_unknown_or_incompatible_units_never_make_edges():
    from app.primitive_graph import relation
    page=page_grid()
    nodes=primitive_graph(page)['nodes']
    a,b=[n for n in nodes if n['metric']=='영업이익'][:2]
    assert relation(a,b)['same_unit']
    for unit in ['%','',None,'억원']:
        wrong={**b,'unit':unit}
        assert not relation(a,wrong)['linkable']
    different_metric={**b,'metric':'영업이익률'}
    assert not relation(a,different_metric)['same_metric']


def test_row_id_is_neither_sufficient_nor_required():
    from app.primitive_graph import relation
    nodes=primitive_graph(page_grid())['nodes']
    a,b=[n for n in nodes if n['metric']=='영업이익'][:2]
    assert relation(a,{**b,'row_id':'another-extraction-row'})['linkable']
    wrong=deepcopy(b);wrong['cell_geometry']['label_cell']=[0,500,100,520]
    assert not relation(a,wrong)['linkable']
    assert not relation(a,{**b,'table_id':'another-table'})['linkable']


def test_invalid_cell_cannot_enter_graph_or_fill_missing_period():
    page=page_grid()
    page.extraction.table_facts[1]['value']='888'
    nodes=primitive_graph(page)['nodes']
    assert not any(n['value']=='888' for n in nodes)
    assert not comparison_candidates(page,table_requirements('표의 2023과 2024 영업이익을 비교해줘.'))


def test_single_period_and_consensus_paths_are_unchanged():
    page=page_grid()
    assert not comparison_candidates(page,table_requirements('표의 2024 영업이익을 알려줘.'))
    assert not comparison_candidates(page,table_requirements('표의 2024 영업이익과 컨센서스를 비교해줘.'))


def test_pack_completes_only_with_both_validated_requested_cells():
    from app.search import rank_rows
    page=page_grid()
    document=SimpleNamespace(id=page.document_id,filename='fixture.pdf',company_name='',
        stock_code=None,issuer='',published_at=None,document_type='broker_report')
    chunk=SimpleNamespace(id=uuid4(),page_id=page.id,document_id=document.id,page_number=1,
        char_start=0,char_end=len(page.final_text),content=page.final_text,section_title=None,embedding=None)
    page.extraction.provenance['index_segments']=[dict(char_start=0,char_end=len(page.final_text),kind='fact_quote')]
    provider=SimpleNamespace(available=False,unavailable_reason='fixture')
    question='표의 2023과 2024 영업이익을 비교해줘.'
    result=rank_rows([(chunk,page,document)],question,5,provider)
    assert result.coverage_complete and len(result.evidence_pack)==1
    assert len(result.evidence_pack[0]['requirement_ids'])==2
    assert all(page.final_text[s['char_start']:s['char_end']]==s['quote']
        for s in result.evidence_pack[0]['source_spans'])
    page.extraction.table_facts=[f for f in page.extraction.table_facts if f['period']!='2024']
    result=rank_rows([(chunk,page,document)],question,5,provider)
    assert result.coverage_complete is False and result.evidence_pack==[]


def test_multilevel_parent_year_child_columns_do_not_cross_facets():
    # Physical merged headers retain parent membership and logical columns.
    entries=[('(십억원)',[0,0,90,18]),('2023',[100,0,290,18]),('2024',[300,0,490,18]),
        ('지표',[0,20,90,38]),('New',[100,20,190,38]),('Old',[200,20,290,38]),
        ('New',[300,20,390,38]),('Old',[400,20,490,38]),
        ('영업이익',[0,40,90,58]),('12',[100,40,190,58]),('13',[200,40,290,58]),
        ('14',[300,40,390,58]),('15',[400,40,490,58])]
    text,words=observed([(t,[b[0]+1,b[1]+1,b[2]-1,b[3]-1]) for t,b in entries])
    positions=[(0,0),(0,1),(0,3),*[(1,c) for c in range(5)],*[(2,c) for c in range(5)]]
    cells=[dict(row=r,column=c,text=t,bbox=b,colspan=2 if r==0 and c>0 else 1)
        for (r,c),(t,b) in zip(positions,entries,strict=True)]
    tables=[dict(index=0,bbox=[0,0,490,58],row_count=3,column_count=5,cells=cells)]
    facts=extract_cell_facts(text,words,tables,1)
    page=SimpleNamespace(id=uuid4(),document_id=uuid4(),page_number=1,final_text=text,
        extraction=SimpleNamespace(parser_version=facts[0]['processing_version'],
            final_text_sha256=hashlib.sha256(text.encode()).hexdigest(),table_facts=facts,
            provenance=dict(selected_words=words,native_tables=tables,paddle_tables=[],unsafe_spans=[])))
    assert not comparison_candidates(page,table_requirements('표의 2023과 2024 영업이익을 비교해줘.'))
    comparisons=comparison_candidates(page,table_requirements('표의 2023과 2024 영업이익 New를 비교해줘.'))
    assert len(comparisons)==2
    assert all(f['column_name']=='New' for f in comparisons)
    assert {f['value'] for f in comparisons}=={'12','14'}
    assert all(comparison_fact_valid(f,page) for f in comparisons)


def test_literal_confirmed_short_year_regression_keeps_graph_dates():
    from tests.test_structured_cells import test_short_year_requires_same_metric_and_value_corroboration
    test_short_year_requires_same_metric_and_value_corroboration()
    # Minimal already validated heading span: alias cannot override its full period.
    from app.primitive_graph import _facet
    base=dict(column_name="'23년",period='2023년',source_spans=[dict(role='period_confirmation')])
    assert _facet(base)==''
    assert _facet({**base,'period':'2022년'})!=""
    assert _facet({**base,'source_spans':[]})!=""
