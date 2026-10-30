"""add_p8_collaboration_and_social_sharing

Revision ID: 7f6e5d4c3b2a
Revises: 6e5f4a3b2c1d
Create Date: 2026-10-13 16:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7f6e5d4c3b2a'
down_revision: Union[str, Sequence[str], None] = '6e5f4a3b2c1d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: add score_shares and score_annotations tables."""
    op.create_table(
        'score_shares',
        sa.Column('id', sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('job_id', sa.Uuid(as_uuid=True), sa.ForeignKey('jobs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.Uuid(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('share_token', sa.String(length=64), nullable=False),
        sa.Column('allow_playback', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('allow_fork', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('view_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_score_shares_job_id', 'score_shares', ['job_id'], unique=False)
    op.create_index('ix_score_shares_share_token', 'score_shares', ['share_token'], unique=True)

    op.create_table(
        'score_annotations',
        sa.Column('id', sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('job_id', sa.Uuid(as_uuid=True), sa.ForeignKey('jobs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.Uuid(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('author_name', sa.String(length=100), nullable=False, server_default='Musician'),
        sa.Column('measure_number', sa.Integer(), nullable=False),
        sa.Column('staff_index', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('annotation_type', sa.String(length=50), nullable=False, server_default='comment'),
        sa.Column('content', sa.String(length=1000), nullable=False),
        sa.Column('color', sa.String(length=20), nullable=False, server_default='#6366f1'),
        sa.Column('is_resolved', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_score_annotations_job_id_measure', 'score_annotations', ['job_id', 'measure_number'], unique=False)
    op.create_index('ix_score_annotations_created_at', 'score_annotations', ['created_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema: drop score_annotations and score_shares tables."""
    op.drop_index('ix_score_annotations_created_at', table_name='score_annotations')
    op.drop_index('ix_score_annotations_job_id_measure', table_name='score_annotations')
    op.drop_table('score_annotations')

    op.drop_index('ix_score_shares_share_token', table_name='score_shares')
    op.drop_index('ix_score_shares_job_id', table_name='score_shares')
    op.drop_table('score_shares')
