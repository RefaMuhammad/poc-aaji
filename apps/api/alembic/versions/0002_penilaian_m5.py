"""penilaian klinis M5: status field AI dan catatan kualitas data rekomendasi

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-04 09:10:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('extracted_fields', sa.Column('status', sa.String(length=20), nullable=True))
    op.add_column('recommendations', sa.Column('quality_flags', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('recommendations', 'quality_flags')
    op.drop_column('extracted_fields', 'status')
