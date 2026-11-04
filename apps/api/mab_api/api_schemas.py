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


class ClaimDetail(ClaimOut):
    documents: list[DocumentOut]
    missing_documents: list[str]
    triage_status: str | None = None


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
    doc: str | None = None
    page: int | None = None
    quote: str | None = None
    bbox: list[float] | None = None


class ExtractedFieldOut(BaseModel):
    """Field kamus data hasil pipeline, dengan bukti lokasi di dokumen."""

    model_config = ConfigDict(from_attributes=True)
    field_path: str
    value: Any = None
    source: str
    confidence: float | None = None
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
    model_version: str
    prompt_version: str
    ruleset_version: str
    insurer_decision: InsurerDecisionOut | None
    label: str = "Data rekaan untuk demonstrasi"


TokenResponse.model_rebuild()
