"""widen_totp_secret_for_encryption

Revision ID: 9b8c7d6e5f4a
Revises: 8a7b6c5d4e3f
Create Date: 2026-10-17 22:15:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9b8c7d6e5f4a'
down_revision: Union[str, Sequence[str], None] = '8a7b6c5d4e3f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: widen totp_secret column to Text to support encrypted secrets."""
    op.alter_column('users', 'totp_secret', type_=sa.Text(), existing_type=sa.String(length=64))


def downgrade() -> None:
    """Downgrade schema: shrink totp_secret column back to String(64)."""
    op.alter_column('users', 'totp_secret', type_=sa.String(length=64), existing_type=sa.Text())
