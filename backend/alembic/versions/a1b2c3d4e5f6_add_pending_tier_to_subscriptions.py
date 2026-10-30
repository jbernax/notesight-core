"""add_pending_tier_to_subscriptions

Revision ID: a1b2c3d4e5f6
Revises: 9b8c7d6e5f4a
Create Date: 2026-10-22 08:45:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '9b8c7d6e5f4a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add pending_tier and downgrade_scheduled_at to subscriptions table."""
    usertier_enum = postgresql.ENUM('starter', 'pro', 'virtuoso', 'maestro', name='usertier', create_type=False)
    op.add_column(
        'subscriptions',
        sa.Column('pending_tier', usertier_enum, nullable=True),
    )
    op.add_column(
        'subscriptions',
        sa.Column('downgrade_scheduled_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Remove pending_tier and downgrade_scheduled_at from subscriptions table."""
    op.drop_column('subscriptions', 'downgrade_scheduled_at')
    op.drop_column('subscriptions', 'pending_tier')
