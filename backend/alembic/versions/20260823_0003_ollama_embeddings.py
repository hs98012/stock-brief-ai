"""switch embeddings to Ollama bge-m3 dimensions"""
from alembic import op
import sqlalchemy as sa

revision = "20260823_0003"
down_revision = "20260823_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    populated = connection.execute(sa.text("SELECT count(*) FROM chunks WHERE embedding IS NOT NULL")).scalar_one()
    if populated:
        raise RuntimeError(
            f"{populated}개의 기존 1536차원 임베딩이 있습니다. 자동 삭제·변환하지 않습니다. "
            "기존 임베딩을 명시적으로 백업·비운 뒤 bge-m3로 재임베딩하세요."
        )
    op.drop_index("ix_chunks_embedding_hnsw", table_name="chunks")
    op.execute("ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(1024) USING embedding::vector(1024)")
    op.execute("CREATE INDEX ix_chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops)")
    op.add_column("documents", sa.Column("embedding_provider", sa.Text()))
    op.add_column("documents", sa.Column("embedding_dimensions", sa.Integer()))
    op.add_column("chunks", sa.Column("embedding_provider", sa.Text()))
    op.add_column("chunks", sa.Column("embedding_dimensions", sa.Integer()))


def downgrade() -> None:
    connection = op.get_bind()
    populated = connection.execute(sa.text("SELECT count(*) FROM chunks WHERE embedding IS NOT NULL")).scalar_one()
    if populated:
        raise RuntimeError("1024차원 임베딩이 존재해 안전하게 downgrade할 수 없습니다. 먼저 명시적으로 백업·비우세요.")
    op.drop_column("chunks", "embedding_dimensions"); op.drop_column("chunks", "embedding_provider")
    op.drop_column("documents", "embedding_dimensions"); op.drop_column("documents", "embedding_provider")
    op.drop_index("ix_chunks_embedding_hnsw", table_name="chunks")
    op.execute("ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(1536) USING embedding::vector(1536)")
    op.execute("CREATE INDEX ix_chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops)")
