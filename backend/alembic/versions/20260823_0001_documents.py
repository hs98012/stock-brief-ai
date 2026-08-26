"""create document ingestion tables"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.types import UserDefinedType


class LegacyVector(UserDefinedType):
    def get_col_spec(self, **kw: object) -> str:
        return "vector"

revision = "20260823_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    document_type = postgresql.ENUM("broker_report", "dart_filing", name="document_type", create_type=False)
    document_status = postgresql.ENUM("processing", "completed", "completed_with_errors", "failed", name="document_status", create_type=False)
    text_source = postgresql.ENUM("native", "ocr", "none", name="text_source", create_type=False)
    document_type.create(op.get_bind(), checkfirst=True)
    document_status.create(op.get_bind(), checkfirst=True)
    text_source.create(op.get_bind(), checkfirst=True)
    op.create_table("documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_name", sa.Text(), nullable=False), sa.Column("stock_code", sa.String(12), nullable=False),
        sa.Column("document_type", document_type, nullable=False), sa.Column("issuer", sa.Text(), nullable=False),
        sa.Column("published_at", sa.Date(), nullable=False), sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False), sa.Column("file_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("status", document_status, nullable=False), sa.Column("error_reason", sa.Text()),
        sa.Column("total_pages", sa.Integer()), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("total_pages IS NULL OR total_pages >= 0", name="ck_documents_total_pages"))
    op.create_table("pages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False), sa.Column("native_text", sa.Text()), sa.Column("ocr_text", sa.Text()),
        sa.Column("final_text", sa.Text(), nullable=False, server_default=""), sa.Column("text_source", text_source, nullable=False),
        sa.Column("page_image_path", sa.Text()), sa.Column("ocr_error", sa.Text()),
        sa.CheckConstraint("page_number >= 1", name="ck_pages_page_number"), sa.UniqueConstraint("document_id", "page_number", name="uq_pages_document_page"))
    op.create_table("chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("pages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False), sa.Column("section_title", sa.Text()), sa.Column("content", sa.Text(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False), sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("embedding", LegacyVector(), nullable=True),
        sa.CheckConstraint("page_number >= 1", name="ck_chunks_page_number"),
        sa.CheckConstraint("char_start >= 0 AND char_end > char_start", name="ck_chunks_char_range"))


def downgrade() -> None:
    op.drop_table("chunks"); op.drop_table("pages"); op.drop_table("documents")
    for name in ("text_source", "document_status", "document_type"):
        op.execute(sa.text(f"DROP TYPE IF EXISTS {name}"))
