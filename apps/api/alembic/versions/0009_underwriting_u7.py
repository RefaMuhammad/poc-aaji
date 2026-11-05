"""underwriting medis U7: pengajuan calon peserta, dokumen, penilaian sistem, telaah dokter, keputusan underwriter

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-05 15:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('uw_applications',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('application_number', sa.String(length=64), nullable=False),
    sa.Column('insurer_id', sa.String(length=36), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('spaj_number', sa.String(length=64), nullable=True),
    sa.Column('applicant_name', sa.String(length=200), nullable=True),
    sa.Column('applicant_sex', sa.String(length=1), nullable=True),
    sa.Column('applicant_birth_date', sa.Date(), nullable=True),
    sa.Column('product_name', sa.String(length=200), nullable=True),
    sa.Column('sum_assured', sa.BigInteger(), nullable=True),
    sa.Column('base_premium', sa.BigInteger(), nullable=True),
    sa.Column('processing_error', sa.Text(), nullable=True),
    sa.Column('submitted_by_id', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['insurer_id'], ['insurers.id'], ),
    sa.ForeignKeyConstraint(['submitted_by_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('application_number')
    )
    op.create_index(op.f('ix_uw_applications_insurer_id'), 'uw_applications', ['insurer_id'], unique=False)
    op.create_index(op.f('ix_uw_applications_status'), 'uw_applications', ['status'], unique=False)
    op.create_table('uw_assessments',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('application_id', sa.String(length=36), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('fields', sa.JSON(), nullable=False),
    sa.Column('profile', sa.JSON(), nullable=False),
    sa.Column('findings', sa.JSON(), nullable=False),
    sa.Column('skipped', sa.JSON(), nullable=False),
    sa.Column('evidence', sa.JSON(), nullable=False),
    sa.Column('missing_docs', sa.JSON(), nullable=False),
    sa.Column('missing_fields', sa.JSON(), nullable=False),
    sa.Column('debit_total', sa.Integer(), nullable=False),
    sa.Column('risk_class', sa.String(length=16), nullable=False),
    sa.Column('loading_pct', sa.Integer(), nullable=False),
    sa.Column('exclusions', sa.JSON(), nullable=False),
    sa.Column('recommendation', sa.String(length=24), nullable=False),
    sa.Column('needs_doctor', sa.Boolean(), nullable=False),
    sa.Column('doctor_reasons', sa.JSON(), nullable=False),
    sa.Column('rules_version', sa.String(length=64), nullable=False),
    sa.Column('model_version', sa.String(length=100), nullable=False),
    sa.Column('prompt_version', sa.String(length=64), nullable=False),
    sa.Column('ocr_engine', sa.String(length=64), nullable=False),
    sa.Column('warnings', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['application_id'], ['uw_applications.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_uw_assessments_application_id'), 'uw_assessments', ['application_id'], unique=False)
    op.create_table('uw_documents',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('application_id', sa.String(length=36), nullable=False),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('content_type', sa.String(length=100), nullable=False),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('storage_key', sa.String(length=500), nullable=False),
    sa.Column('doc_type', sa.String(length=50), nullable=False),
    sa.Column('page_count', sa.Integer(), nullable=True),
    sa.Column('uploaded_by_id', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['application_id'], ['uw_applications.id'], ),
    sa.ForeignKeyConstraint(['uploaded_by_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_uw_documents_application_id'), 'uw_documents', ['application_id'], unique=False)
    op.create_index(op.f('ix_uw_documents_sha256'), 'uw_documents', ['sha256'], unique=False)
    op.create_table('uw_reviews',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('application_id', sa.String(length=36), nullable=False),
    sa.Column('assessment_id', sa.String(length=36), nullable=False),
    sa.Column('doctor_id', sa.String(length=36), nullable=False),
    sa.Column('action', sa.String(length=16), nullable=False),
    sa.Column('recommendation', sa.String(length=24), nullable=False),
    sa.Column('risk_class', sa.String(length=16), nullable=False),
    sa.Column('loading_pct', sa.Integer(), nullable=False),
    sa.Column('exclusions', sa.JSON(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('signed_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['application_id'], ['uw_applications.id'], ),
    sa.ForeignKeyConstraint(['assessment_id'], ['uw_assessments.id'], ),
    sa.ForeignKeyConstraint(['doctor_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_uw_reviews_application_id'), 'uw_reviews', ['application_id'], unique=False)
    op.create_table('uw_decisions',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('application_id', sa.String(length=36), nullable=False),
    sa.Column('review_id', sa.String(length=36), nullable=True),
    sa.Column('decision', sa.String(length=24), nullable=False),
    sa.Column('risk_class', sa.String(length=16), nullable=False),
    sa.Column('loading_pct', sa.Integer(), nullable=False),
    sa.Column('exclusions', sa.JSON(), nullable=False),
    sa.Column('final_premium', sa.BigInteger(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('decided_by_id', sa.String(length=36), nullable=False),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['application_id'], ['uw_applications.id'], ),
    sa.ForeignKeyConstraint(['decided_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['review_id'], ['uw_reviews.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_uw_decisions_application_id'), 'uw_decisions', ['application_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_uw_decisions_application_id'), table_name='uw_decisions')
    op.drop_table('uw_decisions')
    op.drop_index(op.f('ix_uw_reviews_application_id'), table_name='uw_reviews')
    op.drop_table('uw_reviews')
    op.drop_index(op.f('ix_uw_documents_sha256'), table_name='uw_documents')
    op.drop_index(op.f('ix_uw_documents_application_id'), table_name='uw_documents')
    op.drop_table('uw_documents')
    op.drop_index(op.f('ix_uw_assessments_application_id'), table_name='uw_assessments')
    op.drop_table('uw_assessments')
    op.drop_index(op.f('ix_uw_applications_status'), table_name='uw_applications')
    op.drop_index(op.f('ix_uw_applications_insurer_id'), table_name='uw_applications')
    op.drop_table('uw_applications')
