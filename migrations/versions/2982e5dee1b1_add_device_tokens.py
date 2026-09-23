"""add device tokens

Adds the `device_token` table backing FCM push-notification delivery
(see services/device_token_service.py and
services/push_notification_service.py). A device token belongs to
whichever user most recently registered it — `token` is globally
unique (not unique per user), so registering a token already on file
reassigns it rather than creating a duplicate row. This also covers the
case of a different user logging into the same physical device: the
token follows the most recent registration, not the original owner.

Revision ID: 2982e5dee1b1
Revises: 4b1f5c7e2a9d
Create Date: 2026-09-22 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2982e5dee1b1'
down_revision = '4b1f5c7e2a9d'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'device_token',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('token', sa.String(length=1024), nullable=False),
        sa.Column('platform', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], name='fk_device_token_user_id'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('device_token', schema=None) as batch_op:
        batch_op.create_index('ix_device_token_user_id', ['user_id'], unique=False)
        batch_op.create_index('ix_device_token_token', ['token'], unique=True)


def downgrade():
    with op.batch_alter_table('device_token', schema=None) as batch_op:
        batch_op.drop_index('ix_device_token_token')
        batch_op.drop_index('ix_device_token_user_id')

    op.drop_table('device_token')
