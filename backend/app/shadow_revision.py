"""Explicit shadow-only ingestion/search. Never modifies active ORM objects."""
import hashlib
import math
import tempfile
from pathlib import Path
from types import SimpleNamespace
from sqlalchemy import select
from .chunking import split_page, structured_spans
from .pdf_pipeline import extract_pdf
from .pdf_pipeline import PARSER_VERSION
from .shadow_models import ShadowRevision, ShadowPage, ShadowChunk
from .search import rank_rows
from .fused_index import retrieval_text


def create_revision(db, document, pdf: Path, *, revision_version: str | None = None):
    revision_version = revision_version or PARSER_VERSION
    if revision_version != PARSER_VERSION and not revision_version.startswith(PARSER_VERSION + '+pin-'):
        raise ValueError('Invalid shadow-only revision version')
    digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
    if digest != document.file_hash:
        raise ValueError('Original PDF hash mismatch')
    # Serialize concurrent builds for a document without modifying its row.
    if db.bind.dialect.name == 'postgresql':
        from sqlalchemy import text
        db.execute(text('SELECT pg_advisory_xact_lock(:key)'),
                   {'key': int(digest[:15], 16)})
    existing = db.scalar(select(ShadowRevision).where(
        ShadowRevision.document_id == document.id, ShadowRevision.file_hash == digest,
        ShadowRevision.parser_version == revision_version))
    if existing:
        return existing
    with tempfile.TemporaryDirectory() as directory:
        extracted = extract_pdf(pdf, Path(directory))
    if revision_version != PARSER_VERSION:
        for page in extracted:
            provenance = page.provenance
            if (provenance.get('paddle_error') or
                    provenance.get('primary_engine') == 'tesseract_fallback' or
                    (provenance.get('primary_engine') == 'paddle_structure' and
                     not provenance.get('paddle_fingerprint_sha256'))):
                raise ValueError('Pinned revision requires fingerprinted Paddle or valid native extraction')
    revision = ShadowRevision(document_id=document.id, file_hash=digest,
                              parser_version=revision_version, status='parsed')
    db.add(revision); db.flush()
    for result in extracted:
        page = ShadowPage(revision_id=revision.id, page_number=result.page_number,
            native_text=result.native_text, ocr_text=result.ocr_text, final_text=result.final_text,
            final_text_sha256=hashlib.sha256(result.final_text.encode()).hexdigest(),
            provenance=result.provenance, table_facts=result.table_facts)
        db.add(page); db.flush()
        chunks = []
        for span in structured_spans(page.final_text, page.provenance):
            chunk = ShadowChunk(revision_id=revision.id, page_id=page.id, content=span.content,
                                char_start=span.char_start, char_end=span.char_end)
            db.add(chunk); chunks.append(chunk)
        db.flush()
        page.table_facts = [{**fact, 'source_chunk_ids': sorted({str(c.id)
            for s in fact['source_spans'] for c in chunks
            if c.char_start < s['char_end'] and c.char_end > s['char_start']})}
            for fact in page.table_facts]
    return revision


def embed_revision(db, revision_id, provider):
    if (provider.provider_name, provider.model, provider.dimensions) != ('ollama', 'bge-m3', 1024):
        raise ValueError('Shadow evaluation requires Ollama bge-m3 1024')
    revision = db.scalar(select(ShadowRevision).where(ShadowRevision.id == revision_id).with_for_update())
    chunks = db.scalars(select(ShadowChunk).where(ShadowChunk.revision_id == revision_id)
                        .order_by(ShadowChunk.id)).all()
    if not chunks:
        raise ValueError('No shadow chunks')
    for chunk in chunks:
        if chunk.embedding is not None:
            if (chunk.embedding_provider, chunk.embedding_model, chunk.embedding_dimensions) != (
                    provider.provider_name, provider.model, provider.dimensions):
                raise ValueError('Existing shadow embedding configuration mismatch')
            continue
        stored = db.get(ShadowPage, chunk.page_id)
        adapted_page = SimpleNamespace(extraction=SimpleNamespace(parser_version=revision.parser_version.split('+pin-')[0],
            provenance=stored.provenance, table_facts=stored.table_facts))
        vectors = provider.embed([retrieval_text(chunk, adapted_page)])
        if len(vectors) != 1 or len(vectors[0]) != 1024 or not all(math.isfinite(v) for v in vectors[0]):
            raise ValueError('Invalid embedding')
        chunk.embedding = vectors[0]
        chunk.embedding_provider = provider.provider_name
        chunk.embedding_model = provider.model
        chunk.embedding_dimensions = provider.dimensions
    revision.status = 'ready'


def revision_rows(db, revision, document):
    if revision.document_id != document.id or revision.file_hash != document.file_hash:
        raise ValueError('Revision/document mismatch')
    rows = []
    for chunk, stored in db.execute(select(ShadowChunk, ShadowPage).join(
            ShadowPage, ShadowChunk.page_id == ShadowPage.id).where(
            ShadowChunk.revision_id == revision.id, ShadowPage.revision_id == revision.id)):
        page = SimpleNamespace(id=stored.id, document_id=document.id,
            page_number=stored.page_number, final_text=stored.final_text,
            extraction=SimpleNamespace(parser_version=revision.parser_version.split('+pin-')[0],
                final_text_sha256=stored.final_text_sha256, provenance=stored.provenance,
                table_facts=stored.table_facts))
        adapted = SimpleNamespace(**{column.name: getattr(chunk, column.name)
            for column in ShadowChunk.__table__.columns}, document_id=document.id,
            page_number=stored.page_number, section_title=None)
        rows.append((adapted, page, document))
    return rows


def search_revision(db, revision, document, question, provider):
    if revision.status != 'ready':
        raise ValueError('Revision embeddings are not ready')
    return rank_rows(revision_rows(db, revision, document), question, 5, provider, diagnostics=True)
