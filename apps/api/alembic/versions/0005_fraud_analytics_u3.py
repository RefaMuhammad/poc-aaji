"""fraud analytics U3: data analitik klaim, run analisis, sinyal, dan telaah investigator

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-05 15:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'fraud_claim_records',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('insurer_id', sa.String(length=36), nullable=False),
        sa.Column('claim_id', sa.String(length=36), nullable=True),
        sa.Column('claim_number', sa.String(length=64), nullable=False),
        sa.Column('source', sa.String(length=16), nullable=False),
        sa.Column('member_id', sa.String(length=64), nullable=False),
        sa.Column('member_name', sa.String(length=200), nullable=True),
        sa.Column('address', sa.String(length=300), nullable=True),
        sa.Column('bank_account', sa.String(length=64), nullable=True),
        sa.Column('hospital_name', sa.String(length=200), nullable=False),
        sa.Column('doctor_name', sa.String(length=200), nullable=True),
        sa.Column('referral_from', sa.String(length=200), nullable=True),
        sa.Column('icd10', sa.String(length=16), nullable=True),
        sa.Column('admission_date', sa.Date(), nullable=False),
        sa.Column('discharge_date', sa.Date(), nullable=False),
        sa.Column('billed_amount', sa.BigInteger(), nullable=False),
        sa.Column('lab_panels', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['insurer_id'], ['insurers.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('insurer_id', 'claim_number', name='uq_fraud_record_claim'),
    )
    op.create_index(op.f('ix_fraud_claim_records_insurer_id'), 'fraud_claim_records', ['insurer_id'], unique=False)
    op.create_index(op.f('ix_fraud_claim_records_claim_id'), 'fraud_claim_records', ['claim_id'], unique=False)
    op.create_index(op.f('ix_fraud_claim_records_member_id'), 'fraud_claim_records', ['member_id'], unique=False)

    op.create_table(
        'fraud_runs',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('insurer_id', sa.String(length=36), nullable=False),
        sa.Column('ruleset_version', sa.String(length=50), nullable=False),
        sa.Column('record_count', sa.Integer(), nullable=False),
        sa.Column('signal_count', sa.Integer(), nullable=False),
        sa.Column('entities', sa.JSON(), nullable=False),
        sa.Column('created_by_id', sa.String(length=36), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['insurer_id'], ['insurers.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_fraud_runs_insurer_id'), 'fraud_runs', ['insurer_id'], unique=False)
    op.create_index(op.f('ix_fraud_runs_created_at'), 'fraud_runs', ['created_at'], unique=False)

    op.create_table(
        'fraud_signals',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('run_id', sa.String(length=36), nullable=False),
        sa.Column('insurer_id', sa.String(length=36), nullable=False),
        sa.Column('rule_id', sa.String(length=32), nullable=False),
        sa.Column('reason_code', sa.String(length=50), nullable=False),
        sa.Column('severity', sa.String(length=10), nullable=False),
        sa.Column('weight', sa.Integer(), nullable=False),
        sa.Column('entity_type', sa.String(length=20), nullable=False),
        sa.Column('entity_key', sa.String(length=300), nullable=False),
        sa.Column('entity_label', sa.String(length=300), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('claim_numbers', sa.JSON(), nullable=False),
        sa.Column('evidence', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['run_id'], ['fraud_runs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['insurer_id'], ['insurers.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_fraud_signals_run_id'), 'fraud_signals', ['run_id'], unique=False)
    op.create_index(op.f('ix_fraud_signals_insurer_id'), 'fraud_signals', ['insurer_id'], unique=False)

    op.create_table(
        'fraud_reviews',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('insurer_id', sa.String(length=36), nullable=False),
        sa.Column('rule_id', sa.String(length=32), nullable=False),
        sa.Column('entity_type', sa.String(length=20), nullable=False),
        sa.Column('entity_key', sa.String(length=300), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('reviewed_by_id', sa.String(length=36), nullable=False),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['insurer_id'], ['insurers.id']),
        sa.ForeignKeyConstraint(['reviewed_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('insurer_id', 'rule_id', 'entity_key', name='uq_fraud_review_signal'),
    )
    op.create_index(op.f('ix_fraud_reviews_insurer_id'), 'fraud_reviews', ['insurer_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_fraud_reviews_insurer_id'), table_name='fraud_reviews')
    op.drop_table('fraud_reviews')
    op.drop_index(op.f('ix_fraud_signals_insurer_id'), table_name='fraud_signals')
    op.drop_index(op.f('ix_fraud_signals_run_id'), table_name='fraud_signals')
    op.drop_table('fraud_signals')
    op.drop_index(op.f('ix_fraud_runs_created_at'), table_name='fraud_runs')
    op.drop_index(op.f('ix_fraud_runs_insurer_id'), table_name='fraud_runs')
    op.drop_table('fraud_runs')
    op.drop_index(op.f('ix_fraud_claim_records_member_id'), table_name='fraud_claim_records')
    op.drop_index(op.f('ix_fraud_claim_records_claim_id'), table_name='fraud_claim_records')
    op.drop_index(op.f('ix_fraud_claim_records_insurer_id'), table_name='fraud_claim_records')
    op.drop_table('fraud_claim_records')
