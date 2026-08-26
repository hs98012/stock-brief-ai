import hashlib
import os
import shutil
import uuid
from datetime import date
from pathlib import Path

from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session

from .chunking import split_page
from .models import Chunk, Document, DocumentStatus, DocumentType, Page
from .pdf_pipeline import extract_pdf

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))
DATA_DIR = Path(os.getenv("DATA_DIR", Path(__file__).resolve().parents[1] / "data"))


def _read_upload(file: UploadFile) -> bytes:
    if not file.filename or Path(file.filename).suffix.lower() != ".pdf":
        raise HTTPException(415, "PDF 파일만 업로드할 수 있습니다.")
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"파일 크기는 {MAX_UPLOAD_BYTES}바이트를 초과할 수 없습니다.")
    if not data.startswith(b"%PDF-"):
        raise HTTPException(400, "PDF 서명이 없거나 손상된 파일입니다.")
    return data


def ingest_document(db: Session, file: UploadFile, company_name: str, stock_code: str, document_type: DocumentType, issuer: str, published_at: date) -> tuple[Document, bool]:
    data = _read_upload(file)
    digest = hashlib.sha256(data).hexdigest()
    existing = db.query(Document).filter(Document.file_hash == digest).one_or_none()
    if existing:
        return existing, True
    document_id = uuid.uuid4()
    raw_dir = DATA_DIR / "raw"; image_dir = DATA_DIR / "pages" / str(document_id)
    raw_dir.mkdir(parents=True, exist_ok=True)
    safe_name = f"{document_id}.pdf"; path = raw_dir / safe_name; path.write_bytes(data)
    document = Document(id=document_id, company_name=company_name, stock_code=stock_code, document_type=document_type,
        issuer=issuer, published_at=published_at, filename=Path(file.filename or safe_name).name, storage_path=str(path),
        file_hash=digest, status=DocumentStatus.processing)
    db.add(document); db.commit()
    try:
        extracted = extract_pdf(path, image_dir)
        for result in extracted:
            page = Page(document_id=document.id, page_number=result.page_number, native_text=result.native_text, ocr_text=result.ocr_text,
                final_text=result.final_text, text_source=result.text_source, page_image_path=result.page_image_path, ocr_error=result.ocr_error)
            db.add(page); db.flush()
            for span in split_page(result.final_text):
                db.add(Chunk(document_id=document.id, page_id=page.id, page_number=result.page_number, section_title=None,
                    content=span.content, char_start=span.char_start, char_end=span.char_end, embedding=None))
        document.total_pages = len(extracted)
        document.status = DocumentStatus.completed_with_errors if any(page.ocr_error for page in extracted) else DocumentStatus.completed
        db.commit(); db.refresh(document)
    except ValueError as exc:
        document.status = DocumentStatus.failed; document.error_reason = str(exc); db.commit()
        path.unlink(missing_ok=True); shutil.rmtree(image_dir, ignore_errors=True)
        raise HTTPException(400, str(exc)) from exc
    except Exception:
        db.rollback()
        failed = db.get(Document, document.id)
        if failed:
            failed.status = DocumentStatus.failed; failed.error_reason = "문서 처리 중 오류가 발생했습니다."; db.commit()
        raise HTTPException(500, "문서 처리 중 오류가 발생했습니다.")
    return document, False

