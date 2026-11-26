"""Add isolated shadow evaluation tables; no backfill or activation."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from pgvector.sqlalchemy import Vector
revision = '20260923_0006'
down_revision = '20260922_0005'
branch_labels = depends_on = None


def upgrade():
    op.create_table('shadow_revisions',
        sa.Column('id', UUID(), primary_key=True),
        sa.Column('document_id', UUID(), sa.ForeignKey('documents.id'), nullable=False),
        sa.Column('file_hash', sa.String(64), nullable=False),
        sa.Column('parser_version', sa.String(64), nullable=False),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('error', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('document_id', 'file_hash', 'parser_version'))
    op.create_table('shadow_pages',
        sa.Column('id', UUID(), primary_key=True),
        sa.Column('revision_id', UUID(), sa.ForeignKey('shadow_revisions.id'), nullable=False),
        sa.Column('page_number', sa.Integer(), nullable=False),
        sa.Column('native_text', sa.Text()), sa.Column('ocr_text', sa.Text()),
        sa.Column('final_text', sa.Text(), nullable=False),
        sa.Column('final_text_sha256', sa.String(64), nullable=False),
        sa.Column('provenance', sa.JSON(), nullable=False), sa.Column('table_facts', sa.JSON(), nullable=False),
        sa.UniqueConstraint('revision_id', 'page_number'))
    op.create_table('shadow_chunks',
        sa.Column('id', UUID(), primary_key=True),
        sa.Column('revision_id', UUID(), sa.ForeignKey('shadow_revisions.id'), nullable=False),
        sa.Column('page_id', UUID(), sa.ForeignKey('shadow_pages.id'), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('char_start', sa.Integer(), nullable=False), sa.Column('char_end', sa.Integer(), nullable=False),
        sa.Column('embedding', Vector(1024)), sa.Column('embedding_provider', sa.Text()),
        sa.Column('embedding_model', sa.Text()), sa.Column('embedding_dimensions', sa.Integer()),
        sa.UniqueConstraint('page_id', 'char_start', 'char_end'))


def downgrade():
    raise RuntimeError('Shadow revisions are retained; destructive downgrade disabled')
