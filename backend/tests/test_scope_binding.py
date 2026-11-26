"""Independent structural scope fixtures; no sealed corpus values/coordinates."""
from copy import deepcopy
import pytest
from types import SimpleNamespace as NS
from tests.test_structured_cells import observed
from tests.test_period_binding import page
from tests.test_index_admission import rows
from app.primitive_graph import primitive_graph
from app.index_admission import admit_dependencies
from app.search import rank_rows


def fixture(mode='column', scopes=('연결','별도'), duplicate=False):
    entries=[];cells=[]
    ncols=5 if mode=='parent' else 4
    headers=['범위','지표','단위','2034A'] if ncols==4 else ['상위','범위','지표','단위','2034A']
    for c,t in enumerate(headers):
        cells.append(dict(row=0,column=c,text=t,bbox=[c*100,0,(c+1)*100,24]))
        entries.append((t,[c*100+3,3,c*100+3+len(t)*7,17]))
    r=1
    for i,scope in enumerate(scopes):
        if mode=='section':
            cells.append(dict(row=r,column=0,colspan=ncols,text=scope,bbox=[0,r*28,ncols*100,r*28+24]))
            entries.append((scope,[3,r*28+3,3+len(scope)*7,r*28+17]));r+=1
        count=2 if mode in {'merged','parent'} or duplicate else 1
        start=r
        if mode in {'merged','parent'}:
            col=1 if mode=='parent' else 0
            cells.append(dict(row=r,column=col,rowspan=count,text=scope,bbox=[col*100,r*28,(col+1)*100,(r+count-1)*28+24]))
            entries.append((scope,[col*100+3,r*28+3,col*100+3+len(scope)*7,r*28+17]))
        for j in range(count):
            metric='매출액' if j==0 or duplicate else '영업이익'
            metriccol=ncols-3
            if mode=='column':
                cells.append(dict(row=r,column=0,text=scope,bbox=[0,r*28,100,r*28+24]))
                entries.append((scope,[3,r*28+3,3+len(scope)*7,r*28+17]))
            cells.append(dict(row=r,column=metriccol,text=metric,bbox=[metriccol*100,r*28,(metriccol+1)*100,r*28+24]))
            if mode=='row':
                entries.append((scope,[metriccol*100+3,r*28+3,metriccol*100+3+len(scope)*7,r*28+17]))
                x=metriccol*100+40
                cells[-1]['text']=scope+' '+metric
            else:x=metriccol*100+3
            entries.append((metric,[x,r*28+3,x+len(metric)*7,r*28+17]))
            for c,t in [(ncols-2,'억원'),(ncols-1,str(23+i*18+j*4))]:
                cells.append(dict(row=r,column=c,text=t,bbox=[c*100,r*28,(c+1)*100,r*28+24]))
                entries.append((t,[c*100+3,r*28+3,c*100+3+len(t)*7,r*28+17]))
            r+=1
    if mode=='parent':
        cells.append(dict(row=1,column=0,rowspan=r-1,text='연결',bbox=[0,28,100,(r-1)*28+24]))
        entries.append(('연결',[3,31,17,45]))
    text,words=observed(entries)
    return text,words,[dict(index=0,bbox=[0,0,ncols*100,r*28],row_count=r,column_count=ncols,cells=cells)]


def search(p,scope='연결'):
    admit_dependencies(p)
    return rank_rows(rows(p),f'표의 {scope} 기준 2034A 매출액 값은 얼마인가?',5,
                     NS(available=False,unavailable_reason='offline'))


@pytest.mark.parametrize('mode', ['row','column','section','merged','parent'])
def test_scopes_reach_graph_admission_pack_coverage(mode):
    p=page(fixture(mode,('국내','해외') if mode=='parent' else ('연결','별도')))
    expected='연결 국내' if mode=='parent' else '연결'
    assert p.extraction.table_facts
    graph=primitive_graph(p)
    assert graph['nodes'] and all(n['scope_binding']['approved'] for n in graph['nodes'])
    groups=admit_dependencies(p)
    assert groups and all(g['scope_binding']['approved'] for g in groups)
    result=search(p,expected)
    assert result.coverage_complete
    facts=[f for item in result.evidence_pack for f in item.get('table_evidence',[])]
    assert facts and all(f['scope_binding']['path']==(['consolidated','domestic'] if mode=='parent' else ['consolidated']) for f in facts)
    assert all(f['period_binding']['approved'] and f['unit_binding']['approved'] for f in facts)
    assert all(c.content==p.final_text[c.char_start:c.char_end] for c,_,_ in rows(p))


@pytest.mark.parametrize('mode',['row','column','section','merged','parent'])
def test_no_scope_default_or_mismatch(mode):
    p=page(fixture(mode,('국내','해외') if mode=='parent' else ('연결','별도')))
    assert not search(p,'').coverage_complete
    assert not search(p,'개별 해외' if mode=='parent' else '국내').coverage_complete


@pytest.mark.parametrize('mutation',['scope_span','scope_value','context_id','owner','period','unit','table','document','namespace','proof_delete','cross_scope'])
def test_tampered_scope_proof_holds(mutation):
    p=page(fixture())
    f=deepcopy(p.extraction.table_facts[0]);proof=f['scope_binding']
    if mutation=='scope_span':proof['declarations'][0]['span']['quote']='별도'
    elif mutation=='scope_value':proof['path']=['separate']
    elif mutation=='context_id':proof['context_id']='foreign'
    elif mutation=='owner':proof['ownership_id']='foreign'
    elif mutation=='period':f.pop('period_binding')
    elif mutation=='unit':f.pop('unit_binding')
    elif mutation=='table':proof['table_id']='foreign'
    elif mutation=='document':f['document_id']='foreign'
    elif mutation=='namespace':proof['namespace']={'document_id':'foreign','page_id':str(p.id)}
    elif mutation=='proof_delete':f.pop('scope_binding')
    elif mutation=='cross_scope':f['value_span']=deepcopy(p.extraction.table_facts[1]['value_span'])
    p.extraction.table_facts=[f]
    assert not search(p).coverage_complete


def test_duplicate_metric_in_selected_scope_holds():
    assert not search(page(fixture(duplicate=True))).coverage_complete


def test_parent_child_geometry_missing_holds():
    text,words,tables=fixture('parent',('국내','해외'))
    parent=next(c for c in tables[0]['cells'] if c['text']=='연결')
    parent['rowspan']=1
    assert not search(page((text,words,tables)),'연결 국내').coverage_complete



def test_two_reporting_scope_declarations_in_metric_cell_hold():
    text,words,tables=fixture('row')
    entries=[(w['text'],w['bbox']) for w in words]+[('별도',[150,31,164,45])]
    text,words=observed(entries)
    p=page((text,words,tables))
    assert not search(p).coverage_complete


def test_scope_candidate_with_missing_value_proof_still_blocks_duplicate():
    text,words,tables=fixture(duplicate=True)
    words=[w for w in words if w['text']!='27']
    p=page((text,words,tables))
    assert not search(p).coverage_complete


def test_parent_proof_mutation_cannot_publish():
    p=page(fixture('parent',('국내','해외')))
    p.extraction.table_facts[0]['scope_binding']['parent_child'][0]['relationship']='inferred'
    assert not search(p,'연결 국내').coverage_complete


def test_missing_scope_source_observation_is_not_unscoped():
    text,words,tables=fixture()
    words=[w for w in words if w['text']!='연결']
    assert not search(page((text,words,tables))).coverage_complete


def test_scoped_native_fallback_does_not_bypass_new_binding():
    from app.native_tables import extract_native_facts
    from app.fact_fusion import PARSER_VERSION
    from app.extraction_provenance import validated_stored_facts
    p=page(fixture('section'))
    pro=p.extraction.provenance
    facts=extract_native_facts(p.final_text,pro['selected_words'],pro['native_tables'],1)
    for f in facts:f['processing_version']=PARSER_VERSION
    p.extraction.table_facts=facts
    assert not validated_stored_facts(p)


def two_periods(mode='column'):
    text,words,tables=fixture(mode,('국내','해외') if mode=='parent' else ('연결','별도'))
    table=tables[0];old=table['column_count'];entries=[(w['text'],w['bbox']) for w in words]
    for cell in list(table['cells']):
        if cell['column'] != old-1:continue
        new=deepcopy(cell);new['column']=old
        new['bbox']=[b+(100 if i in (0,2) else 0) for i,b in enumerate(new['bbox'])]
        new['text']='2035F' if new['row']==0 else str(int(new['text'])+9)
        table['cells'].append(new)
        box=new['bbox'];entries.append((new['text'],[box[0]+3,box[1]+3,box[0]+3+len(new['text'])*7,box[1]+17]))
    table['column_count']+=1;table['bbox'][2]+=100
    text,words=observed(entries)
    return text,words,tables


@pytest.mark.parametrize('mode', ['column','parent'])
def test_comparison_keeps_scoped_period_unit_leaves(mode):
    p=page(two_periods(mode));admit_dependencies(p)
    scope='연결 국내' if mode=='parent' else '연결'
    result=rank_rows(rows(p),f'표의 {scope} 2034A와 2035F 매출액을 비교해줘.',5,
                     NS(available=False,unavailable_reason='offline'))
    assert result.coverage_complete
    selected=[f for i in result.evidence_pack for f in i['table_evidence']]
    assert selected
    for fact in selected:
        leaves=fact['comparison_derivation']['primitive_cells']
        assert len(leaves)==2 and leaves[0]['scope_binding']['path']==leaves[1]['scope_binding']['path']
        assert all(f['period_binding']['approved'] and f['unit_binding']['approved'] for f in leaves)


def test_cross_scope_comparison_leaf_cannot_be_mixed():
    from app.primitive_graph import comparison_candidates
    from app.evidence_requirements import table_requirements, fact_requirement_match
    p=page(two_periods())
    req=table_requirements('표의 연결 2034A와 2035F 매출액을 비교해줘.')[0]
    f=comparison_candidates(p,[req])[0]
    f['comparison_derivation']['primitive_cells'][1]['scope_binding']['path']=['separate']
    assert not fact_requirement_match(req,f)[0]


def test_missing_inline_scope_proof_does_not_become_unscoped():
    text,words,tables=fixture('row',('연결',))
    words=[w for w in words if w['text']!='연결']
    p=page((text,words,tables))
    assert not search(p,'').coverage_complete


def test_scope_column_conflicting_row_geometry_holds():
    text,words,tables=fixture()
    cell=next(c for c in tables[0]['cells'] if c['text']=='연결')
    cell['bbox'][3]+=28
    assert not search(page((text,words,tables))).coverage_complete


def test_section_boundary_is_a_required_dependency():
    p=page(fixture('section'))
    groups=admit_dependencies(p)
    selected=[g for g in groups if g['scope']=='consolidated']
    assert selected and all(any(s['role']=='scope_boundary' for s in g['dependencies']) for g in selected)


def test_deleted_section_topology_proof_cannot_become_unscoped():
    text,words,tables=fixture('section',('연결',))
    next(c for c in tables[0]['cells'] if c['text']=='연결').pop('colspan')
    assert not search(page((text,words,tables)),'').coverage_complete


def test_unsupported_scope_header_does_not_authorize_a_default():
    text,words,tables=fixture('column',('연결',))
    entries=[(w['text'],w['bbox']) for w in words if w['text']!='연결']+[('연결',[3,3,17,17])]
    tables[0]['cells'][0]['text']='연결'
    next(c for c in tables[0]['cells'] if c['row']==1 and c['column']==0)['text']=''
    text,words=observed(entries)
    assert not search(page((text,words,tables)),'').coverage_complete


@pytest.mark.parametrize('version',['fact-fusion-paddle-v3','fact-fusion-paddle-v4','fact-fusion-paddle-v5'])
def test_archived_annotation_rows_keep_original_scope_tokens(version):
    from app.metric_annotations import _rows
    p=page(fixture())
    p.extraction.parser_version=version
    table=p.extraction.provenance['native_tables'][0]
    assert any(r['raw_label']=='연결' for r in _rows(p,table,'native'))


def test_expired_native_context_proof_is_revalidated():
    text,words,tables=fixture('merged')
    for cell in tables[0]['cells']:cell.pop('rowspan',None)
    p=page((text,words,tables))
    assert search(p,'별도').coverage_complete
    selected=[f for f in p.extraction.table_facts if f.get('scope_binding',{}).get('scope')=='separate']
    assert selected and all(f['scope_binding']['expired_contexts'] for f in selected)
    for fact in selected:
        fact['scope_binding']['expired_contexts'][0]['membership']['context_id']='foreign-context'
    assert not search(p,'별도').coverage_complete
