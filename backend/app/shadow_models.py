"""Isolated evaluation storage. No active pointer or active ORM relationships."""
import uuid
from datetime import datetime
from sqlalchemy import ForeignKey, String, Text, UniqueConstraint, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON
from .models import Base, Vector


class ShadowRevision(Base):
    __tablename__ = 'shadow_revisions'
    __table_args__ = (UniqueConstraint('document_id', 'file_hash', 'parser_version'),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('documents.id'))
    file_hash: Mapped[str] = mapped_column(String(64))
    parser_version: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default='parsed')
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ShadowPage(Base):
    __tablename__ = 'shadow_pages'
    __table_args__ = (UniqueConstraint('revision_id', 'page_number'),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    revision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('shadow_revisions.id'))
    page_number: Mapped[int]
    native_text: Mapped[str | None] = mapped_column(Text)
    ocr_text: Mapped[str | None] = mapped_column(Text)
    final_text: Mapped[str] = mapped_column(Text)
    final_text_sha256: Mapped[str] = mapped_column(String(64))
    provenance: Mapped[dict] = mapped_column(JSON)
    table_facts: Mapped[list] = mapped_column(JSON)


class ShadowChunk(Base):
    __tablename__ = 'shadow_chunks'
    __table_args__ = (UniqueConstraint('page_id', 'char_start', 'char_end'),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    revision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('shadow_revisions.id'))
    page_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('shadow_pages.id'))
    content: Mapped[str] = mapped_column(Text)
    char_start: Mapped[int]
    char_end: Mapped[int]
    embedding: Mapped[list | None] = mapped_column(Vector())
    embedding_provider: Mapped[str | None] = mapped_column(Text)
    embedding_model: Mapped[str | None] = mapped_column(Text)
    embedding_dimensions: Mapped[int | None]
