"""add_guest_token_to_jobs

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-10-25 10:45:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add guest_token column and index to jobs table."""
    op.add_column(
        'jobs',
        sa.Column('guest_token', sa.String(length=64), nullable=True),
    )
    op.create_index(
        'ix_jobs_guest_token',
        'jobs',
        ['guest_token'],
        unique=False,
    )


def downgrade() -> None:
    """Remove guest_token column and index from jobs table."""
    op.drop_index('ix_jobs_guest_token', table_name='jobs')
    op.drop_column('jobs', 'guest_token')
