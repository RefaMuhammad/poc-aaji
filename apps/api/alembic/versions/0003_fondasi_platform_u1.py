"""fondasi platform U1: pengaturan tenant, peran baru, akun layanan (API key), penugasan dokter + SLA

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-05 07:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('facility_name', sa.String(length=200), nullable=True))
    op.add_column('users', sa.Column('member_ref', sa.String(length=64), nullable=True))

    op.create_table(
        'user_tenants',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('insurer_id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['insurer_id'], ['insurers.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'insurer_id', name='uq_user_tenant'),
    )
    op.create_index(op.f('ix_user_tenants_user_id'), 'user_tenants', ['user_id'], unique=False)
    op.create_index(op.f('ix_user_tenants_insurer_id'), 'user_tenants', ['insurer_id'], unique=False)

    op.create_table(
        'tenant_settings',
        sa.Column('insurer_id', sa.String(length=36), nullable=False),
        sa.Column('display_name', sa.String(length=200), nullable=True),
        sa.Column('logo_data_url', sa.Text(), nullable=True),
        sa.Column('primary_color', sa.String(length=7), nullable=True),
        sa.Column('triage_red_min_score', sa.Integer(), nullable=True),
        sa.Column('triage_yellow_min_score', sa.Integer(), nullable=True),
        sa.Column('disabled_rules', sa.JSON(), nullable=False),
        sa.Column('sla_gp_hours', sa.Integer(), nullable=False),
        sa.Column('sla_specialist_hours', sa.Integer(), nullable=False),
        sa.Column('auto_assign', sa.Boolean(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('updated_by_id', sa.String(length=36), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['insurer_id'], ['insurers.id']),
        sa.ForeignKeyConstraint(['updated_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('insurer_id'),
    )

    op.create_table(
        'api_clients',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('insurer_id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('key_prefix', sa.String(length=16), nullable=False),
        sa.Column('key_hash', sa.String(length=64), nullable=False),
        sa.Column('scopes', sa.JSON(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_by_id', sa.String(length=36), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['insurer_id'], ['insurers.id']),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_api_clients_insurer_id'), 'api_clients', ['insurer_id'], unique=False)
    op.create_index(op.f('ix_api_clients_key_prefix'), 'api_clients', ['key_prefix'], unique=True)

    op.create_table(
        'assignments',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('claim_id', sa.String(length=36), nullable=False),
        sa.Column('recommendation_id', sa.String(length=36), nullable=False),
        sa.Column('doctor_id', sa.String(length=36), nullable=False),
        sa.Column('level', sa.String(length=16), nullable=False),
        sa.Column('specialty', sa.String(length=100), nullable=True),
        sa.Column('method', sa.String(length=16), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('assigned_by_id', sa.String(length=36), nullable=True),
        sa.Column('assigned_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('due_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['claim_id'], ['claims.id']),
        sa.ForeignKeyConstraint(['recommendation_id'], ['recommendations.id']),
        sa.ForeignKeyConstraint(['doctor_id'], ['users.id']),
        sa.ForeignKeyConstraint(['assigned_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_assignments_claim_id'), 'assignments', ['claim_id'], unique=False)
    op.create_index(op.f('ix_assignments_doctor_id'), 'assignments', ['doctor_id'], unique=False)
    op.create_index(op.f('ix_assignments_status'), 'assignments', ['status'], unique=False)


def downgrade() -> None:
    op.drop_table('assignments')
    op.drop_table('api_clients')
    op.drop_table('tenant_settings')
    op.drop_table('user_tenants')
    op.drop_column('users', 'member_ref')
    op.drop_column('users', 'facility_name')
