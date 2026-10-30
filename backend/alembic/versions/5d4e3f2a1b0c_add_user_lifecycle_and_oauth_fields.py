"""add_user_lifecycle_and_oauth_fields

Revision ID: 5d4e3f2a1b0c
Revises: 4c3d2e1f0a9b
Create Date: 2026-10-04 11:35:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5d4e3f2a1b0c'
down_revision: Union[str, Sequence[str], None] = '4c3d2e1f0a9b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: add email verification, social OAuth, avatar and notification fields to users table."""
    op.add_column('users', sa.Column('is_verified', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('users', sa.Column('oauth_provider', sa.String(length=50), nullable=True))
    op.add_column('users', sa.Column('oauth_id', sa.String(length=255), nullable=True))
    op.add_column('users', sa.Column('avatar_url', sa.String(length=512), nullable=True))
    op.add_column('users', sa.Column('email_notifications_enabled', sa.Boolean(), nullable=False, server_default='true'))
    op.alter_column('users', 'hashed_password', existing_type=sa.String(length=255), nullable=True)
    op.create_index('ix_users_oauth_id', 'users', ['oauth_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema: drop added lifecycle and OAuth columns from users table."""
    op.drop_index('ix_users_oauth_id', table_name='users')
    op.alter_column('users', 'hashed_password', existing_type=sa.String(length=255), nullable=False)
    op.drop_column('users', 'email_notifications_enabled')
    op.drop_column('users', 'avatar_url')
    op.drop_column('users', 'oauth_id')
    op.drop_column('users', 'oauth_provider')
    op.drop_column('users', 'is_verified')
