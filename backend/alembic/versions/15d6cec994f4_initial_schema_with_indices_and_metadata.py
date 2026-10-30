"""initial_schema_with_indices_and_metadata

Revision ID: 15d6cec994f4
Revises: 
Create Date: 2026-10-02 13:46:50.336920

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '15d6cec994f4'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('users',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('hashed_password', sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)

    op.create_table('jobs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=True),
        sa.Column('status', sa.Enum('pending', 'processing', 'completed', 'failed', name='jobstatus'), nullable=False),
        sa.Column('original_filename', sa.String(length=255), nullable=False),
        sa.Column('file_path', sa.String(length=512), nullable=True),
        sa.Column('result_file_path', sa.String(length=512), nullable=True),
        sa.Column('error_message', sa.String(length=1024), nullable=True),
        sa.Column('content_hash', sa.String(length=64), nullable=True),
        sa.Column('page_count', sa.Integer(), nullable=True),
        sa.Column('processing_time_seconds', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_jobs_content_hash'), 'jobs', ['content_hash'], unique=False)
    op.create_index(op.f('ix_jobs_status'), 'jobs', ['status'], unique=False)
    op.create_index(op.f('ix_jobs_user_id'), 'jobs', ['user_id'], unique=False)
    op.create_index('ix_jobs_user_id_created_at', 'jobs', ['user_id', 'created_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_jobs_user_id_created_at', table_name='jobs')
    op.drop_index(op.f('ix_jobs_user_id'), table_name='jobs')
    op.drop_index(op.f('ix_jobs_status'), table_name='jobs')
    op.drop_index(op.f('ix_jobs_content_hash'), table_name='jobs')
    op.drop_table('jobs')
    sa.Enum(name='jobstatus').drop(op.get_bind(), checkfirst=True)
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')
