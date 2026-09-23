"""add reminder.notified_at

Adds the single column the reminder delivery worker needs to guarantee
a reminder is never notified twice (see
services/reminder_delivery_service.py): `notified_at` starts NULL and
is set exactly once, via a conditional `UPDATE ... WHERE notified_at
IS NULL`, at the moment a reminder is claimed for processing. This is
deliberately the only schema change this phase needs — `status` and
every other Reminder field are untouched.

Revision ID: 41cb27a20370
Revises: 2982e5dee1b1
Create Date: 2026-09-22 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '41cb27a20370'
down_revision = '2982e5dee1b1'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('reminder', schema=None) as batch_op:
        batch_op.add_column(sa.Column('notified_at', sa.DateTime(), nullable=True))
        batch_op.create_index('ix_reminder_notified_at', ['notified_at'], unique=False)


def downgrade():
    with op.batch_alter_table('reminder', schema=None) as batch_op:
        batch_op.drop_index('ix_reminder_notified_at')
        batch_op.drop_column('notified_at')
