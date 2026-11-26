"""Independent coordinate fixtures: no company/report/answer-specific behavior."""
from app import pdf_pipeline
from PIL import Image, ImageDraw


def test_paragraph_order_does_not_interleave_two_columns():
    from app import fact_fusion as f
    words=[dict(text=t,bbox=b,line_id=t,source='native',confidence=100)
           for t,b in [('right1',[200,10,260,20]),('left2',[10,30,70,40]),
                       ('left1',[10,10,70,20]),('right2',[200,30,260,40])]]
    groups=f.reading_groups(words)
    assert [[w['text'] for w in g] for g in groups]==[['left1','left2'],['right1','right2']]


def test_native_candidate_survives_conflicting_ocr():
    from app import fact_fusion as f
    n=dict(kind='text_numeric',metric='매출액',row_label='사업',period='2027F',unit='억원',value='12',
           page_number=1,bbox=[10,10,50,20],source='native_text',confidence=100)
    o={**n,'source':'ocr_text','value':'17','confidence':99}
    selected,rejected=f.fuse_candidates([o,n])
    assert selected==[n] and rejected[0]['reason']=='lower_priority_source_conflict'
    assert f.fuse_candidates([o,{**o,'value':'19'}])[0]==[]


def test_missing_regions_exclude_native_coverage():
    from app import fact_fusion as f
    image=Image.new('L',(400,200),255);d=ImageDraw.Draw(image)
    d.rectangle((10,20,100,40),fill=0);d.rectangle((240,20,350,40),fill=0)
    regions=f.missing_regions(image,[[8,18,102,42]])
    assert regions and all(b[0]>200 for b in regions)


def test_parser_has_new_version_boundary():
    assert pdf_pipeline.PARSER_VERSION != 'mixed-layout-v1'


def test_structured_chunks_never_bridge_unverified_gap():
    from app.chunking import structured_spans
    text='verified untrusted evidence'
    result=structured_spans(text,dict(parser_version='fact-fusion-v2',index_segments=[
        dict(char_start=0,char_end=8),dict(char_start=19,char_end=27)]))
    assert [s.content for s in result]==['verified','evidence']


def test_cell_topology_rejects_value_in_wrong_column():
    from app.native_tables import topology_matches
    table=dict(cells=[dict(row=0,column=1,bbox=[100,0,150,20]),
                      dict(row=1,column=0,bbox=[0,20,100,40]),
                      dict(row=1,column=1,bbox=[100,20,150,40]),
                      dict(row=1,column=2,bbox=[150,20,200,40])])
    fact=dict(source_spans=[dict(role='columns',bbox=[110,2,140,18]),
                           dict(role='row',bbox=[2,22,80,38]),dict(role='value',bbox=[110,22,140,38])])
    assert topology_matches(fact,table)
    fact['source_spans'][-1]['bbox']=[160,22,190,38]
    assert not topology_matches(fact,table)


def test_numeric_facts_do_not_accept_low_confidence_period():
    from app.fact_fusion import serialize_groups
    from app.fused_extraction import _numeric
    words=[dict(text=t,bbox=[i*30,0,i*30+25,10],line_id='r1',source='ocr',confidence=99)
           for i,t in enumerate('2Q27 영업이익 12억원 예상'.split())]
    text,words,segments=serialize_groups([words])
    assert _numeric(text,words,segments,1)[0]['value']=='12'
    words[0]['confidence']=50
    assert _numeric(text,words,segments,1)==[]


def test_numeric_promotion_requires_intact_source_and_new_version():
    from hashlib import sha256
    from types import SimpleNamespace
    from uuid import uuid4
    from app.fact_fusion import serialize_groups
    from app.fused_extraction import _numeric
    from app.fused_candidates import verified_numeric_candidates
    words=[dict(text=t,bbox=[i*30,0,i*30+25,10],line_id='n1',source='native',confidence=100)
           for i,t in enumerate('2Q27 영업이익 12억원 예상'.split())]
    text,words,segments=serialize_groups([words]);facts=_numeric(text,words,segments,1)
    page=SimpleNamespace(id=uuid4(),document_id=uuid4(),page_number=1,final_text=text,
        extraction=SimpleNamespace(table_facts=[],parser_version=facts[0]['processing_version'],final_text_sha256=sha256(text.encode()).hexdigest(),
            provenance=dict(selected_words=words,numeric_evidence=facts,unsafe_spans=[])))
    chunk=SimpleNamespace(id=uuid4(),page_id=page.id,document_id=page.document_id,page_number=1,
                          char_start=0,char_end=len(text),content=text)
    rows=[(chunk,page,None)]
    assert verified_numeric_candidates(rows,'2Q27 영업이익 전망')[0][1]['value']=='12'
    facts[0]['value']='13'
    assert verified_numeric_candidates(rows,'2Q27 영업이익 전망')==[]
    facts[0]['value']='12';page.extraction.parser_version='mixed-layout-v1'
    assert verified_numeric_candidates(rows,'2Q27 영업이익 전망')==[]


def test_sentence_boundaries_keep_later_damaged_text_out_of_claim():
    from app.fact_fusion import sentence_groups
    words=[dict(text=t) for t in ['매출은','늘었다.','손상된','문자']]
    assert [[w['text'] for w in g] for g in sentence_groups([words])]==[['매출은','늘었다.'],['손상된','문자']]


def test_same_cell_with_disagreeing_period_abstains():
    from app.fact_fusion import fuse_candidates
    fact=dict(kind='table',row_label='부문',metric='매출액',period='2027F',value='12',unit='억원',
              page_number=1,bbox=[100,50,120,60],source='ocr_table',confidence=99)
    assert fuse_candidates([fact,{**fact,'period':'2028F'}])[0]==[]


def test_new_upload_keeps_fused_proofs_through_embedding(client,db,monkeypatch):
    from uuid import UUID
    from app.models import Page,Chunk
    from app.main import app
    from app.embeddings import get_embedding_provider
    from .helpers import metadata
    from .test_page_layout import extraction_fixture
    from .test_hybrid_search import FakeEmbeddingProvider
    page=extraction_fixture()
    page.provenance.update(parser_version='fact-fusion-v2',index_segments=[
        dict(char_start=0,char_end=len(page.final_text),kind='paragraph')])
    for fact in page.table_facts:
        fact.update(processing_version='fact-fusion-v2',source='ocr_table')
    monkeypatch.setattr('app.service.extract_pdf',lambda *args:[page])
    app.dependency_overrides[get_embedding_provider]=lambda:FakeEmbeddingProvider()
    response=client.post('/api/v1/documents',data=metadata(),files={'file':('fixture.pdf',b'%PDF-fusion-transport','application/pdf')})
    assert response.status_code==200
    doc=UUID(response.json()['document_id'])
    assert client.post(f'/api/v1/documents/{doc}/embeddings').status_code==200
    stored=db.query(Page).filter_by(document_id=doc).one()
    assert stored.extraction.parser_version=='fact-fusion-v2'
    assert all(c.embedding is not None for c in db.query(Chunk).filter_by(document_id=doc))
    result=client.post('/api/v1/search',json={'query':'소재 2026E 영업이익','top_k':5}).json()
    fact=result['results'][0]['table_evidence'][0]
    assert (fact['value'],fact['unit'],fact['source'])==('5','백만원','ocr_table')
    assert fact['source_chunk_ids'] and all(s['bbox'] for s in fact['source_spans'])


def test_native_cells_form_facts_without_geometric_row_alignment():
    from app.native_tables import extract_native_facts
    from app.fact_fusion import serialize_groups
    entries=[('2027F',[110,3,145,13]),('억원',[10,3,40,13]),
             ('매출액',[10,23,60,33]),('12',[120,40,140,49]),
             ('영업이익',[10,55,70,65]),('4',[125,72,140,79])]
    text,words,_=serialize_groups([[dict(text=t,bbox=b,line_id=str(i),source='native',confidence=100)
                                  for i,(t,b) in enumerate(entries)]])
    table=dict(index=0,bbox=[0,0,150,80],row_count=3,column_count=2,cells=[
        dict(row=r,column=c,bbox=box,text='') for r,c,box in [
            (0,0,[0,0,100,20]),(0,1,[100,0,150,20]),
            (1,0,[0,20,100,50]),(1,1,[100,20,150,50]),
            (2,0,[0,50,100,80]),(2,1,[100,50,150,80])]])
    facts=extract_native_facts(text,words,[table],1)
    assert [(f['row_label'],f['period'],f['value'],f['source']) for f in facts]==[
        ('매출액','2027F','12','native_table'),('영업이익','2027F','4','native_table')]
    assert all(f['native_cell']['column']==1 for f in facts)


def test_proof_fragments_are_linkable_but_not_search_candidates():
    from types import SimpleNamespace
    from app.fused_index import searchable,retrieval_text
    page=SimpleNamespace(extraction=SimpleNamespace(parser_version='fact-fusion-v3',table_facts=[
        dict(char_start=20,row_label='소 재',metric='매 출',period='2027F',unit='억원',value='12')],
        provenance=dict(index_segments=[dict(kind='fact_span',char_start=0,char_end=5),
                                       dict(kind='fact_quote',char_start=20,char_end=23)])))
    proof=SimpleNamespace(char_start=0,char_end=5,content='2027F')
    anchor=SimpleNamespace(char_start=20,char_end=23,content='소 재')
    assert not searchable(proof,page)
    assert searchable(anchor,page) and '2027F' in retrieval_text(anchor,page)
    assert anchor.content=='소 재'


def test_benchmark_heading_does_not_relabel_company_forecast_as_consensus():
    from app.fact_fusion import serialize_groups
    from app.fused_extraction import _numeric
    words=[dict(text=t,bbox=[i*30,0,i*30+25,10],line_id='n1',source='native',confidence=100)
        for i,t in enumerate('2분기 순이익 컨센서스 10% 상회 예상 순이익 22억원 컨센서스 20억원 예상'.split())]
    text,selected,segments=serialize_groups([words])
    facts=_numeric(text,selected,segments,1)
    assert next(f for f in facts if f['value']=='22')['comparison_basis'] is None
    assert next(f for f in facts if f['value']=='20')['comparison_basis']=='컨센서스'


def test_duplicate_ocr_fact_does_not_consume_two_retrieval_slots():
    from app.fused_candidates import deduplicate_verified
    fact=dict(processing_version='fact-fusion-v4',document_id='d',page_number=1,row_label='부문',
              metric='매출액',unit='억원',value='12',period='2027F',status='forecast',source='ocr_table',confidence=85)
    better={**fact,'confidence':95}
    assert deduplicate_verified([('first',fact),('second',better)])==[('second',better)]
    legacy={**fact,'processing_version':'mixed-layout-v1'}
    assert len(deduplicate_verified([('first',legacy),('second',legacy)]))==2


def test_valid_words_from_different_table_rows_cannot_be_spliced():
    from copy import deepcopy
    from hashlib import sha256
    from types import SimpleNamespace
    from .test_page_layout import extraction_fixture
    from app.extraction_provenance import validated_stored_facts
    extracted=extraction_fixture()
    facts=deepcopy(extracted.table_facts)
    target=next(f for f in facts if f['row_label']=='소재' and f['period']=='2026E')
    other=next(f for f in facts if f['row_label']!='소재' and f['period']=='2026E')
    target['value']=other['value']
    target['source_spans']=[s for s in target['source_spans'] if s['role']!='value']+[
        s for s in other['source_spans'] if s['role']=='value']
    for f in facts:f['processing_version']='fact-fusion-v4'
    page=SimpleNamespace(page_number=1,final_text=extracted.final_text,
        extraction=SimpleNamespace(parser_version='fact-fusion-v4',
            final_text_sha256=sha256(extracted.final_text.encode()).hexdigest(),
            table_facts=facts,provenance=extracted.provenance))
    assert target not in validated_stored_facts(page)
