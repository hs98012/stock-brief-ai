import hashlib
from datetime import date
from types import SimpleNamespace
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app.models import Base, Document, DocumentType, DocumentStatus, Chunk, Page
from app.shadow_models import ShadowRevision, ShadowPage, ShadowChunk
from app import shadow_revision as shadow
from app.search import hybrid_search, SearchFilters


class Provider:
    provider_name = 'ollama'; model = 'bge-m3'; dimensions = 1024
    available = True; unavailable_reason = None
    def embed(self, texts):
        return [[1.0] + [0.0]*1023 for _ in texts]


def test_isolated_idempotent_revision(tmp_path, monkeypatch):
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    pdf = tmp_path/'original'; pdf.write_bytes(b'original fixture bytes')
    observed = SimpleNamespace(page_number=1, native_text='매출 2026F 123억원', ocr_text=None,
        final_text='매출 2026F 123억원', provenance={'parser_version':'mixed-layout-v1',
            'index_segments':[{'kind':'paragraph','char_start':0,'char_end':14}]}, table_facts=[])
    monkeypatch.setattr(shadow, 'extract_pdf', lambda *args: [observed])
    with Session(engine) as db:
        doc = Document(company_name='fixture', document_type=DocumentType.broker_report,
            issuer='fixture', published_at=date(2026, 1, 1), filename='fixture', storage_path=str(pdf),
            file_hash=hashlib.sha256(pdf.read_bytes()).hexdigest(), status=DocumentStatus.completed)
        db.add(doc); db.commit()
        rev = shadow.create_revision(db, doc, pdf); db.commit()
        assert shadow.create_revision(db, doc, pdf).id == rev.id
        shadow.embed_revision(db, rev.id, Provider()); db.commit()
        assert len(db.scalars(select(ShadowRevision)).all()) == 1
        assert len(db.scalars(select(ShadowPage)).all()) == 1
        assert len(db.scalars(select(ShadowChunk)).all()) == 1
        assert db.scalars(select(Page)).all() == db.scalars(select(Chunk)).all() == []
        assert hybrid_search(db, '매출', 5, SearchFilters(), Provider()).results == []
        result = shadow.search_revision(db, rev, doc, '매출', Provider())
        assert len(result.results) == 1 and result.vector_search_used
        assert result.results[0]['quote'] == observed.final_text
        provider = Provider()
        provider.embed = lambda _: pytest.fail('Already embedded chunks must not be re-embedded')
        shadow.embed_revision(db, rev.id, provider)
        rev.status = 'parsed'
        with pytest.raises(ValueError, match='not ready'):
            shadow.search_revision(db, rev, doc, '매출', provider)
        pdf.write_bytes(b'different')
        with pytest.raises(ValueError, match='hash mismatch'):
            shadow.create_revision(db, doc, pdf)


def test_ranking_only_sees_supplied_revision_rows():
    from uuid import uuid4
    from app.search import rank_rows
    document = SimpleNamespace(id=uuid4(), filename='test', company_name='fixture',
        stock_code=None, issuer='fixture', published_at=date(2026, 1, 1),
        document_type=DocumentType.broker_report)
    page = SimpleNamespace(id=uuid4(), document_id=document.id, page_number=1,
                           final_text='매출 2026F', extraction=None)
    chunk = SimpleNamespace(id=uuid4(), document_id=document.id, page_id=page.id,
        page_number=1, content=page.final_text, char_start=0, char_end=len(page.final_text),
        embedding=[1.0]+[0.0]*1023, embedding_model='bge-m3', embedding_provider='ollama',
        embedding_dimensions=1024, section_title=None)
    assert rank_rows([(chunk, page, document)], '매출', 5, Provider()).results[0]['chunk_id'] == chunk.id
    chunk.page_id = uuid4()
    assert rank_rows([(chunk, page, document)], '매출', 5, Provider()).results == []


def test_pinned_revision_keeps_fact_parser_version_for_search():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        doc = Document(company_name='fixture', document_type=DocumentType.broker_report,
            issuer='fixture', published_at=date(2026, 1, 1), filename='fixture',
            storage_path='fixture.pdf', file_hash='a'*64, status=DocumentStatus.completed)
        db.add(doc); db.flush()
        rev = ShadowRevision(document_id=doc.id, file_hash=doc.file_hash,
            parser_version='fact-fusion-paddle-v2+pin-test1234', status='ready')
        db.add(rev); db.flush()
        page = ShadowPage(revision_id=rev.id, page_number=1, final_text='근거 문장',
            final_text_sha256=hashlib.sha256('근거 문장'.encode()).hexdigest(),
            provenance={'index_segments': []}, table_facts=[])
        db.add(page); db.flush()
        db.add(ShadowChunk(revision_id=rev.id, page_id=page.id, content='근거 문장',
                           char_start=0, char_end=len('근거 문장')))
        db.flush()
        rows = shadow.revision_rows(db, rev, doc)
        assert rows[0][1].extraction.parser_version == 'fact-fusion-paddle-v2'


def test_pinned_revision_rejects_fallback_before_storage(tmp_path, monkeypatch):
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    pdf = tmp_path/'original.pdf'; pdf.write_bytes(b'fixture')
    observed = SimpleNamespace(page_number=1, native_text=None, ocr_text='text',
        final_text='text', provenance={'primary_engine':'tesseract_fallback',
            'paddle_error':'worker unavailable'}, table_facts=[])
    monkeypatch.setattr(shadow, 'extract_pdf', lambda *args: [observed])
    with Session(engine) as db:
        doc = Document(company_name='fixture', document_type=DocumentType.broker_report,
            issuer='fixture', published_at=date(2026, 1, 1), filename='fixture',
            storage_path=str(pdf), file_hash=hashlib.sha256(pdf.read_bytes()).hexdigest(),
            status=DocumentStatus.completed)
        db.add(doc); db.flush()
        with pytest.raises(ValueError, match='fingerprinted Paddle'):
            shadow.create_revision(db, doc, pdf,
                revision_version=shadow.PARSER_VERSION+'+pin-test1234')
        assert db.scalars(select(ShadowRevision)).all() == []
