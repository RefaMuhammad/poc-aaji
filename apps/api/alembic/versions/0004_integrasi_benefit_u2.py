"""integrasi & benefit U2: polis/plan benefit, sumber klaim, riwayat integrasi, webhook

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-05 12:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('tenant_settings', sa.Column('webhook_url', sa.String(length=500), nullable=True))
    op.add_column('tenant_settings', sa.Column('webhook_secret', sa.String(length=100), nullable=True))

    op.create_table(
        'benefit_plans',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('insurer_id', sa.String(length=36), nullable=False),
        sa.Column('code', sa.String(length=32), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('room_class', sa.String(length=50), nullable=True),
        sa.Column('room_rate_limit', sa.BigInteger(), nullable=True),
        sa.Column('annual_limit', sa.BigInteger(), nullable=True),
        sa.Column('waiting_period_days', sa.Integer(), nullable=False),
        sa.Column('excluded_icd10', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['insurer_id'], ['insurers.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('insurer_id', 'code', name='uq_benefit_plan_code'),
    )
    op.create_index(op.f('ix_benefit_plans_insurer_id'), 'benefit_plans', ['insurer_id'], unique=False)

    op.create_table(
        'policies',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('insurer_id', sa.String(length=36), nullable=False),
        sa.Column('policy_number', sa.String(length=64), nullable=False),
        sa.Column('member_id', sa.String(length=64), nullable=False),
        sa.Column('member_name', sa.String(length=200), nullable=True),
        sa.Column('plan_id', sa.String(length=36), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('limit_used', sa.BigInteger(), nullable=False),
        sa.Column('source', sa.String(length=16), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['insurer_id'], ['insurers.id']),
        sa.ForeignKeyConstraint(['plan_id'], ['benefit_plans.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('insurer_id', 'policy_number', 'member_id', name='uq_policy_member'),
    )
    op.create_index(op.f('ix_policies_insurer_id'), 'policies', ['insurer_id'], unique=False)
    op.create_index(op.f('ix_policies_policy_number'), 'policies', ['policy_number'], unique=False)
    op.create_index(op.f('ix_policies_member_id'), 'policies', ['member_id'], unique=False)

    op.create_table(
        'integration_jobs',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('insurer_id', sa.String(length=36), nullable=False),
        sa.Column('channel', sa.String(length=16), nullable=False),
        sa.Column('reference', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('summary', sa.JSON(), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=True),
        sa.Column('api_client_id', sa.String(length=36), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['insurer_id'], ['insurers.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_integration_jobs_insurer_id'), 'integration_jobs', ['insurer_id'], unique=False)
    op.create_index(op.f('ix_integration_jobs_created_at'), 'integration_jobs', ['created_at'], unique=False)

    op.create_table(
        'webhook_deliveries',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('insurer_id', sa.String(length=36), nullable=False),
        sa.Column('event', sa.String(length=64), nullable=False),
        sa.Column('claim_id', sa.String(length=36), nullable=True),
        sa.Column('url', sa.String(length=500), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('last_status_code', sa.Integer(), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['insurer_id'], ['insurers.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_webhook_deliveries_insurer_id'), 'webhook_deliveries', ['insurer_id'], unique=False)
    op.create_index(op.f('ix_webhook_deliveries_claim_id'), 'webhook_deliveries', ['claim_id'], unique=False)
    op.create_index(op.f('ix_webhook_deliveries_status'), 'webhook_deliveries', ['status'], unique=False)
    op.create_index(op.f('ix_webhook_deliveries_created_at'), 'webhook_deliveries', ['created_at'], unique=False)

    # klaim lama berasal dari portal
    op.add_column('claims', sa.Column('source', sa.String(length=16), nullable=False, server_default='PORTAL'))
    op.alter_column('claims', 'source', server_default=None)
    op.add_column('claims', sa.Column('api_client_id', sa.String(length=36), nullable=True))
    op.add_column('claims', sa.Column('policy_id', sa.String(length=36), nullable=True))
    op.create_foreign_key('fk_claims_policy_id', 'claims', 'policies', ['policy_id'], ['id'])
    op.alter_column('claims', 'created_by_id', existing_type=sa.String(length=36), nullable=True)
    op.alter_column('documents', 'uploaded_by_id', existing_type=sa.String(length=36), nullable=True)

    op.add_column('recommendations', sa.Column('benefit_ruleset_version', sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column('recommendations', 'benefit_ruleset_version')
    op.alter_column('documents', 'uploaded_by_id', existing_type=sa.String(length=36), nullable=False)
    op.alter_column('claims', 'created_by_id', existing_type=sa.String(length=36), nullable=False)
    op.drop_constraint('fk_claims_policy_id', 'claims', type_='foreignkey')
    op.drop_column('claims', 'policy_id')
    op.drop_column('claims', 'api_client_id')
    op.drop_column('claims', 'source')
    op.drop_table('webhook_deliveries')
    op.drop_table('integration_jobs')
    op.drop_table('policies')
    op.drop_table('benefit_plans')
    op.drop_column('tenant_settings', 'webhook_secret')
    op.drop_column('tenant_settings', 'webhook_url')
