from hashlib import sha256
from types import SimpleNamespace
from uuid import UUID

from PIL import Image, ImageDraw
import fitz

from app.page_layout import native_observation, select_sources, PARSER_VERSION
from app.layout_tables import extract_layout_facts
from app.pdf_pipeline import ExtractedPage, OCRPage
from app.models import Page, Chunk, TextSource
from app.extraction_provenance import validated_stored_facts


def table_words(source='ocr'):
    rows = [[('요약',20),('(백만원)',230)], [('2025A',110),('2026E',190)],
            [('매출액',20),('100',120),('120',200)], [('- 소재',20),('10',120),('12',200)],
            [('영업이익',20),('20',120),('30',200)], [('- 소재',20),('3',120),('5',200)]]
    return [{'text':text,'bbox':[x,20+row*20,x+(35 if len(text)>3 else 25),30+row*20],
             'line_id':f'{source}:{row}','source':source,'confidence':95.0}
            for row,tokens in enumerate(rows) for text,x in tokens]


def extraction_fixture():
    text,words,unsafe,mode = select_sources('',[],table_words())
    facts = extract_layout_facts(text,words,1,unsafe)
    provenance = {'parser_version':PARSER_VERSION,'selection_mode':mode,'ocr_reasons':['uncovered_fixture'],
        'ocr_dpi':300,'metrics':{},'selected_words':words,'unsafe_spans':unsafe}
    return ExtractedPage(1,None,text,text,TextSource.ocr,None,None,provenance,facts)


def test_long_native_with_uncovered_visual_region_requires_ocr():
    class VisualPage:
        rotation_matrix=fitz.Matrix(1,1)
        def get_text(self, mode, **kwargs):
            return [(10,10,90,30,'A'*287,0,0,0)]
        def get_pixmap(self, **kwargs):
            image=Image.new('L',(300,400),255)
            draw=ImageDraw.Draw(image)
            draw.rectangle((12,12,85,25),fill=0)
            draw.rectangle((100,100,270,250),fill=0)
            return SimpleNamespace(width=300,height=400,samples=image.tobytes())
        def get_drawings(self):
            return []
    _,metrics,reasons=native_observation(VisualPage(),'A'*287)
    assert metrics['native_chars']==287
    assert 'rendered_regions_missing_from_native' in reasons


def test_selection_keeps_native_body_and_rejects_numeric_disagreement():
    native_words=[{'text':'본문','bbox':[10,10,40,20],'line_id':'n:0','source':'native','confidence':100},
                  {'text':'10','bbox':[50,10,70,20],'line_id':'n:0','source':'native','confidence':100}]
    recognized=[{**native_words[1],'text':'11','source':'ocr','confidence':96},*table_words()]
    text,words,unsafe,mode=select_sources('본문 10',native_words,recognized)
    assert text.startswith('본문 10') and not text.startswith('본문 11')
    assert mode=='mixed' and any(s['reason']=='native_ocr_numeric_disagreement' for s in unsafe)


def test_coordinate_table_preserves_parent_period_unit_and_exact_spans():
    page=extraction_fixture()
    fact=next(f for f in page.table_facts if f['row_label']=='소재' and f['metric']=='영업이익' and f['period']=='2026E')
    assert (fact['value'],fact['unit'],fact['status'])==('5','백만원','forecast')
    assert fact['source']=='ocr'
    for span in fact['source_spans']:
        assert page.final_text[span['char_start']:span['char_end']]==span['quote']
        assert len(span['bbox'])==4


def test_uncertain_period_not_repaired_and_unknown_column_does_not_shift_values():
    words=table_words()
    for word in words:
        if word['text']=='2025A': word['text']='1026'
    text,selected,unsafe,_=select_sources('',[],words)
    # Only one intact period: insufficient header evidence; no guessed table.
    assert not extract_layout_facts(text,selected,1,unsafe)


def test_low_confidence_cell_and_prose_are_not_table_facts():
    words=table_words()
    next(w for w in words if w['text']=='5')['confidence']=20
    text,selected,unsafe,_=select_sources('',[],words)
    assert not any(f['value']=='5' for f in extract_layout_facts(text,selected,1,unsafe))
    assert not extract_layout_facts('매출은 늘었다.',[],1,[])


def test_upload_embedding_search_and_analysis_candidates_keep_metadata(client,db,monkeypatch):
    from app.main import app
    from app.embeddings import get_embedding_provider
    from app.analysis_retrieval import collect_analysis_evidence
    from .test_hybrid_search import FakeEmbeddingProvider
    from .helpers import metadata
    page=extraction_fixture()
    # Isolated transport fixture; no original PDF or persistent DB is uploaded.
    monkeypatch.setattr('app.service.extract_pdf',lambda *args:[page])
    from app.chunking import split_page
    monkeypatch.setattr('app.service.split_page',lambda text:split_page(text,45))
    response=client.post('/api/v1/documents',data=metadata(),files={'file':('fixture.pdf',b'%PDF-fixture-transport','application/pdf')})
    assert response.status_code==200
    doc_id=UUID(response.json()['document_id'])
    stored=db.query(Page).filter(Page.document_id==doc_id).one()
    assert stored.extraction.parser_version==PARSER_VERSION
    assert stored.extraction.final_text_sha256==sha256(stored.final_text.encode()).hexdigest()
    assert stored.extraction.table_facts
    original=stored.extraction.table_facts
    provider=FakeEmbeddingProvider()
    app.dependency_overrides[get_embedding_provider]=lambda:provider
    embedded=client.post(f'/api/v1/documents/{doc_id}/embeddings')
    assert embedded.status_code==200
    assert stored.extraction.table_facts==original
    assert all(c.embedding is not None for c in db.query(Chunk).filter(Chunk.document_id==doc_id))
    response=client.post('/api/v1/search',json={'query':'소재 2026E 영업이익','top_k':5})
    fact=response.json()['results'][0]['table_evidence'][0]
    assert fact['value']=='5' and fact['source_chunk_ids']
    assert fact['source_spans'] and len(fact['source_chunk_ids'])>1
    candidates=collect_analysis_evidence(db,doc_id,'소재 2026E 영업이익',5,provider)
    assert any(c.get('table_evidence') for c in candidates)
    assert client.get(f'/api/v1/documents/{doc_id}/pages/1').json()['extraction']['parser_version']==PARSER_VERSION
    # Neither stale final_text nor forged values may reuse old coordinate proofs.
    original[0]['value']='999'
    assert original[0] not in validated_stored_facts(stored)
    stored.final_text += ' changed'
    assert validated_stored_facts(stored)==[]


def test_numeric_prose_has_period_unit_and_basis_but_is_not_a_table():
    from app.numeric_evidence import extract_numeric_evidence
    tokens='2 분 기 영 업 이 익 은 42 억 원 으로 컨센서스 38 억 원 을 10.5% 상 회 할 것으로 예상'.split()
    words=[{'text':t,'bbox':[i*20,10,(i+1)*20,20],'line_id':'o:1','source':'ocr','confidence':95}
           for i,t in enumerate(tokens)]
    text,selected,unsafe,_=select_sources('',[],words)
    facts=extract_numeric_evidence(text,selected,1,unsafe)
    assert [(f['value'],f['unit']) for f in facts]==[('42','억원'),('38','억원'),('10.5','%')]
    assert all(f['period']=='2분기' and f['status']=='forecast' for f in facts)
    assert facts[1]['comparison_basis']=='컨센서스'
    assert extract_layout_facts(text,selected,1,unsafe)==[]
    for fact in facts:
        for span in fact['source_spans']:
            assert text[span['char_start']:span['char_end']]==span['quote'] and span['boxes']


def test_damaged_value_does_not_take_a_number_from_remarks_column():
    rows=[ [('제목',20),('(억원)',240)], [('구분',20),('값',194),('비고',260)],
           [('항목가',20),('26.04]',170),('8',210)],
           [('항목나',20),('10',180)], [('항목다',20),('20',180)] ]
    words=[]
    for i,row in enumerate(rows):
        for text,x in row:
            width=7 if text=='값' else 6 if text=='8' else 21 if text in ('10','20') else 30
            words.append({'text':text,'bbox':[x,i*20,x+width,i*20+10], 'line_id':f'o:{i}',
                          'source':'ocr','confidence':95})
    text,selected,unsafe,_=select_sources('',[],words)
    facts=extract_layout_facts(text,selected,1,unsafe)
    assert not any(f['row_label']=='항목가' or f['value']=='8' for f in facts)
    assert {f['value'] for f in facts}=={'10','20'}


def test_bad_native_token_never_discards_intact_native_body():
    native=[{'text':'정상본문','bbox':[0,0,40,10],'source':'native','confidence':100,'line_id':'n:0'},
            {'text':'\ufffd','bbox':[50,0,60,10],'source':'native','confidence':100,'line_id':'n:0'}]
    recognized=[{'text':'복구','bbox':[50,0,60,10],'source':'ocr','confidence':95,'line_id':'o:0'}]
    text,selected,unsafe,mode=select_sources('정상본문 \ufffd',native,recognized,damaged_native=True)
    assert text.startswith('정상본문') and any(w['text']=='정상본문' and w['source']=='native' for w in selected)
    assert any(w['text']=='복구' and w['source']=='ocr' for w in selected)
    assert mode=='mixed' and unsafe[0]['reason']=='damaged_native_token'


def test_ocr_coordinates_use_cropbox_and_pdf_point_scale(tmp_path,monkeypatch):
    from app.pdf_pipeline import ocr_page
    observed={}
    def render(*args,**kwargs):
        observed.update(kwargs)
        return [Image.new('RGB',(200,100),'white')]
    class Document:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def __getitem__(self,index): return SimpleNamespace(rect=SimpleNamespace(width=100,height=50),rotation=0)
    monkeypatch.setattr('app.pdf_pipeline.convert_from_path',render)
    monkeypatch.setattr('app.pdf_pipeline.fitz.open',lambda _:Document())
    monkeypatch.setattr('app.pdf_pipeline.pytesseract.image_to_data',lambda *args,**kwargs:
        {'text':['token'],'conf':[95],'left':[20],'top':[10],'width':[40],'height':[20],
         'block_num':[1],'par_num':[1],'line_num':[1]})
    result=ocr_page(tmp_path/'unused.pdf',1,tmp_path/'images')
    assert observed['use_cropbox'] is True
    assert result.words[0]['bbox']==[10,5,30,15]
