"""audit dan pelaporan U6: tabel reports, indeks log audit untuk penampil audit

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-05 22:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'reports',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('kind', sa.String(length=32), nullable=False),
        sa.Column('period', sa.String(length=7), nullable=False),
        sa.Column('insurer_id', sa.String(length=36), nullable=True),
        sa.Column('scope_key', sa.String(length=36), nullable=False),
        sa.Column('template_version', sa.String(length=32), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('trigger', sa.String(length=16), nullable=False),
        sa.Column('partial', sa.Boolean(), nullable=False),
        sa.Column('data', sa.JSON(), nullable=False),
        sa.Column('generated_by_id', sa.String(length=36), nullable=True),
        sa.Column('generated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['insurer_id'], ['insurers.id']),
        sa.ForeignKeyConstraint(['generated_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('kind', 'period', 'scope_key', name='uq_report_period'),
    )
    op.create_index('ix_reports_period', 'reports', ['period'])
    op.create_index('ix_reports_insurer_id', 'reports', ['insurer_id'])
    op.create_index('ix_audit_logs_action', 'audit_logs', ['action'])


def downgrade() -> None:
    op.drop_index('ix_audit_logs_action', table_name='audit_logs')
    op.drop_index('ix_reports_insurer_id', table_name='reports')
    op.drop_index('ix_reports_period', table_name='reports')
    op.drop_table('reports')
