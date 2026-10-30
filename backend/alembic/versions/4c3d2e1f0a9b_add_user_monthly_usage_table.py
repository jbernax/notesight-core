"""add_user_monthly_usage_table

Revision ID: 4c3d2e1f0a9b
Revises: 3b2c1d0e9f8a
Create Date: 2026-10-03 12:55:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4c3d2e1f0a9b'
down_revision: Union[str, Sequence[str], None] = '3b2c1d0e9f8a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: add user_monthly_usage table to track monthly transcription volume across library score deletions."""
    op.create_table(
        'user_monthly_usage',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('month', sa.Integer(), nullable=False),
        sa.Column('deleted_job_pages', sa.Integer(), nullable=False, server_default='0'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_user_monthly_usage_user_id'), 'user_monthly_usage', ['user_id'], unique=False)
    op.create_index(
        'ix_user_monthly_usage_user_year_month',
        'user_monthly_usage',
        ['user_id', 'year', 'month'],
        unique=True,
    )


def downgrade() -> None:
    """Downgrade schema: drop user_monthly_usage table."""
    op.drop_index('ix_user_monthly_usage_user_year_month', table_name='user_monthly_usage')
    op.drop_index(op.f('ix_user_monthly_usage_user_id'), table_name='user_monthly_usage')
    op.drop_table('user_monthly_usage')
