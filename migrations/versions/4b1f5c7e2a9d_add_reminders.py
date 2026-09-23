"""add reminders

Adds the `reminder` table backing the AI-chat reminder tools
(create_reminder / list_reminders / delete_reminder). A reminder is a
user-created "remind me at this time" entry, always scoped to the
authenticated user who created it — see services/reminder_service.py.

`remind_at` is stored as a naive UTC datetime, matching every other
DateTime column in this database: the caller is required to supply an
explicit UTC offset (services.reminder_service rejects anything
without one), which is then converted to UTC before being written here.

Revision ID: 4b1f5c7e2a9d
Revises: 23b65450a041
Create Date: 2026-09-22 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4b1f5c7e2a9d'
down_revision = '23b65450a041'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'reminder',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=120), nullable=False),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('remind_at', sa.DateTime(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], name='fk_reminder_user_id'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('reminder', schema=None) as batch_op:
        batch_op.create_index('ix_reminder_user_id', ['user_id'], unique=False)
        batch_op.create_index('ix_reminder_remind_at', ['remind_at'], unique=False)


def downgrade():
    with op.batch_alter_table('reminder', schema=None) as batch_op:
        batch_op.drop_index('ix_reminder_remind_at')
        batch_op.drop_index('ix_reminder_user_id')

    op.drop_table('reminder')
