"""Model database POC (SQLAlchemy 2)."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any

from sqlalchemy import JSON, BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mab_api.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Role(str, Enum):
    INSURER_STAFF = "insurer_staff"
    INSURER_MANAGER = "insurer_manager"
    DOCTOR_GP = "doctor_gp"
    DOCTOR_SPECIALIST = "doctor_specialist"
    ADMIN = "admin"
    # U1: peran baru
    TPA_OPERATOR = "tpa_operator"          # operator TPA, bekerja untuk beberapa asuransi (tenant)
    AUDITOR = "auditor"                    # auditor internal/OJK, hanya-baca
    FACILITY_OFFICER = "facility_officer"  # petugas faskes/RS (portal faskes menyusul di U4)
    MEMBER = "member"                      # peserta asuransi (portal peserta menyusul di U4)
    UNDERWRITER = "underwriter"            # underwriter (modul underwriting menyusul di U7)


INSURER_ROLES = {Role.INSURER_STAFF, Role.INSURER_MANAGER}
DOCTOR_ROLES = {Role.DOCTOR_GP, Role.DOCTOR_SPECIALIST}
# Peran yang bertindak atas nama asuransi (unggah, keputusan). TPA bisa untuk beberapa tenant.
CLAIM_OPERATOR_ROLES = INSURER_ROLES | {Role.TPA_OPERATOR}


class ClaimStatus(str, Enum):
    RECEIVED = "RECEIVED"                    # diterima, belum ada dokumen diproses
    QUEUED = "QUEUED"                        # dokumen masuk, menunggu worker
    PROCESSING = "PROCESSING"                # diproses
    AWAITING_DOCTOR = "AWAITING_DOCTOR"      # menunggu dokter
    AWAITING_DECISION = "AWAITING_DECISION"  # menunggu keputusan asuransi
    COMPLETED = "COMPLETED"                  # selesai
    FAILED = "FAILED"


class RecommendationCode(str, Enum):
    PAY_FULL = "PAY_FULL"
    PAY_PARTIAL = "PAY_PARTIAL"
    PEND = "PEND"
    NOT_COVERED = "NOT_COVERED"
    DOCTOR_REVIEW = "DOCTOR_REVIEW"  # draf awal sebelum dokter memutuskan


class RecommendationState(str, Enum):
    DRAFT = "DRAFT"    # dibuat sistem, belum ditandatangani
    SIGNED = "SIGNED"  # ditandatangani dokter


class DecisionCode(str, Enum):
    AGREE = "AGREE"
    DIFFER = "DIFFER"


class Insurer(Base):
    __tablename__ = "insurers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32))
    insurer_id: Mapped[str | None] = mapped_column(ForeignKey("insurers.id"), nullable=True)
    specialty: Mapped[str | None] = mapped_column(String(100), nullable=True)
    pin_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)  # tanda tangan (M7)
    facility_name: Mapped[str | None] = mapped_column(String(200), nullable=True)  # petugas faskes: nama RS
    member_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)  # peserta: id peserta
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    insurer: Mapped[Insurer | None] = relationship()


class UserTenant(Base):
    """Tenant tambahan yang boleh dilayani pengguna (operator TPA)."""

    __tablename__ = "user_tenants"
    __table_args__ = (UniqueConstraint("user_id", "insurer_id", name="uq_user_tenant"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    insurer_id: Mapped[str] = mapped_column(ForeignKey("insurers.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TenantSettings(Base):
    """Pengaturan per tenant (asuransi): tampilan, ambang triase, aturan aktif, SLA.

    Nilai None berarti memakai nilai dari file aturan YAML. Setiap simpan menaikkan `version`,
    dan versi ini ikut tercatat di versi aturan rekomendasi bila ada penyesuaian.
    """

    __tablename__ = "tenant_settings"
    insurer_id: Mapped[str] = mapped_column(ForeignKey("insurers.id"), primary_key=True)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    logo_data_url: Mapped[str | None] = mapped_column(Text, nullable=True)  # data:image/...;base64 (maks. ~200 KB)
    primary_color: Mapped[str | None] = mapped_column(String(7), nullable=True)  # #RRGGBB
    triage_red_min_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    triage_yellow_min_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    disabled_rules: Mapped[list] = mapped_column(JSON, default=list)
    sla_gp_hours: Mapped[int] = mapped_column(Integer, default=24)
    sla_specialist_hours: Mapped[int] = mapped_column(Integer, default=48)
    auto_assign: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ApiClient(Base):
    """Akun layanan untuk integrasi sistem asuransi/TPA. Kunci API hanya disimpan sebagai hash."""

    __tablename__ = "api_clients"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    insurer_id: Mapped[str] = mapped_column(ForeignKey("insurers.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    key_prefix: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    key_hash: Mapped[str] = mapped_column(String(64))
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"          # sedang dipegang dokter
    COMPLETED = "COMPLETED"    # rekomendasi ditandatangani
    RELEASED = "RELEASED"      # dilepas dokter, kembali ke antrean
    ESCALATED = "ESCALATED"    # diteruskan ke spesialis
    CANCELLED = "CANCELLED"    # klaim diproses ulang / dipindah admin


class Assignment(Base):
    """Penugasan kasus ke dokter beserta batas waktu SLA antreannya."""

    __tablename__ = "assignments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    recommendation_id: Mapped[str] = mapped_column(ForeignKey("recommendations.id"))
    doctor_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    level: Mapped[str] = mapped_column(String(16))          # GP / SPECIALIST
    specialty: Mapped[str | None] = mapped_column(String(100), nullable=True)
    method: Mapped[str] = mapped_column(String(16))         # AUTO / CLAIMED / MANUAL
    status: Mapped[str] = mapped_column(String(16), default=AssignmentStatus.ACTIVE.value, index=True)
    assigned_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Claim(Base):
    __tablename__ = "claims"
    __table_args__ = (UniqueConstraint("insurer_id", "claim_number", name="uq_claim_number_per_insurer"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    insurer_id: Mapped[str] = mapped_column(ForeignKey("insurers.id"), index=True)
    claim_number: Mapped[str] = mapped_column(String(64))
    policy_number: Mapped[str] = mapped_column(String(64))
    member_id: Mapped[str] = mapped_column(String(64), index=True)
    patient_name: Mapped[str | None] = mapped_column(String(200), nullable=True)  # sudah disamarkan
    hospital_name: Mapped[str] = mapped_column(String(200))
    admission_date: Mapped[date] = mapped_column(Date)
    discharge_date: Mapped[date] = mapped_column(Date)
    billed_amount: Mapped[int] = mapped_column(BigInteger)
    primary_icd10: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default=ClaimStatus.RECEIVED.value, index=True)
    processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    assigned_doctor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    documents: Mapped[list[Document]] = relationship(back_populates="claim", order_by="Document.created_at")
    recommendations: Mapped[list[Recommendation]] = relationship(back_populates="claim", order_by="Recommendation.version")
    decisions: Mapped[list[InsurerDecision]] = relationship(back_populates="claim", order_by="InsurerDecision.decided_at")


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    storage_key: Mapped[str] = mapped_column(String(500))
    doc_type: Mapped[str] = mapped_column(String(50), default="unknown")
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uploaded_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    claim: Mapped[Claim] = relationship(back_populates="documents")


class ExtractedField(Base):
    __tablename__ = "extracted_fields"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    field_path: Mapped[str] = mapped_column(String(100))
    value: Mapped[Any] = mapped_column(JSON, nullable=True)
    source: Mapped[str] = mapped_column(String(20))  # dokumen / ai / hitung
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence: Mapped[list] = mapped_column(JSON, default=list)  # [{doc, page, bbox, quote, line_ids, field}]
    status: Mapped[str | None] = mapped_column(String(20), nullable=True)  # field ai: verified/absent/unverified/unknown
    corrected_value: Mapped[Any] = mapped_column(JSON, nullable=True)
    corrected_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    corrected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Recommendation(Base):
    __tablename__ = "recommendations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    state: Mapped[str] = mapped_column(String(16), default=RecommendationState.DRAFT.value)
    triage_status: Mapped[str] = mapped_column(String(10))
    risk_score: Mapped[int] = mapped_column(Integer)
    recommendation: Mapped[str] = mapped_column(String(20))
    billed_amount: Mapped[int] = mapped_column(BigInteger)
    recommended_amount: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    line_adjustments: Mapped[list] = mapped_column(JSON, default=list)
    guideline_refs: Mapped[list] = mapped_column(JSON, default=list)
    next_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    explanation_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    quality_flags: Mapped[list | None] = mapped_column(JSON, nullable=True, default=list)  # [{code, message}]
    model_version: Mapped[str] = mapped_column(String(50))
    prompt_version: Mapped[str] = mapped_column(String(50))
    ruleset_version: Mapped[str] = mapped_column(String(50))
    signed_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    claim: Mapped[Claim] = relationship(back_populates="recommendations")
    findings: Mapped[list[Finding]] = relationship(back_populates="recommendation", order_by="Finding.created_at")
    signed_by: Mapped[User | None] = relationship()


class Finding(Base):
    __tablename__ = "findings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    recommendation_id: Mapped[str] = mapped_column(ForeignKey("recommendations.id"), index=True)
    rule_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reason_code: Mapped[str] = mapped_column(String(50))
    severity: Mapped[str] = mapped_column(String(10))
    source: Mapped[str] = mapped_column(String(10))  # RULE / AI / RED_FLAG
    text: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    guideline_refs: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    recommendation: Mapped[Recommendation] = relationship(back_populates="findings")


class Review(Base):
    __tablename__ = "reviews"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    recommendation_id: Mapped[str] = mapped_column(ForeignKey("recommendations.id"))
    doctor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str | None] = mapped_column(String(20), nullable=True)  # APPROVE / MODIFY / ESCALATE
    reason_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    agrees_with_ai: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    escalated_specialty: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class InsurerDecision(Base):
    __tablename__ = "insurer_decisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    recommendation_id: Mapped[str] = mapped_column(ForeignKey("recommendations.id"))
    decision: Mapped[str] = mapped_column(String(10))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    claim: Mapped[Claim] = relationship(back_populates="decisions")
    decided_by: Mapped[User] = relationship()


class AuditLog(Base):
    """Log audit. Di PostgreSQL, trigger menolak UPDATE dan DELETE (lihat migrasi)."""

    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    user_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    action: Mapped[str] = mapped_column(String(100))
    method: Mapped[str | None] = mapped_column(String(10), nullable=True)
    path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    claim_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    document_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
