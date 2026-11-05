"""Fakta hasil ekstraksi dokumen pengajuan (U7). Setiap nilai membawa source_line_ids."""
from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

from mab_pipeline.extraction.facts import Fact

UwLabTest = Literal["fasting_glucose", "hba1c", "total_cholesterol", "ldl", "hdl", "triglycerides", "sgot", "sgpt",
                    "creatinine", "hbsag", "urine_protein", "other"]


class SpajFacts(BaseModel):
    spaj_number: Fact[str] = Field(default_factory=Fact)
    applicant_name: Fact[str] = Field(default_factory=Fact)
    sex: Fact[Literal["L", "P"]] = Field(default_factory=Fact)
    birth_date: Fact[dt.date] = Field(default_factory=Fact)
    occupation: Fact[str] = Field(default_factory=Fact)
    product: Fact[str] = Field(default_factory=Fact)
    sum_assured: Fact[int] = Field(default_factory=Fact)
    base_premium: Fact[int] = Field(default_factory=Fact)
    spaj_date: Fact[dt.date] = Field(default_factory=Fact)


class QuestionAnswer(BaseModel):
    code: Literal["Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7", "Q8", "Q9"]
    value: bool | None = None
    detail: str | None = None
    source_line_ids: list[str] = Field(default_factory=list)


class QuestionnaireFacts(BaseModel):
    answers: list[QuestionAnswer] = Field(default_factory=list)


class McuFacts(BaseModel):
    exam_date: Fact[dt.date] = Field(default_factory=Fact)
    height_cm: Fact[float] = Field(default_factory=Fact)
    weight_kg: Fact[float] = Field(default_factory=Fact)
    systolic: Fact[int] = Field(default_factory=Fact)
    diastolic: Fact[int] = Field(default_factory=Fact)
    pulse: Fact[int] = Field(default_factory=Fact)
    ecg: Fact[Literal["normal", "abnormal_ringan", "iskemia"]] = Field(default_factory=Fact)


class UwLabResult(BaseModel):
    test: UwLabTest
    value: float | str | None = None
    source_line_ids: list[str] = Field(default_factory=list)


class UwLabFacts(BaseModel):
    results: list[UwLabResult] = Field(default_factory=list)


class DoctorLetterFacts(BaseModel):
    diagnosis: Fact[str] = Field(default_factory=Fact)
    since_year: Fact[int] = Field(default_factory=Fact)
    treatment: Fact[str] = Field(default_factory=Fact)
    controlled: Fact[bool] = Field(default_factory=Fact)
    letter_date: Fact[dt.date] = Field(default_factory=Fact)
    doctor: Fact[str] = Field(default_factory=Fact)


UW_EXTRACT_MODELS: dict[str, type[BaseModel]] = {
    "spaj": SpajFacts,
    "kuesioner_kesehatan": QuestionnaireFacts,
    "hasil_mcu": McuFacts,
    "hasil_lab_uw": UwLabFacts,
    "surat_dokter": DoctorLetterFacts,
}
