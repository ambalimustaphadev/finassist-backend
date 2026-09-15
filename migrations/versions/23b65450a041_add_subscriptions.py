"""add subscriptions

Adds the `subscription` table backing the Subscription Tracker feature.
A subscription is a recurring financial commitment with a schedule
(name, amount, currency, frequency, next billing date) — not a
transaction, so no financial history is created or implied by this
table on its own.

Revision ID: 23b65450a041
Revises: 7fbf55826671
Create Date: 2026-09-15 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '23b65450a041'
down_revision = '7fbf55826671'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'subscription',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('amount', sa.Float(), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('frequency', sa.String(length=20), nullable=False),
        sa.Column('next_billing_date', sa.Date(), nullable=False),
        sa.Column('category', sa.String(length=30), nullable=True),
        sa.Column('payment_method', sa.String(length=30), nullable=True),
        sa.Column('website', sa.String(length=512), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('cancelled_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], name='fk_subscription_user_id'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('subscription', schema=None) as batch_op:
        batch_op.create_index('ix_subscription_user_id', ['user_id'], unique=False)


def downgrade():
    with op.batch_alter_table('subscription', schema=None) as batch_op:
        batch_op.drop_index('ix_subscription_user_id')

    op.drop_table('subscription')
