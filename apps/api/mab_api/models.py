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
    FACILITY_OFFICER = "facility_officer"  # petugas faskes/RS (portal faskes, U4)
    MEMBER = "member"                      # peserta asuransi (portal peserta, U4)
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
    PENDING_DOCUMENTS = "PENDING_DOCUMENTS"  # U4: ditunda, menunggu dokumen susulan dari faskes
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
    # U2: webhook keluar (rekomendasi dirilis, keputusan dicatat, proses gagal)
    webhook_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    webhook_secret: Mapped[str | None] = mapped_column(String(100), nullable=True)
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


class ClaimSource(str, Enum):
    PORTAL = "PORTAL"   # formulir satu klaim di portal
    BATCH = "BATCH"     # ZIP + manifest di portal
    API = "API"         # REST API integrasi
    SFTP = "SFTP"       # ZIP + manifest di folder SFTP
    FHIR = "FHIR"       # Bundle FHIR R4


class BenefitPlan(Base):
    """Produk/plan rawat inap: hak kelas kamar, limit, masa tunggu, pengecualian diagnosis."""

    __tablename__ = "benefit_plans"
    __table_args__ = (UniqueConstraint("insurer_id", "code", name="uq_benefit_plan_code"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    insurer_id: Mapped[str] = mapped_column(ForeignKey("insurers.id"), index=True)
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(200))
    room_class: Mapped[str | None] = mapped_column(String(50), nullable=True)      # mis. "Kelas 1"
    room_rate_limit: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # rupiah per hari
    annual_limit: Mapped[int | None] = mapped_column(BigInteger, nullable=True)     # rupiah per tahun polis
    waiting_period_days: Mapped[int] = mapped_column(Integer, default=0)
    excluded_icd10: Mapped[list] = mapped_column(JSON, default=list)               # awalan kode, mis. ["O", "Z30"]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Policy(Base):
    """Polis satu peserta (dari sistem inti asuransi: impor file atau API)."""

    __tablename__ = "policies"
    __table_args__ = (UniqueConstraint("insurer_id", "policy_number", "member_id", name="uq_policy_member"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    insurer_id: Mapped[str] = mapped_column(ForeignKey("insurers.id"), index=True)
    policy_number: Mapped[str] = mapped_column(String(64), index=True)
    member_id: Mapped[str] = mapped_column(String(64), index=True)
    member_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("benefit_plans.id"))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")  # ACTIVE / LAPSED / TERMINATED
    limit_used: Mapped[int] = mapped_column(BigInteger, default=0)     # limit tahunan yang sudah terpakai
    source: Mapped[str] = mapped_column(String(16), default="IMPORT")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    plan: Mapped[BenefitPlan] = relationship()


class IntegrationJob(Base):
    """Riwayat data masuk lewat integrasi (API, SFTP, FHIR, impor polis)."""

    __tablename__ = "integration_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    insurer_id: Mapped[str] = mapped_column(ForeignKey("insurers.id"), index=True)
    channel: Mapped[str] = mapped_column(String(16))          # API / SFTP / FHIR / POLICY_IMPORT / BATCH
    reference: Mapped[str | None] = mapped_column(String(255), nullable=True)  # nama file / id bundle / nomor klaim
    status: Mapped[str] = mapped_column(String(16))           # SUCCESS / PARTIAL / FAILED
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    api_client_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class WebhookDelivery(Base):
    """Satu pengiriman webhook ke sistem asuransi, beserta hasil percobaan terakhir."""

    __tablename__ = "webhook_deliveries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    insurer_id: Mapped[str] = mapped_column(ForeignKey("insurers.id"), index=True)
    event: Mapped[str] = mapped_column(String(64))
    claim_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    url: Mapped[str] = mapped_column(String(500))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="PENDING", index=True)  # PENDING / DELIVERED / FAILED
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FraudClaimRecord(Base):
    """Data analitik fraud (U3): satu baris per klaim, dari riwayat impor atau klaim platform.

    Kolom rekening dan alamat berasal dari sistem inti asuransi (riwayat impor); klaim
    platform belum membawanya. Data ini hanya untuk analisis pola, tidak mengubah klaim.
    """

    __tablename__ = "fraud_claim_records"
    __table_args__ = (UniqueConstraint("insurer_id", "claim_number", name="uq_fraud_record_claim"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    insurer_id: Mapped[str] = mapped_column(ForeignKey("insurers.id"), index=True)
    claim_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)  # klaim platform, bila ada
    claim_number: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(16), default="HISTORY")  # HISTORY / PLATFORM
    member_id: Mapped[str] = mapped_column(String(64), index=True)
    member_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    address: Mapped[str | None] = mapped_column(String(300), nullable=True)
    bank_account: Mapped[str | None] = mapped_column(String(64), nullable=True)
    hospital_name: Mapped[str] = mapped_column(String(200))
    doctor_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    referral_from: Mapped[str | None] = mapped_column(String(200), nullable=True)
    icd10: Mapped[str | None] = mapped_column(String(16), nullable=True)
    admission_date: Mapped[date] = mapped_column(Date)
    discharge_date: Mapped[date] = mapped_column(Date)
    billed_amount: Mapped[int] = mapped_column(BigInteger)
    lab_panels: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class FraudRun(Base):
    """Satu kali analisis fraud untuk satu tenant. Sinyal selalu dibaca dari run terakhir."""

    __tablename__ = "fraud_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    insurer_id: Mapped[str] = mapped_column(ForeignKey("insurers.id"), index=True)
    ruleset_version: Mapped[str] = mapped_column(String(50))
    record_count: Mapped[int] = mapped_column(Integer)
    signal_count: Mapped[int] = mapped_column(Integer)
    entities: Mapped[list] = mapped_column(JSON, default=list)   # skor fraud per entitas
    created_by_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class FraudSignal(Base):
    __tablename__ = "fraud_signals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("fraud_runs.id", ondelete="CASCADE"), index=True)
    insurer_id: Mapped[str] = mapped_column(ForeignKey("insurers.id"), index=True)
    rule_id: Mapped[str] = mapped_column(String(32))
    reason_code: Mapped[str] = mapped_column(String(50))
    severity: Mapped[str] = mapped_column(String(10))
    weight: Mapped[int] = mapped_column(Integer)
    entity_type: Mapped[str] = mapped_column(String(20))
    entity_key: Mapped[str] = mapped_column(String(300))
    entity_label: Mapped[str] = mapped_column(String(300))
    message: Mapped[str] = mapped_column(Text)
    claim_numbers: Mapped[list] = mapped_column(JSON, default=list)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FraudReview(Base):
    """Hasil telaah investigator atas satu sinyal (aturan + entitas). Bertahan lintas run."""

    __tablename__ = "fraud_reviews"
    __table_args__ = (UniqueConstraint("insurer_id", "rule_id", "entity_key", name="uq_fraud_review_signal"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    insurer_id: Mapped[str] = mapped_column(ForeignKey("insurers.id"), index=True)
    rule_id: Mapped[str] = mapped_column(String(32))
    entity_type: Mapped[str] = mapped_column(String(20))
    entity_key: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(16))   # INVESTIGATING / CONFIRMED / DISMISSED
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


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
    # pembuat: pengguna portal, atau kosong bila dari integrasi (lihat source / api_client_id)
    created_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    source: Mapped[str] = mapped_column(String(16), default=ClaimSource.PORTAL.value)
    api_client_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    policy_id: Mapped[str | None] = mapped_column(ForeignKey("policies.id"), nullable=True)
    assigned_doctor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    policy: Mapped[Policy | None] = relationship()
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
    uploaded_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
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
    benefit_ruleset_version: Mapped[str | None] = mapped_column(String(50), nullable=True)  # U2
    # U5: rekomendasi telaah ulang sengketa (banding) dan dokter yang tidak boleh menelaahnya (penelaah awal)
    dispute_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    excluded_reviewer_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
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


class DocumentRequest(Base):
    """U4: permintaan dokumen susulan ke faskes ("tunda: minta dokumen").

    Selama permintaan OPEN, klaim berstatus PENDING_DOCUMENTS dan tidak bisa diputuskan.
    Permintaan tertutup (FULFILLED) saat faskes atau asuransi mengunggah dokumen; klaim lalu diproses ulang.
    """

    __tablename__ = "document_requests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    insurer_id: Mapped[str] = mapped_column(ForeignKey("insurers.id"), index=True)
    recommendation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    doc_types: Mapped[list] = mapped_column(JSON, default=list)
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="OPEN", index=True)  # OPEN / FULFILLED / CANCELLED
    requested_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fulfilled_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    document_ids: Mapped[list] = mapped_column(JSON, default=list)
    response_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    requested_by: Mapped[User] = relationship(foreign_keys=[requested_by_id])
    fulfilled_by: Mapped[User | None] = relationship(foreign_keys=[fulfilled_by_id])


class Dispute(Base):
    """U5: sengketa (banding) atas keputusan klaim oleh faskes atau peserta.

    Alur: OPEN/IN_REVIEW (telaah ulang dokter yang BERBEDA dari penandatangan rekomendasi yang dibanding)
    -> AWAITING_DECISION (dokter sudah tanda tangan) -> RESOLVED (asuransi memutus ulang). WITHDRAWN bila
    pengaju menarik banding sebelum dokter menandatangani.
    Hasil: UPHELD (dikuatkan), MODIFIED (diubah), OVERTURNED (dibatalkan, klaim dibayar penuh).
    """

    __tablename__ = "disputes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    insurer_id: Mapped[str] = mapped_column(ForeignKey("insurers.id"), index=True)
    decision_id: Mapped[str] = mapped_column(String(36))                 # keputusan yang dibanding
    disputed_recommendation_id: Mapped[str] = mapped_column(String(36))  # rekomendasi yang dibanding
    original_reviewer_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    raised_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    raised_by_role: Mapped[str] = mapped_column(String(32))
    category: Mapped[str] = mapped_column(String(32))   # CLINICAL / COVERAGE / BILLING / OTHER
    reason: Mapped[str] = mapped_column(Text)
    document_ids: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="IN_REVIEW", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    review_recommendation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)  # draf telaah ulang
    reviewer_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_outcome: Mapped[str | None] = mapped_column(String(16), nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_recommendation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    final_decision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(16), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    raised_by: Mapped[User] = relationship(foreign_keys=[raised_by_id])
    reviewer: Mapped[User | None] = relationship(foreign_keys=[reviewer_id])
    resolved_by: Mapped[User | None] = relationship(foreign_keys=[resolved_by_id])


class Notification(Base):
    """U4: notifikasi ke pengguna. Email disimulasikan (disimpan, tidak dikirim) selama demo."""

    __tablename__ = "notifications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    insurer_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    claim_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    event: Mapped[str] = mapped_column(String(64))
    email: Mapped[str] = mapped_column(String(200))
    subject: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    delivery: Mapped[str] = mapped_column(String(16), default="SIMULATED")  # SIMULATED / SENT / FAILED
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    """Log audit. Di PostgreSQL, trigger menolak UPDATE dan DELETE (lihat migrasi)."""

    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    user_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    method: Mapped[str | None] = mapped_column(String(10), nullable=True)
    path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    claim_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    document_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class Report(Base):
    """U6: laporan berkala (bulanan) yang sudah dihasilkan. Isi dibekukan di `data` saat dibuat.

    `insurer_id` kosong = laporan seluruh platform (auditor platform / admin). Satu laporan per
    jenis + periode + tenant; membuat ulang menimpa isi dan menaikkan `revision`.
    """

    __tablename__ = "reports"
    __table_args__ = (UniqueConstraint("kind", "period", "scope_key", name="uq_report_period"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    kind: Mapped[str] = mapped_column(String(32))                 # POJK36_MONTHLY
    period: Mapped[str] = mapped_column(String(7), index=True)    # YYYY-MM
    insurer_id: Mapped[str | None] = mapped_column(ForeignKey("insurers.id"), nullable=True, index=True)
    scope_key: Mapped[str] = mapped_column(String(36))            # insurer_id atau "ALL"
    template_version: Mapped[str] = mapped_column(String(32))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    trigger: Mapped[str] = mapped_column(String(16))              # SCHEDULED / MANUAL
    partial: Mapped[bool] = mapped_column(Boolean, default=False)  # periode belum selesai saat dibuat
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    generated_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    insurer: Mapped[Insurer | None] = relationship()
    generated_by: Mapped[User | None] = relationship()
