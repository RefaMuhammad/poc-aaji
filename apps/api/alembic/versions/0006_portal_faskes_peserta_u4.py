"""portal faskes, peserta, TPA U4: permintaan dokumen susulan dan notifikasi

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-05 18:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'document_requests',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('claim_id', sa.String(length=36), nullable=False),
        sa.Column('insurer_id', sa.String(length=36), nullable=False),
        sa.Column('recommendation_id', sa.String(length=36), nullable=True),
        sa.Column('doc_types', sa.JSON(), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('requested_by_id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('due_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('fulfilled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('fulfilled_by_id', sa.String(length=36), nullable=True),
        sa.Column('document_ids', sa.JSON(), nullable=False),
        sa.Column('response_note', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['claim_id'], ['claims.id']),
        sa.ForeignKeyConstraint(['insurer_id'], ['insurers.id']),
        sa.ForeignKeyConstraint(['requested_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['fulfilled_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_document_requests_claim_id'), 'document_requests', ['claim_id'], unique=False)
    op.create_index(op.f('ix_document_requests_insurer_id'), 'document_requests', ['insurer_id'], unique=False)
    op.create_index(op.f('ix_document_requests_status'), 'document_requests', ['status'], unique=False)

    op.create_table(
        'notifications',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('insurer_id', sa.String(length=36), nullable=True),
        sa.Column('claim_id', sa.String(length=36), nullable=True),
        sa.Column('event', sa.String(length=64), nullable=False),
        sa.Column('email', sa.String(length=200), nullable=False),
        sa.Column('subject', sa.String(length=300), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('delivery', sa.String(length=16), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_notifications_user_id'), 'notifications', ['user_id'], unique=False)
    op.create_index(op.f('ix_notifications_claim_id'), 'notifications', ['claim_id'], unique=False)
    op.create_index(op.f('ix_notifications_created_at'), 'notifications', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_notifications_created_at'), table_name='notifications')
    op.drop_index(op.f('ix_notifications_claim_id'), table_name='notifications')
    op.drop_index(op.f('ix_notifications_user_id'), table_name='notifications')
    op.drop_table('notifications')
    op.drop_index(op.f('ix_document_requests_status'), table_name='document_requests')
    op.drop_index(op.f('ix_document_requests_insurer_id'), table_name='document_requests')
    op.drop_index(op.f('ix_document_requests_claim_id'), table_name='document_requests')
    op.drop_table('document_requests')
