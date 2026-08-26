"""add metadata correction and grounded analyses"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260823_0004"
down_revision = "20260823_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("documents", "stock_code", existing_type=sa.String(12), nullable=True)
    op.create_table("analysis_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question", sa.Text(), nullable=False), sa.Column("status", sa.String(32), nullable=False),
        sa.Column("generation_provider", sa.Text()), sa.Column("generation_model", sa.Text()),
        sa.Column("generated_at", sa.DateTime(timezone=True)), sa.Column("error_reason", sa.Text()),
        sa.Column("result", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_analysis_runs_document_id", "analysis_runs", ["document_id"])


def downgrade() -> None:
    op.drop_index("ix_analysis_runs_document_id", table_name="analysis_runs")
    op.drop_table("analysis_runs")
    null_codes = op.get_bind().execute(sa.text("SELECT count(*) FROM documents WHERE stock_code IS NULL")).scalar_one()
    if null_codes:
        raise RuntimeError("stock_code가 NULL인 문서가 있어 안전하게 downgrade할 수 없습니다.")
    op.alter_column("documents", "stock_code", existing_type=sa.String(12), nullable=False)
