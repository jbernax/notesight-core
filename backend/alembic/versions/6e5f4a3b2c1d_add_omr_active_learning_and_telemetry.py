"""add_omr_active_learning_and_telemetry

Revision ID: 6e5f4a3b2c1d
Revises: 5d4e3f2a1b0c
Create Date: 2026-10-13 15:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6e5f4a3b2c1d'
down_revision: Union[str, Sequence[str], None] = '5d4e3f2a1b0c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: add active learning telemetry and training triplet models."""
    op.add_column('users', sa.Column('allow_omr_telemetry', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('jobs', sa.Column('raw_prediction_path', sa.String(length=512), nullable=True))

    op.create_table(
        'omr_training_triplets',
        sa.Column('id', sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('job_id', sa.Uuid(as_uuid=True), sa.ForeignKey('jobs.id', ondelete='SET NULL'), nullable=True),
        sa.Column('user_id', sa.Uuid(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('image_path', sa.String(length=512), nullable=True),
        sa.Column('raw_prediction_path', sa.String(length=512), nullable=False),
        sa.Column('corrected_xml_path', sa.String(length=512), nullable=False),
        sa.Column('character_error_rate', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('measures_modified', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('rhythm_issues_fixed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('diff_summary', sa.String(length=1024), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_omr_training_triplets_job_id', 'omr_training_triplets', ['job_id'], unique=False)
    op.create_index('ix_omr_training_triplets_created_at', 'omr_training_triplets', ['created_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema: drop training triplets table and added active learning columns."""
    op.drop_index('ix_omr_training_triplets_created_at', table_name='omr_training_triplets')
    op.drop_index('ix_omr_training_triplets_job_id', table_name='omr_training_triplets')
    op.drop_table('omr_training_triplets')
    op.drop_column('jobs', 'raw_prediction_path')
    op.drop_column('users', 'allow_omr_telemetry')
