"""Add new-upload extraction observations; no backfill or existing row changes."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20260922_0005'
down_revision = '20260823_0004'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('page_extractions',
        sa.Column('page_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('pages.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('parser_version', sa.String(64), nullable=False),
        sa.Column('final_text_sha256', sa.String(64), nullable=False),
        sa.Column('provenance', sa.JSON(), nullable=False),
        sa.Column('table_facts', sa.JSON(), nullable=False))


def downgrade():
    if op.get_bind().execute(sa.text('SELECT count(*) FROM page_extractions')).scalar_one():
        raise RuntimeError('Extraction provenance exists; refusing destructive downgrade.')
    op.drop_table('page_extractions')
