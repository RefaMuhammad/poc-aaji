"""Skema request/response API."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LoginRequest(BaseModel):
    email: str
    password: str


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


class ClaimCreate(BaseModel):
    claim_number: str = Field(min_length=1, max_length=64)
    policy_number: str = Field(min_length=1, max_length=64)
    member_id: str = Field(min_length=1, max_length=64)
    patient_name: str | None = Field(default=None, max_length=200)
    hospital_name: str = Field(min_length=1, max_length=200)
    admission_date: date
    discharge_date: date
    billed_amount: int = Field(ge=0)

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


class ClaimListItem(ClaimOut):
    """Baris daftar klaim. Triase/rekomendasi hanya terisi bila sudah boleh dilihat peran ini."""

    triage_status: str | None = None
    risk_score: int | None = None
    recommendation: str | None = None
    decision: str | None = None


class ClaimDetail(ClaimOut):
    documents: list[DocumentOut]
    missing_documents: list[str]
    triage_status: str | None = None
    recommendation_available: bool = False   # sudah ada rekomendasi yang boleh dilihat peran ini
    awaiting_doctor: bool = False            # ada draf yang menunggu tanda tangan dokter
    decision: str | None = None


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
