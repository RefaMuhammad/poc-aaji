"""Fakta mentah hasil ekstraksi dokumen (sebelum dihitung menjadi field kamus data).

Setiap fakta membawa source_line_ids: id baris dokumen tempat nilai itu dibaca.
"""
from __future__ import annotations

import datetime as dt
from enum import Enum
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Fact(BaseModel, Generic[T]):
    value: T | None = None
    source_line_ids: list[str] = Field(default_factory=list)


class LabTest(str, Enum):
    HB = "hb"
    HCT = "hct"
    WBC = "wbc"
    PLT = "plt"
    NS1 = "ns1"
    IGM = "dengue_igm"
    WIDAL_O = "widal_o"
    WIDAL_H = "widal_h"
    CULTURE_TYPHI = "culture_typhi"
    TYPHI_RAPID = "typhi_rapid"
    STOOL = "stool_pathogen"
    ELECTROLYTE = "electrolyte"
    OTHER = "other"


class LabResult(BaseModel):
    date: dt.date | None = None
    time: str | None = None
    test: LabTest
    # angka untuk hb/hct/wbc/plt; "pos"/"neg" untuk serologi, kultur, tes cepat;
    # penyebut titer untuk widal (1/160 -> 160); true/false untuk patogen feses
    value: float | str | bool | None = None
    source_line_ids: list[str] = Field(default_factory=list)


class BillingItem(BaseModel):
    date: dt.date | None = None
    time: str | None = None
    name: str
    qty: int = 1
    unit_price: int | None = None
    source_line_ids: list[str] = Field(default_factory=list)


class MedicationAdmin(BaseModel):
    date: dt.date | None = None
    name: str
    source_line_ids: list[str] = Field(default_factory=list)


class ResumeFacts(BaseModel):
    care_type: Fact[str] = Field(default_factory=Fact)
    patient_age: Fact[int] = Field(default_factory=Fact)
    admission_date: Fact[dt.date] = Field(default_factory=Fact)
    discharge_date: Fact[dt.date] = Field(default_factory=Fact)
    primary_dx: Fact[str] = Field(default_factory=Fact)        # kode ICD-10
    secondary_dx: Fact[list[str]] = Field(default_factory=Fact)
    attending_doctor: Fact[str] = Field(default_factory=Fact)


class LabFacts(BaseModel):
    results: list[LabResult] = Field(default_factory=list)


class BillingFacts(BaseModel):
    items: list[BillingItem] = Field(default_factory=list)


class CpptFacts(BaseModel):
    medications: list[MedicationAdmin] = Field(default_factory=list)


class ClaimFacts(BaseModel):
    """Gabungan fakta semua dokumen satu klaim. None = dokumen jenis itu tidak ada."""

    documents_present: list[str] = Field(default_factory=list)
    resume: ResumeFacts | None = None
    labs: LabFacts | None = None
    billing: BillingFacts | None = None
    cppt: CpptFacts | None = None
