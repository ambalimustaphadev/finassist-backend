"""add upload_file.content_hash

Revision ID: 7f3a92c1d4e5
Revises: 1d696b7bf091
Create Date: 2026-08-27 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7f3a92c1d4e5'
down_revision = '1d696b7bf091'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('upload_file', schema=None) as batch_op:
        batch_op.add_column(sa.Column('content_hash', sa.String(length=64), nullable=True))
        batch_op.create_index(
            batch_op.f('ix_upload_file_content_hash'), ['content_hash'], unique=False
        )


def downgrade():
    with op.batch_alter_table('upload_file', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_upload_file_content_hash'))
        batch_op.drop_column('content_hash')
