"""add_user_profile_and_terms_fields

Revision ID: 3b2c1d0e9f8a
Revises: 185f2e3570e1
Create Date: 2026-10-03 09:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '3b2c1d0e9f8a'
down_revision: Union[str, Sequence[str], None] = '185f2e3570e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: add profile, timestamps, and legal terms acceptance columns to users table."""
    op.add_column('users', sa.Column('full_name', sa.String(length=255), nullable=False, server_default=''))
    op.add_column('users', sa.Column('birthdate', sa.Date(), nullable=True))
    op.add_column('users', sa.Column('musical_role', sa.String(length=100), nullable=True))
    op.add_column('users', sa.Column('country', sa.String(length=100), nullable=True))
    op.add_column('users', sa.Column('bio', sa.String(length=500), nullable=True))
    op.add_column('users', sa.Column('terms_accepted', sa.Boolean(), nullable=False, server_default='true'))
    op.add_column('users', sa.Column('terms_accepted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('terms_version', sa.String(length=50), nullable=True, server_default='2026.1-copyright'))
    op.add_column('users', sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')))
    op.add_column('users', sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')))


def downgrade() -> None:
    """Downgrade schema: drop added profile and terms columns from users table."""
    op.drop_column('users', 'updated_at')
    op.drop_column('users', 'created_at')
    op.drop_column('users', 'terms_version')
    op.drop_column('users', 'terms_accepted_at')
    op.drop_column('users', 'terms_accepted')
    op.drop_column('users', 'bio')
    op.drop_column('users', 'country')
    op.drop_column('users', 'musical_role')
    op.drop_column('users', 'birthdate')
    op.drop_column('users', 'full_name')
