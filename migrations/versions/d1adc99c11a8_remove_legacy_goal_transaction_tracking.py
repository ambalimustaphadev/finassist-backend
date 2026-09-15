"""remove legacy goal/transaction tracking

FinAssist is now an AI-first chat product; it no longer maintains a
manual financial-goal or transaction ledger (that data now lives only
inside user-uploaded documents analyzed by the AI). This drops the
`financial_goal` and `transaction` tables and the `user_preference`
columns that existed only to support them.

Data check performed before writing this migration (see the backend
legacy-feature-cleanup task): the local dev database held one
`financial_goal` row and zero `transaction` rows; both were exported to
a local backup file outside the repo before this migration was applied
there. This project has no separate production database — `config.py`
points at the same SQLite file in every environment — so there is no
additional production data to account for. Anyone applying this
migration against a database with real user data in these tables
should export it first; this migration does not do that automatically.

Revision ID: d1adc99c11a8
Revises: 29bd12a2dde1
Create Date: 2026-09-14 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd1adc99c11a8'
down_revision = '29bd12a2dde1'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user_preference', schema=None) as batch_op:
        batch_op.drop_column('goal_notifications')
        batch_op.drop_column('financial_reminders')

    with op.batch_alter_table('transaction', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_transaction_user_id'))
        batch_op.drop_index(batch_op.f('ix_transaction_date'))
    op.drop_table('transaction')

    with op.batch_alter_table('financial_goal', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_financial_goal_user_id'))
        batch_op.drop_index(batch_op.f('ix_financial_goal_status'))
    op.drop_table('financial_goal')


def downgrade():
    op.create_table('financial_goal',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('target_amount', sa.Float(), nullable=False),
    sa.Column('current_amount', sa.Float(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('target_date', sa.Date(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('financial_goal', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_financial_goal_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_financial_goal_user_id'), ['user_id'], unique=False)

    op.create_table('transaction',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('description', sa.String(length=255), nullable=True),
    sa.Column('amount', sa.Float(), nullable=False),
    sa.Column('type', sa.String(length=20), nullable=False),
    sa.Column('category', sa.String(length=60), nullable=True),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('transaction', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_transaction_date'), ['date'], unique=False)
        batch_op.create_index(batch_op.f('ix_transaction_user_id'), ['user_id'], unique=False)

    with op.batch_alter_table('user_preference', schema=None) as batch_op:
        batch_op.add_column(sa.Column('financial_reminders', sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column('goal_notifications', sa.Boolean(), nullable=False, server_default=sa.true()))
