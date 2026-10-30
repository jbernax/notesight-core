"""add_quota_tier_and_file_size

Revision ID: 2a1b3c4d5e6f
Revises: 15d6cec994f4
Create Date: 2026-10-02 22:40:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '2a1b3c4d5e6f'
down_revision: Union[str, Sequence[str], None] = '15d6cec994f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: add usertier enum, users.tier, and jobs.file_size_bytes."""
    # Create enum type with checkfirst
    usertier_enum = postgresql.ENUM('starter', 'pro', 'virtuoso', 'maestro', name='usertier', create_type=False)
    usertier_enum.create(op.get_bind(), checkfirst=True)
    # Ensure virtuoso exists if usertier was previously created
    op.execute("ALTER TYPE usertier ADD VALUE IF NOT EXISTS 'virtuoso';")


    op.add_column(
        'users',
        sa.Column(
            'tier',
            postgresql.ENUM('starter', 'pro', 'virtuoso', 'maestro', name='usertier', create_type=False),
            nullable=False,
            server_default='starter',
        ),
    )

    op.add_column(
        'jobs',
        sa.Column(
            'file_size_bytes',
            sa.BigInteger(),
            nullable=False,
            server_default='0',
        ),
    )


def downgrade() -> None:
    """Downgrade schema: drop jobs.file_size_bytes, users.tier, and usertier enum."""
    op.drop_column('jobs', 'file_size_bytes')
    op.drop_column('users', 'tier')
    sa.Enum(name='usertier').drop(op.get_bind(), checkfirst=True)
