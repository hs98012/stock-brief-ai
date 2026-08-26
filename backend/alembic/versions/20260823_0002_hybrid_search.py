"""add hybrid search embeddings"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260823_0002"
down_revision = "20260823_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    embedding_status = postgresql.ENUM("not_started", "processing", "completed", "failed", name="embedding_status", create_type=False)
    embedding_status.create(op.get_bind(), checkfirst=True)
    op.add_column("documents", sa.Column("embedding_status", embedding_status, nullable=False, server_default="not_started"))
    op.add_column("documents", sa.Column("embedding_model", sa.Text()))
    op.add_column("documents", sa.Column("embedding_completed_at", sa.DateTime(timezone=True)))
    op.add_column("documents", sa.Column("embedding_failure_reason", sa.Text()))
    op.add_column("documents", sa.Column("embedding_failure_chunk_id", postgresql.UUID(as_uuid=True)))
    op.add_column("chunks", sa.Column("embedding_model", sa.Text()))
    op.add_column("chunks", sa.Column("embedding_error", sa.Text()))
    op.execute("ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(1536) USING embedding::vector(1536)")
    op.execute("CREATE INDEX ix_chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops)")


def downgrade() -> None:
    op.drop_index("ix_chunks_embedding_hnsw", table_name="chunks")
    op.execute("ALTER TABLE chunks ALTER COLUMN embedding TYPE vector USING embedding::vector")
    op.drop_column("chunks", "embedding_error"); op.drop_column("chunks", "embedding_model")
    for name in ("embedding_failure_chunk_id", "embedding_failure_reason", "embedding_completed_at", "embedding_model", "embedding_status"):
        op.drop_column("documents", name)
    op.execute(sa.text("DROP TYPE IF EXISTS embedding_status"))
