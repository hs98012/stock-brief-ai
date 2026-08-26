from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from .embeddings import EmbeddingConfigurationError, EmbeddingProvider
from .models import Chunk, Document, EmbeddingStatus

BATCH_SIZE = 100


@dataclass(frozen=True)
class EmbeddingRun:
    document: Document; processed: int; skipped: int; failed: int


def embed_document(db: Session, document: Document, provider: EmbeddingProvider) -> EmbeddingRun:
    chunks = db.query(Chunk).filter(Chunk.document_id == document.id).order_by(Chunk.page_number, Chunk.char_start).all()
    pending = [chunk for chunk in chunks if chunk.embedding is None or chunk.embedding_provider != provider.provider_name or chunk.embedding_model != provider.model or chunk.embedding_dimensions != provider.dimensions]
    skipped = len(chunks) - len(pending)
    document.embedding_status = EmbeddingStatus.processing; document.embedding_provider = provider.provider_name
    document.embedding_model = provider.model; document.embedding_dimensions = provider.dimensions
    document.embedding_failure_reason = None; document.embedding_failure_chunk_id = None; document.embedding_completed_at = None
    db.commit()
    processed = failed = 0
    for start in range(0, len(pending), BATCH_SIZE):
        batch = pending[start:start + BATCH_SIZE]
        try:
            vectors = provider.embed([chunk.content for chunk in batch])
            if len(vectors) != len(batch):
                raise RuntimeError("임베딩 응답 개수가 요청 청크 수와 다릅니다.")
            for chunk, vector in zip(batch, vectors, strict=True):
                chunk.embedding = vector; chunk.embedding_provider = provider.provider_name
                chunk.embedding_model = provider.model; chunk.embedding_dimensions = provider.dimensions; chunk.embedding_error = None
                processed += 1
            db.commit()
        except Exception as exc:
            db.rollback()
            reason = str(exc) if isinstance(exc, EmbeddingConfigurationError) else f"임베딩 처리 실패: {type(exc).__name__}"
            failed += len(batch)
            for chunk in batch:
                persisted = db.get(Chunk, chunk.id)
                if persisted:
                    persisted.embedding_error = reason
            document = db.get(Document, document.id)
            document.embedding_status = EmbeddingStatus.failed
            document.embedding_failure_reason = reason
            document.embedding_failure_chunk_id = batch[0].id if batch else None
            db.commit()
            if isinstance(exc, EmbeddingConfigurationError):
                raise
            break
    document = db.get(Document, document.id)
    if failed == 0:
        document.embedding_status = EmbeddingStatus.completed
        document.embedding_completed_at = datetime.now(timezone.utc)
        db.commit()
    db.refresh(document)
    return EmbeddingRun(document, processed, skipped, failed)


def embedding_counts(db: Session, document_id: UUID, provider: str | None, model: str | None, dimensions: int | None) -> tuple[int, int, int]:
    chunks = db.query(Chunk).filter(Chunk.document_id == document_id).all()
    embedded = sum(chunk.embedding is not None and (provider is None or chunk.embedding_provider == provider)
        and (model is None or chunk.embedding_model == model) and (dimensions is None or chunk.embedding_dimensions == dimensions) for chunk in chunks)
    failed = sum(bool(chunk.embedding_error) for chunk in chunks)
    return len(chunks), embedded, failed
