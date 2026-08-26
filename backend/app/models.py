import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, TypeDecorator
from pgvector.sqlalchemy import Vector as PgVector


EMBEDDING_DIMENSIONS = 1024


class Vector(TypeDecorator):
    impl = JSON
    cache_ok = True
    class comparator_factory(TypeDecorator.Comparator):
        def cosine_distance(self, other: object):
            return self.expr.op("<=>")(other)
    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PgVector(EMBEDDING_DIMENSIONS))
        return dialect.type_descriptor(JSON())


class Base(DeclarativeBase): pass
class DocumentType(str, enum.Enum): broker_report = "broker_report"; dart_filing = "dart_filing"
class DocumentStatus(str, enum.Enum): processing = "processing"; completed = "completed"; completed_with_errors = "completed_with_errors"; failed = "failed"
class TextSource(str, enum.Enum): native = "native"; ocr = "ocr"; none = "none"
class EmbeddingStatus(str, enum.Enum): not_started = "not_started"; processing = "processing"; completed = "completed"; failed = "failed"


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_name: Mapped[str] = mapped_column(Text); stock_code: Mapped[str | None] = mapped_column(String(12), nullable=True)
    document_type: Mapped[DocumentType] = mapped_column(Enum(DocumentType, name="document_type")); issuer: Mapped[str] = mapped_column(Text)
    published_at: Mapped[date] = mapped_column(Date); filename: Mapped[str] = mapped_column(Text); storage_path: Mapped[str] = mapped_column(Text)
    file_hash: Mapped[str] = mapped_column(String(64), unique=True); status: Mapped[DocumentStatus] = mapped_column(Enum(DocumentStatus, name="document_status"))
    error_reason: Mapped[str | None] = mapped_column(Text); total_pages: Mapped[int | None] = mapped_column(Integer)
    embedding_status: Mapped[EmbeddingStatus] = mapped_column(Enum(EmbeddingStatus, name="embedding_status"), default=EmbeddingStatus.not_started)
    embedding_provider: Mapped[str | None] = mapped_column(Text); embedding_model: Mapped[str | None] = mapped_column(Text)
    embedding_dimensions: Mapped[int | None] = mapped_column(Integer); embedding_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    embedding_failure_reason: Mapped[str | None] = mapped_column(Text); embedding_failure_chunk_id: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    pages: Mapped[list["Page"]] = relationship(cascade="all, delete-orphan", order_by="Page.page_number")


class Page(Base):
    __tablename__ = "pages"; __table_args__ = (UniqueConstraint("document_id", "page_number"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE")); page_number: Mapped[int]
    native_text: Mapped[str | None] = mapped_column(Text); ocr_text: Mapped[str | None] = mapped_column(Text)
    final_text: Mapped[str] = mapped_column(Text, default=""); text_source: Mapped[TextSource] = mapped_column(Enum(TextSource, name="text_source"))
    page_image_path: Mapped[str | None] = mapped_column(Text); ocr_error: Mapped[str | None] = mapped_column(Text)
    chunks: Mapped[list["Chunk"]] = relationship(cascade="all, delete-orphan", order_by="Chunk.char_start")


class Chunk(Base):
    __tablename__ = "chunks"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE")); page_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"))
    page_number: Mapped[int]; section_title: Mapped[str | None] = mapped_column(Text); content: Mapped[str] = mapped_column(Text)
    char_start: Mapped[int]; char_end: Mapped[int]; embedding: Mapped[list[float] | None] = mapped_column(Vector(), nullable=True)
    embedding_provider: Mapped[str | None] = mapped_column(Text); embedding_model: Mapped[str | None] = mapped_column(Text)
    embedding_dimensions: Mapped[int | None] = mapped_column(Integer); embedding_error: Mapped[str | None] = mapped_column(Text)


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    question: Mapped[str] = mapped_column(Text); status: Mapped[str] = mapped_column(String(32))
    generation_provider: Mapped[str | None] = mapped_column(Text); generation_model: Mapped[str | None] = mapped_column(Text)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True)); error_reason: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
