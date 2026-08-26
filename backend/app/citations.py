from sqlalchemy.orm import Session

from .models import Chunk, Document, Page
from .schemas import Citation


def restore_citation(db: Session, chunk_id: object) -> Citation:
    row = db.query(Chunk, Page, Document).join(Page, Chunk.page_id == Page.id).join(Document, Chunk.document_id == Document.id).filter(Chunk.id == chunk_id).one()
    chunk, page, document = row
    quote = page.final_text[chunk.char_start:chunk.char_end]
    if quote != chunk.content or chunk.page_number != page.page_number:
        raise ValueError("청크의 인용 위치가 원문 페이지와 일치하지 않습니다.")
    return Citation(filename=document.filename, published_at=document.published_at, page_number=page.page_number, quote=quote)

