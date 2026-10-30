"""add_p14_totp_two_factor_auth

Revision ID: 8a7b6c5d4e3f
Revises: 7f6e5d4c3b2a
Create Date: 2026-10-17 18:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8a7b6c5d4e3f'
down_revision: Union[str, Sequence[str], None] = '7f6e5d4c3b2a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: add totp columns to users table."""
    op.add_column('users', sa.Column('totp_secret', sa.String(length=64), nullable=True))
    op.add_column('users', sa.Column('totp_enabled', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('users', sa.Column('totp_backup_codes', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema: drop totp columns from users table."""
    op.drop_column('users', 'totp_backup_codes')
    op.drop_column('users', 'totp_enabled')
    op.drop_column('users', 'totp_secret')
