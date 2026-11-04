"""Skema data klaim, temuan, dan hasil triase.

Field di sini harus sama persis dengan bagian `kamus_data` pada
rules/aturan_klinis_demo.yaml (dicek oleh tests/test_rules.py).

Semua field boleh None. None berarti "tidak diketahui" (tidak ada di dokumen,
atau bukti AI tidak ditemukan), BUKAN "tidak ada".
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class _Group(BaseModel):
    """Satu kelompok field. Field di luar kamus data ditolak."""

    model_config = ConfigDict(extra="forbid")


class ClaimInfo(_Group):
    care_type: str | None = None
    los_days: float | None = None
    patient_age: float | None = None


class DiagnosisInfo(_Group):
    primary: str | None = None
    secondary: list[str] | None = None


class LabInfo(_Group):
    platelet_min: float | None = None
    hct_rise_pct: float | None = None
    dengue_ns1: str | None = None
    dengue_igm: str | None = None
    cbc_max_per_day: float | None = None
    widal_tests: float | None = None
    widal_o_max_titer: float | None = None
    widal_fourfold_rise: bool | None = None
    blood_culture_typhi: str | None = None
    typhi_rapid: str | None = None
    stool_pathogen: bool | None = None


class ClinicalInfo(_Group):
    plasma_leakage: bool | None = None
    warning_signs: list[str] | None = None
    spontaneous_bleeding: bool | None = None
    shock: bool | None = None
    unable_to_drink: bool | None = None
    comorbidities: list[str] | None = None
    dehydration: str | None = None
    persistent_vomiting: bool | None = None
    bloody_diarrhea: bool | None = None
    suspected_cholera: bool | None = None
    daldiyono_score: float | None = None
    poor_general_condition: bool | None = None
    days_after_discharge_criteria: float | None = None
    complication_documented: bool | None = None


class TreatmentInfo(_Group):
    iv_fluid_days: float | None = None
    antibiotic_given: bool | None = None
    ceftriaxone_days: float | None = None
    fluoroquinolone_given: bool | None = None


class BillingInfo(_Group):
    duplicate_items: float | None = None
    items_without_clinical_note: float | None = None


class DocsInfo(_Group):
    missing: list[str] | None = None


class HistoryInfo(_Group):
    overlapping_claims: float | None = None


# Nama kelompok di ekspresi aturan -> nama atribut di ClaimData
GROUPS: tuple[str, ...] = ("claim", "dx", "lab", "clin", "tx", "bill", "docs", "history")


class ClaimData(BaseModel):
    """Data klaim hasil ekstraksi, siap dievaluasi mesin aturan."""

    # Kunci lain di level atas (mis. "_skenario" di file uji) diabaikan.
    model_config = ConfigDict(extra="ignore")

    claim_id: str | None = None
    claim: ClaimInfo = Field(default_factory=ClaimInfo)
    dx: DiagnosisInfo = Field(default_factory=DiagnosisInfo)
    lab: LabInfo = Field(default_factory=LabInfo)
    clin: ClinicalInfo = Field(default_factory=ClinicalInfo)
    tx: TreatmentInfo = Field(default_factory=TreatmentInfo)
    bill: BillingInfo = Field(default_factory=BillingInfo)
    docs: DocsInfo = Field(default_factory=DocsInfo)
    history: HistoryInfo = Field(default_factory=HistoryInfo)

    @classmethod
    def field_paths(cls) -> set[str]:
        """Semua field dalam bentuk 'kelompok.field', untuk dicocokkan dengan kamus data."""
        paths: set[str] = set()
        for group in GROUPS:
            group_model = cls.model_fields[group].annotation
            paths.update(f"{group}.{name}" for name in group_model.model_fields)  # type: ignore[union-attr]
        return paths

    def get_field(self, path: str):
        group, name = path.split(".", 1)
        return getattr(getattr(self, group), name)


class Severity(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class TriageStatus(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


class InitialRecommendation(str, Enum):
    PAY_FULL = "PAY_FULL"
    DOCTOR_REVIEW = "DOCTOR_REVIEW"
    PEND = "PEND"


class Finding(BaseModel):
    """Satu temuan dari aturan yang terpicu. Bukti (kutipan) ditempelkan di M5."""

    rule_id: str
    rule_name: str
    reason_code: str
    severity: Severity
    needs_ai_evidence: bool
    message: str
    reference: str | None = None
    fields_used: list[str] = Field(default_factory=list)


class SkippedRule(BaseModel):
    """Aturan yang tidak bisa dinilai karena data yang dibutuhkan kosong."""

    rule_id: str
    missing_fields: list[str]


class TriageResult(BaseModel):
    claim_id: str | None
    ruleset_version: str
    matched_diagnosis: str | None
    triage_status: TriageStatus
    risk_score: int
    initial_recommendation: InitialRecommendation
    findings: list[Finding]
    skipped_rules: list[SkippedRule] = Field(default_factory=list)
