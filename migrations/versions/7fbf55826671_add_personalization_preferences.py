"""add personalization preferences

Adds the four fields the personalization flow collects (financial
experience, conversation interests, response style, proactive
suggestions) to `user_preference`. This only persists the data — the AI
does not consume these fields yet (see a later task for that).

`financial_experience`, `interests`, and `response_style` are nullable
with no default: they are real user selections, so an existing user who
hasn't been through the personalization flow must read back `null`
rather than a fabricated guess. `proactive_suggestions` is a behavior
toggle (like the existing `notifications_enabled`/`document_notifications`
columns), so it gets the same non-nullable-with-default treatment,
backfilled to `true` via `server_default` for rows that already exist.

Revision ID: 7fbf55826671
Revises: d1adc99c11a8
Create Date: 2026-09-14 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7fbf55826671'
down_revision = 'd1adc99c11a8'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user_preference', schema=None) as batch_op:
        batch_op.add_column(sa.Column('financial_experience', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('interests', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('response_style', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('proactive_suggestions', sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade():
    with op.batch_alter_table('user_preference', schema=None) as batch_op:
        batch_op.drop_column('proactive_suggestions')
        batch_op.drop_column('response_style')
        batch_op.drop_column('interests')
        batch_op.drop_column('financial_experience')
