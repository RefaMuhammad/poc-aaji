"""manajemen sengketa U5: tabel disputes, kolom telaah ulang di recommendations

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-05 20:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'disputes',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('claim_id', sa.String(length=36), nullable=False),
        sa.Column('insurer_id', sa.String(length=36), nullable=False),
        sa.Column('decision_id', sa.String(length=36), nullable=False),
        sa.Column('disputed_recommendation_id', sa.String(length=36), nullable=False),
        sa.Column('original_reviewer_id', sa.String(length=36), nullable=True),
        sa.Column('raised_by_id', sa.String(length=36), nullable=False),
        sa.Column('raised_by_role', sa.String(length=32), nullable=False),
        sa.Column('category', sa.String(length=32), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('document_ids', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('due_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('review_recommendation_id', sa.String(length=36), nullable=True),
        sa.Column('reviewer_id', sa.String(length=36), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('review_outcome', sa.String(length=16), nullable=True),
        sa.Column('review_notes', sa.Text(), nullable=True),
        sa.Column('new_recommendation_id', sa.String(length=36), nullable=True),
        sa.Column('final_decision_id', sa.String(length=36), nullable=True),
        sa.Column('outcome', sa.String(length=16), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_by_id', sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(['claim_id'], ['claims.id']),
        sa.ForeignKeyConstraint(['insurer_id'], ['insurers.id']),
        sa.ForeignKeyConstraint(['raised_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['reviewer_id'], ['users.id']),
        sa.ForeignKeyConstraint(['resolved_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_disputes_claim_id', 'disputes', ['claim_id'])
    op.create_index('ix_disputes_insurer_id', 'disputes', ['insurer_id'])
    op.create_index('ix_disputes_status', 'disputes', ['status'])
    op.add_column('recommendations', sa.Column('dispute_id', sa.String(length=36), nullable=True))
    op.add_column('recommendations', sa.Column('excluded_reviewer_id', sa.String(length=36), nullable=True))
    op.create_index('ix_recommendations_dispute_id', 'recommendations', ['dispute_id'])


def downgrade() -> None:
    op.drop_index('ix_recommendations_dispute_id', table_name='recommendations')
    op.drop_column('recommendations', 'excluded_reviewer_id')
    op.drop_column('recommendations', 'dispute_id')
    op.drop_index('ix_disputes_status', table_name='disputes')
    op.drop_index('ix_disputes_insurer_id', table_name='disputes')
    op.drop_index('ix_disputes_claim_id', table_name='disputes')
    op.drop_table('disputes')
