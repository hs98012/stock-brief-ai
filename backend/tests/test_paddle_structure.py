import pytest
from app.paddle_structure import decode_result


def observation():
    return dict(model='PP-StructureV3/test', width=400, height=200, result={
        'parsing_res_list': [dict(block_bbox=[200,0,400,200],block_label='text',block_order=1),
                             dict(block_bbox=[0,0,190,200],block_label='text',block_order=2)],
        'overall_ocr_res': dict(rec_texts=['왼쪽', '2Q27 영업이익 12억원 예상'],
             rec_scores=[.95,.99],rec_boxes=[[10,20,180,40],[210,20,390,40]]),
        'table_res_list': []})


def test_paddle_keeps_reported_reading_order_and_line_bbox():
    result=decode_result(observation(), 200, 100)
    assert result.groups[0][0]['text']=='2Q27 영업이익 12억원 예상'
    word=result.groups[0][0]
    assert word['bbox']==[105,10,195,20]
    assert word['confidence']==99 and word['source']=='paddle_structure'
    # A line is not split into invented word coordinates.
    assert len(result.words)==2


def test_paddle_rejects_misaligned_confidence_and_nonfinite_coordinates():
    raw=observation();raw['result']['overall_ocr_res']['rec_scores']=[.9]
    with pytest.raises(ValueError):decode_result(raw,200,100)
    raw=observation();raw['result']['overall_ocr_res']['rec_scores']=[0,0]
    with pytest.raises(ValueError):decode_result(raw,200,100)
    raw=observation();raw['result']['overall_ocr_res']['rec_boxes'][0][0]=float('nan')
    with pytest.raises(ValueError):decode_result(raw,200,100)


def test_paddle_low_confidence_numeric_is_not_evidence():
    from app.fact_fusion import serialize_groups
    from app.fused_extraction import _numeric
    raw=observation();raw['result']['overall_ocr_res']['rec_scores'][1]=.79
    result=decode_result(raw,200,100)
    text,words,segments=serialize_groups(result.groups)
    assert not _numeric(text,words,segments,1)


def test_paddle_fact_retains_source():
    from app.fact_fusion import serialize_groups
    from app.fused_extraction import _numeric
    result=decode_result(observation(),200,100)
    text,words,segments=serialize_groups(result.groups)
    fact=_numeric(text,words,segments,1)[0]
    assert fact['source']=='paddle_structure'
    assert fact['value']=='12'
    assert all(s['sources']==['paddle_structure'] for s in fact['source_spans'])


def test_separate_values_in_one_paddle_line_do_not_conflict():
    from app.fact_fusion import serialize_groups,fuse_candidates
    from app.fused_extraction import _numeric
    raw=observation()
    raw['result']['overall_ocr_res']['rec_texts'][1]='2Q27 영업이익 12억원 컨센서스 10억원 20% 상회 예상'
    result=decode_result(raw,200,100)
    text,words,segments=serialize_groups(result.groups)
    facts=_numeric(text,words,segments,1)
    assert {f['value'] for f in fuse_candidates(facts)[0]}=={'12','10','20'}


def test_complex_page_uses_paddle_without_tesseract(tmp_path,monkeypatch):
    from .helpers import make_pdf
    from app.pdf_pipeline import extract_pdf
    path=tmp_path/'document.pdf';path.write_bytes(make_pdf('Native body retained'))
    monkeypatch.setattr('app.fused_extraction.extract_structure',lambda page:decode_result(observation(),200,100))
    def forbidden(*args):raise AssertionError('Tesseract must not run after valid Paddle')
    monkeypatch.setattr('app.pdf_pipeline.ocr_page',forbidden)
    page=extract_pdf(path,tmp_path/'images',force_ocr=True)[0]
    assert page.provenance['primary_engine']=='paddle_structure'
    assert page.ocr_error is None and page.native_text=='Native body retained'
    assert page.provenance['paddle_model']=='PP-StructureV3/test'
    assert page.provenance['numeric_evidence'][0]['source']=='paddle_structure'


def test_paddle_failure_records_fallback(tmp_path,monkeypatch):
    from .helpers import make_pdf
    from app.pdf_pipeline import extract_pdf,OCRPage
    path=tmp_path/'document.pdf';path.write_bytes(make_pdf('Native remains'))
    def fail(*args):raise ValueError('invalid structure')
    monkeypatch.setattr('app.fused_extraction.extract_structure',fail)
    calls=[]
    def fallback(*args):
        calls.append(True)
        return OCRPage('',None,[])
    monkeypatch.setattr('app.pdf_pipeline.ocr_page',fallback)
    page=extract_pdf(path,tmp_path/'images',force_ocr=True)[0]
    assert calls==[True] and page.provenance['paddle_error']
    assert page.native_text=='Native remains'


def table_observation():
    cells=[['구분','2027A','2028F'],['매출액','12','15'],['영업이익','3','4']]
    boxes=[[c*100,r*30+30,(c+1)*100,(r+1)*30+30] for r in range(3) for c in range(3)]
    text=[v for row in cells for v in row]+['(억원)']
    rec_boxes=[[b[0]+10,b[1]+4,b[2]-10,b[3]-4] for b in boxes]+[[210,3,270,15]]
    return dict(model='PP-StructureV3/test',width=300,height=150,result={
        'overall_ocr_res':dict(rec_texts=text,rec_scores=[.99]*len(text),rec_boxes=rec_boxes),
        'parsing_res_list':[dict(block_bbox=[0,30,300,120],block_label='table')],
        'table_res_list':[dict(cell_box_list=boxes,pred_html='<table>'+''.join(
            '<tr>'+''.join(f'<td>{v}</td>' for v in row)+'</tr>' for row in cells)+'</table>')]})


def test_paddle_cell_facts_require_html_ocr_agreement_and_reject_merged_cells():
    from app.fact_fusion import serialize_groups
    from app.paddle_tables import extract_paddle_facts
    raw=table_observation();obs=decode_result(raw,300,150)
    text,words,_=serialize_groups(obs.groups)
    facts=extract_paddle_facts(text,words,obs.tables,1)
    assert len(facts)==4
    assert {(f['period'],f['unit'],f['value']) for f in facts}=={
        ('2027A','억원','12'),('2028F','억원','15'),('2027A','억원','3'),('2028F','억원','4')}
    obs.tables[0]['cells'][4]['text']='999'
    assert not any(f['value']=='12' for f in extract_paddle_facts(text,words,obs.tables,1))
    raw['result']['table_res_list'][0]['pred_html']=raw['result']['table_res_list'][0]['pred_html'].replace('<td>','<td colspan="2">',1)
    assert not decode_result(raw,300,150).tables


def test_inline_row_unit_keeps_literal_region_and_html_identity():
    from app.fact_fusion import serialize_groups
    from app.paddle_tables import extract_paddle_facts
    raw=table_observation();ocr=raw['result']['overall_ocr_res']
    for key in ('rec_texts','rec_scores','rec_boxes'):ocr[key].pop()
    for index,label in ((3,'매출액'),(6,'영업이익')):
        ocr['rec_texts'][index]=label+'(억원)'
        raw['result']['table_res_list'][0]['pred_html']=raw['result']['table_res_list'][0]['pred_html'].replace(f'>{label}<',f'>{label}(억원)<')
    obs=decode_result(raw,300,150);text,words,_=serialize_groups(obs.groups)
    facts=extract_paddle_facts(text,words,obs.tables,1)
    assert len(facts)==4
    assert {f['row_label'] for f in facts}=={'매출액','영업이익'}
    assert all(f['unit']=='억원' for f in facts)
    label=next(w for w in words if w['text']=='매출액')
    unit=next(w for w in words if w['text']=='(억원)')
    assert label['bbox']==unit['bbox']  # Region box retained, no fake glyph boxes.
    assert label['observation_index']==unit['observation_index']


@pytest.mark.parametrize('structured', [False, True])
def test_new_upload_paddle_cells_survive_embedding_and_search(client,db,monkeypatch,tmp_path,structured):
    from uuid import UUID
    from .helpers import make_pdf,metadata
    from .test_hybrid_search import FakeEmbeddingProvider
    from app.main import app
    from app.embeddings import get_embedding_provider
    from app.models import Page
    from app.pdf_pipeline import extract_pdf
    from app.extraction_provenance import validated_stored_facts
    path=tmp_path/'fixture.pdf';path.write_bytes(make_pdf('Native preserved'))
    raw=table_observation()
    if structured:
        # Explicit table-header unit inside the conservative structural scope.
        raw['result']['overall_ocr_res']['rec_boxes'][-1]=[210,15,270,27]
    monkeypatch.setattr('app.fused_extraction.extract_structure',lambda page:decode_result(raw,300,150))
    parsed=extract_pdf(path,tmp_path/'images',force_ocr=True)
    monkeypatch.setattr('app.service.extract_pdf',lambda *args:parsed)
    app.dependency_overrides[get_embedding_provider]=lambda:FakeEmbeddingProvider()
    upload=client.post('/api/v1/documents',data=metadata(),files={'file':('fixture.pdf',path.read_bytes(),'application/pdf')})
    assert upload.status_code==200
    doc=UUID(upload.json()['document_id'])
    assert client.post(f'/api/v1/documents/{doc}/embeddings').status_code==200
    page=db.query(Page).filter_by(document_id=doc).one()
    assert len(validated_stored_facts(page))==4
    if structured:
        cells=validated_stored_facts(page)
        assert all(f.get('table_id') and f.get('row_id') and f.get('column_id') for f in cells)
        assert all(f.get('comparison_cell') and f['comparison_derivation']['primitive_cells'] for f in cells)
    response=client.post('/api/v1/search',json={'query':'2028F 영업이익','top_k':5})
    facts=[f for r in response.json()['results'] for f in r['table_evidence']]
    assert any(f['value']=='4' and f['source']=='paddle_structure' and f['source_chunk_ids'] for f in facts)


def test_period_followed_by_korean_particle_remains_queryable():
    from app.table_evidence import fact_matches_query
    fact=dict(row_label='영업이익',metric='영업이익',period='1Q27',comparison_basis=None,
              processing_version='fact-fusion-paddle-v2')
    query='1Q27과 2Q27F 영업이익을 비교해줘'
    assert fact_matches_query(fact,query)
    assert fact_matches_query({**fact,'period':'2Q27F'},query)
    assert not fact_matches_query({**fact,'period':'1Q28'},query)
