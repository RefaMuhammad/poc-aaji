"""Skema request/response API."""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LoginRequest(BaseModel):
    email: str
    password: str


class DemoAccountOut(BaseModel):
    email: str
    label: str
    full_name: str
    role: str


class DemoSwitchRequest(BaseModel):
    email: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: str
    full_name: str
    role: str
    insurer_id: str | None
    specialty: str | None
    facility_name: str | None = None
    member_ref: str | None = None


class ClaimCreate(BaseModel):
    claim_number: str = Field(min_length=1, max_length=64)
    policy_number: str = Field(min_length=1, max_length=64)
    member_id: str = Field(min_length=1, max_length=64)
    patient_name: str | None = Field(default=None, max_length=200)
    hospital_name: str = Field(min_length=1, max_length=200)
    admission_date: date
    discharge_date: date
    billed_amount: int = Field(ge=0)
    insurer_id: str | None = Field(default=None, description="Hanya untuk operator TPA: asuransi pemilik klaim")

    @model_validator(mode="after")
    def check_dates(self) -> "ClaimCreate":
        if self.discharge_date < self.admission_date:
            raise ValueError("Tanggal keluar tidak boleh sebelum tanggal masuk")
        return self


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    filename: str
    content_type: str
    size_bytes: int
    doc_type: str
    page_count: int | None = None
    created_at: datetime


class ClaimOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    insurer_id: str
    claim_number: str
    policy_number: str
    member_id: str
    patient_name: str | None
    hospital_name: str
    admission_date: date
    discharge_date: date
    billed_amount: int
    primary_icd10: str | None
    status: str
    processing_error: str | None
    created_at: datetime
    updated_at: datetime
    source: str = "PORTAL"          # U2: PORTAL / BATCH / API / SFTP / FHIR
    policy_id: str | None = None


class ClaimListItem(ClaimOut):
    """Baris daftar klaim. Triase/rekomendasi hanya terisi bila sudah boleh dilihat peran ini."""

    triage_status: str | None = None
    risk_score: int | None = None
    recommendation: str | None = None
    decision: str | None = None
    insurer_name: str | None = None


class ClaimDetail(ClaimOut):
    documents: list[DocumentOut]
    missing_documents: list[str]
    triage_status: str | None = None
    recommendation_available: bool = False   # sudah ada rekomendasi yang boleh dilihat peran ini
    awaiting_doctor: bool = False            # ada draf yang menunggu tanda tangan dokter
    decision: str | None = None
    policy: "PolicyOut | None" = None        # U2: polis yang dipakai aturan benefit


class ClaimStatusOut(BaseModel):
    id: str
    status: str
    processing_error: str | None
    updated_at: datetime


class UploadResult(BaseModel):
    documents: list[DocumentOut]
    job_id: str | None
    status: str


class BatchRowResult(BaseModel):
    row: int
    folder: str | None
    claim_number: str | None
    ok: bool
    claim_id: str | None = None
    documents: int = 0
    reason: str | None = None


class BatchResult(BaseModel):
    created: int
    failed: int
    rows: list[BatchRowResult]


class DecisionCreate(BaseModel):
    decision: str = Field(pattern="^(AGREE|DIFFER)$")
    reason: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def reason_required_for_differ(self) -> "DecisionCreate":
        if self.decision == "DIFFER" and not (self.reason or "").strip():
            raise ValueError("Alasan wajib diisi bila keputusan berbeda dengan rekomendasi")
        return self


class BulkAgreeRequest(BaseModel):
    claim_ids: list[str] = Field(min_length=1, max_length=500)


class BulkAgreeResult(BaseModel):
    agreed: list[str]
    skipped: list[dict]


# --- Format rekomendasi sesuai PRD ---------------------------------------------------


class EvidenceOut(BaseModel):
    doc: str | None = None          # id dokumen
    page: int | None = None
    quote: str | None = None
    bbox: list[float] | None = None  # x0, y0, x1, y1 dalam proporsi halaman
    field: str | None = None        # field kamus data yang dibuktikan
    claim_id: str | None = None     # untuk bukti klaim tumpang tindih
    policy_number: str | None = None  # U2: bukti dari data polis (bukan dokumen rumah sakit)


class ExtractedFieldOut(BaseModel):
    """Field kamus data hasil pipeline, dengan bukti lokasi di dokumen."""

    model_config = ConfigDict(from_attributes=True)
    field_path: str
    value: Any = None
    source: str
    confidence: float | None = None
    status: str | None = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    corrected_value: Any = None


class FindingOut(BaseModel):
    code: str
    severity: str
    source: str
    text: str
    rule_id: str | None = None
    evidence: list[EvidenceOut] = []
    guideline_refs: list[str] = []


class ReviewerOut(BaseModel):
    name: str
    specialty: str | None
    signed_at: datetime


class InsurerDecisionOut(BaseModel):
    decision: str
    reason: str | None
    decided_by: str
    decided_at: datetime


class RecommendationOut(BaseModel):
    claim_id: str
    claim_number: str
    triage_status: str
    risk_score: int
    recommendation: str
    state: str
    billed_amount: int
    recommended_amount: int | None
    line_adjustments: list[dict]
    findings: list[FindingOut]
    guideline_refs: list[str]
    next_action: str | None
    reviewer: ReviewerOut | None
    explanation_text: str | None
    quality_flags: list[dict] = []
    model_version: str
    prompt_version: str
    ruleset_version: str
    benefit_ruleset_version: str | None = None
    insurer_decision: InsurerDecisionOut | None
    label: str = "Data rekaan untuk demonstrasi"


TokenResponse.model_rebuild()


# --- Ruang kerja dokter (M7) ---------------------------------------------------------

FINAL_RECOMMENDATIONS = ("PAY_FULL", "PAY_PARTIAL", "PEND", "NOT_COVERED")


class QueueItem(BaseModel):
    id: str
    claim_number: str
    hospital_name: str
    admission_date: date
    discharge_date: date
    billed_amount: int
    primary_icd10: str | None
    diagnosis_name: str | None
    status: str
    triage_status: str | None
    risk_score: int | None
    findings: int
    level: str                       # GP / SPECIALIST
    specialty: str | None            # spesialisasi yang dibutuhkan (untuk level SPECIALIST)
    escalated: bool
    assigned_to: str | None          # nama dokter yang sedang menelaah
    assigned_to_me: bool
    waiting_since: datetime
    signed_by: str | None = None
    signed_at: datetime | None = None
    insurer_name: str | None = None
    sla_hours: int | None = None
    sla_due_at: datetime | None = None
    sla_state: str | None = None     # ON_TRACK / AT_RISK / OVERDUE (kasus yang masih di antrean)
    sla_met: bool | None = None      # untuk kasus selesai: ditandatangani sebelum batas SLA?


class ReviewFieldOut(BaseModel):
    id: str
    field_path: str
    label: str | None = None
    kind: str | None = None          # tipe di kamus data: angka / teks / ya_tidak / daftar
    value: Any = None
    source: str
    confidence: float | None = None
    status: str | None = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    corrected_value: Any = None
    corrected: bool = False
    corrected_by: str | None = None
    corrected_at: datetime | None = None


class FieldHistoryOut(BaseModel):
    field_path: str
    old: Any = None
    new: Any = None
    note: str | None = None
    by: str | None = None
    at: datetime


class ReviewOut(BaseModel):
    id: str
    doctor: str
    doctor_specialty: str | None
    action: str | None
    reason_code: str | None
    agrees_with_ai: bool | None
    escalated_specialty: str | None
    notes: str | None
    started_at: datetime
    finished_at: datetime | None
    duration_seconds: int | None


class Suggestion(BaseModel):
    recommendation: str
    recommended_amount: int | None


class Workspace(BaseModel):
    claim: ClaimDetail
    level: str
    specialty: str | None
    diagnosis_name: str | None
    escalated: bool
    assigned_to: str | None
    can_start: bool                   # dokter ini boleh mulai menelaah
    blocked_reason: str | None        # alasan bila tidak boleh
    my_review: ReviewOut | None       # telaah yang sedang dibuka dokter ini
    reviews: list[ReviewOut]          # riwayat telaah klaim ini
    draft: RecommendationOut | None   # draf AI (atau rekomendasi yang sudah ditandatangani)
    suggestion: Suggestion | None     # usulan rekomendasi final dari draf AI
    fields: list[ReviewFieldOut]
    field_history: list[FieldHistoryOut]
    reason_codes: dict[str, str]


class FieldCorrection(BaseModel):
    value: Any = None
    note: str | None = Field(default=None, max_length=1000)


class EscalateRequest(BaseModel):
    notes: str = Field(min_length=1, max_length=2000)
    specialty: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def notes_not_blank(self) -> "EscalateRequest":
        if not self.notes.strip():
            raise ValueError("Catatan eskalasi wajib diisi")
        return self


class SignRequest(BaseModel):
    recommendation: str = Field(pattern="^(PAY_FULL|PAY_PARTIAL|PEND|NOT_COVERED)$")
    recommended_amount: int | None = Field(default=None, ge=0)
    kept_adjustments: list[int] | None = None   # indeks koreksi item AI yang dipertahankan; None = semua
    reason_code: str | None = Field(default=None, max_length=50)
    notes: str | None = Field(default=None, max_length=4000)
    explanation_text: str | None = Field(default=None, max_length=8000)
    next_action: str | None = Field(default=None, max_length=1000)
    pin: str = Field(min_length=4, max_length=12)


class RulesetRule(BaseModel):
    id: str
    name: str
    reason_code: str
    severity: str
    needs_ai: bool
    reference: str | None


class RulesetDiagnosis(BaseModel):
    id: str
    name: str
    icd10: list[str]
    specialty: str | None
    rules: list[RulesetRule]


class RulesetOut(BaseModel):
    version: str
    status: str | None
    path: str
    general_rules: list[RulesetRule]
    diagnoses: list[RulesetDiagnosis]
    triage: list[dict[str, Any]]
    reason_codes: dict[str, str]
    benefit: "BenefitRulesetOut | None" = None


class BenefitRulesetOut(BaseModel):
    version: str
    path: str
    rules: list[RulesetRule]


# --- Dashboard (M8) -------------------------------------------------------------------


class CountItem(BaseModel):
    key: str
    label: str | None = None
    count: int
    amount: int | None = None


class DashboardOut(BaseModel):
    label: str = "Data rekaan untuk demonstrasi"
    total_claims: int
    by_status: list[CountItem]
    by_triage: list[CountItem]
    by_recommendation: list[CountItem]
    awaiting_doctor: int
    billed_total: int                     # tagihan semua klaim yang sudah punya rekomendasi terlihat
    recommended_total: int                # nilai rekomendasi (klaim dengan nilai)
    correction_total: int                 # tagihan - rekomendasi, untuk bayar sebagian / tidak dijamin
    top_findings: list[CountItem]
    top_hospitals: list[CountItem]        # RS dengan temuan terbanyak
    avg_processing_seconds: float | None  # unggah sampai rekomendasi awal
    decisions: list[CountItem]
    doctor_reviews: int
    doctor_agreement_pct: float | None    # persentase telaah yang setuju dengan draf AI
    avg_review_seconds: float | None


# --- Tenant, akun layanan, penugasan (U1) ---------------------------------------------

_LOGO_PREFIXES = ("data:image/png;base64,", "data:image/jpeg;base64,", "data:image/webp;base64,", "data:image/svg+xml;base64,")
MAX_LOGO_CHARS = 300_000  # kira-kira 220 KB gambar


class BrandingOut(BaseModel):
    """Tampilan tenant untuk header portal."""

    insurer_id: str
    code: str
    name: str
    display_name: str | None = None
    logo_data_url: str | None = None
    primary_color: str | None = None


class TenantOut(BrandingOut):
    triage_red_min_score: int | None = None
    triage_yellow_min_score: int | None = None
    disabled_rules: list[str] = []
    sla_gp_hours: int
    sla_specialist_hours: int
    auto_assign: bool
    version: int
    updated_at: datetime | None = None
    default_red_min_score: int | None = None     # dari file aturan YAML
    default_yellow_min_score: int | None = None
    effective_ruleset_version: str
    claim_count: int = 0
    webhook_url: str | None = None
    webhook_secret_set: bool = False
    policy_count: int = 0


class TenantCreate(BaseModel):
    code: str = Field(min_length=2, max_length=32, pattern=r"^[A-Z0-9_-]+$")
    name: str = Field(min_length=3, max_length=200)


class TenantSettingsIn(BaseModel):
    display_name: str | None = Field(default=None, max_length=200)
    logo_data_url: str | None = None
    primary_color: str | None = None
    triage_red_min_score: int | None = Field(default=None, ge=1, le=100)
    triage_yellow_min_score: int | None = Field(default=None, ge=1, le=100)
    disabled_rules: list[str] = []
    sla_gp_hours: int = Field(default=24, ge=1, le=720)
    sla_specialist_hours: int = Field(default=48, ge=1, le=720)
    auto_assign: bool = True
    webhook_url: str | None = Field(default=None, max_length=500)
    # None = rahasia lama dipertahankan; "" = hapus rahasia
    webhook_secret: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def check(self) -> "TenantSettingsIn":
        self.webhook_url = (self.webhook_url or "").strip() or None
        if self.webhook_url and not re.match(r"^https?://[^\s]+$", self.webhook_url):
            raise ValueError("URL webhook harus diawali http:// atau https://")
        if self.webhook_secret and len(self.webhook_secret) < 16:
            raise ValueError("Rahasia webhook minimal 16 karakter")
        if self.logo_data_url:
            if not self.logo_data_url.startswith(_LOGO_PREFIXES):
                raise ValueError("Logo harus gambar PNG, JPEG, WEBP, atau SVG")
            if len(self.logo_data_url) > MAX_LOGO_CHARS:
                raise ValueError("Logo terlalu besar (maksimal sekitar 200 KB)")
        if self.primary_color and not re.fullmatch(r"#[0-9a-fA-F]{6}", self.primary_color):
            raise ValueError("Warna harus format #RRGGBB")
        self.display_name = (self.display_name or "").strip() or None
        self.disabled_rules = sorted(set(self.disabled_rules))
        return self


class ApiClientCreate(BaseModel):
    name: str = Field(min_length=3, max_length=200)
    scopes: list[str] = ["claims:read"]


class ApiScopeOut(BaseModel):
    scope: str
    description: str


class ApiClientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    insurer_id: str
    name: str
    key_prefix: str
    scopes: list[str]
    is_active: bool
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class ApiClientCreated(ApiClientOut):
    api_key: str  # hanya ditampilkan sekali


class AssignRequest(BaseModel):
    doctor_id: str


class AssignmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    claim_id: str
    doctor_id: str
    level: str
    specialty: str | None
    method: str
    status: str
    assigned_at: datetime
    due_at: datetime
    closed_at: datetime | None


class IntegrationWhoAmI(BaseModel):
    client: str
    tenant_code: str
    scopes: list[str]
    label: str = "Data rekaan untuk demonstrasi"


class IntegrationClaimOut(BaseModel):
    """Status klaim untuk sistem asuransi. Rekomendasi hanya terisi bila sudah dirilis ke asuransi."""

    claim_number: str
    status: str
    triage_status: str | None = None
    recommendation: str | None = None
    billed_amount: int
    recommended_amount: int | None = None
    reason_codes: list[str] = []
    signed_by: str | None = None
    signed_at: datetime | None = None
    ruleset_version: str | None = None
    benefit_ruleset_version: str | None = None
    model_version: str | None = None
    decision: str | None = None
    source: str | None = None
    processing_error: str | None = None
    updated_at: datetime


class IntegrationSubmitOut(BaseModel):
    """Hasil kirim klaim lewat API/FHIR. Status akhir dikirim lewat webhook atau dibaca ulang."""

    claim_number: str
    claim_id: str
    status: str
    source: str
    documents: int
    job_id: str | None = None
    label: str = "Data rekaan untuk demonstrasi"


# --- Polis & benefit (U2) ---------------------------------------------------------------


class BenefitPlanIn(BaseModel):
    insurer_id: str | None = None
    code: str = Field(min_length=2, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=3, max_length=200)
    room_class: str | None = Field(default=None, max_length=50)
    room_rate_limit: int | None = Field(default=None, ge=0)
    annual_limit: int | None = Field(default=None, ge=0)
    waiting_period_days: int = Field(default=0, ge=0, le=3650)
    excluded_icd10: list[str] = []

    @model_validator(mode="after")
    def check(self) -> "BenefitPlanIn":
        self.code = self.code.upper()
        codes = [c.strip().upper() for c in self.excluded_icd10 if c and c.strip()]
        bad = [c for c in codes if not re.fullmatch(r"[A-Z][0-9A-Z.]{0,6}", c)]
        if bad:
            raise ValueError(f"Kode ICD-10 pengecualian tidak valid: {', '.join(bad)}")
        self.excluded_icd10 = sorted(set(codes))
        return self


class BenefitPlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    insurer_id: str
    code: str
    name: str
    room_class: str | None
    room_rate_limit: int | None
    annual_limit: int | None
    waiting_period_days: int
    excluded_icd10: list[str]
    policy_count: int = 0


class PolicyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    insurer_id: str
    policy_number: str
    member_id: str
    member_name: str | None
    plan_code: str
    plan_name: str
    room_class: str | None = None
    room_rate_limit: int | None = None
    annual_limit: int | None = None
    waiting_period_days: int = 0
    excluded_icd10: list[str] = []
    start_date: date
    end_date: date
    status: str
    limit_used: int
    limit_remaining: int | None = None
    source: str
    updated_at: datetime


class PolicyIn(BaseModel):
    """Satu polis lewat API integrasi (kolom sama dengan file impor)."""

    nomor_polis: str = Field(min_length=1, max_length=64)
    id_peserta: str = Field(min_length=1, max_length=64)
    nama_peserta: str | None = Field(default=None, max_length=200)
    kode_plan: str
    tanggal_mulai: date
    tanggal_akhir: date
    status: str = "ACTIVE"
    limit_terpakai: int = Field(default=0, ge=0)


class PolicyImportOut(BaseModel):
    job_id: str
    status: str
    created: int
    updated: int
    errors: list[str]


class IntegrationJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    insurer_id: str
    channel: str
    reference: str | None
    status: str
    summary: dict
    created_at: datetime


class WebhookDeliveryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    insurer_id: str
    event: str
    claim_id: str | None
    url: str
    status: str
    attempts: int
    last_status_code: int | None
    last_error: str | None
    created_at: datetime
    delivered_at: datetime | None
    payload: dict


ClaimDetail.model_rebuild()
RulesetOut.model_rebuild()
