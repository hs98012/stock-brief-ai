from datetime import date

from app.citations import restore_citation
from app.models import Chunk, Document, DocumentStatus, DocumentType, Page, TextSource


def test_citation_restores_exact_source_span(db) -> None:
    document = Document(company_name="Example", stock_code="000000", document_type=DocumentType.dart_filing, issuer="Issuer",
        published_at=date(2026, 8, 23), filename="source.pdf", storage_path="/data/raw/id.pdf", file_hash="a" * 64, status=DocumentStatus.completed, total_pages=1)
    db.add(document); db.flush()
    text = "Original units and table-like text remain exactly where they appeared."
    page = Page(document_id=document.id, page_number=1, final_text=text, native_text=text, text_source=TextSource.native)
    db.add(page); db.flush()
    chunk = Chunk(document_id=document.id, page_id=page.id, page_number=1, content=text[9:32], char_start=9, char_end=32)
    db.add(chunk); db.commit()
    citation = restore_citation(db, chunk.id)
    assert citation.quote == text[9:32]
    assert citation.filename == "source.pdf" and citation.page_number == 1

