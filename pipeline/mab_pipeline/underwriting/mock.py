"""Jawaban LLM tiruan untuk dokumen underwriting sintetis (U7).

Nilai diambil dari case.json kasus sintetis (data/synthetic_output/underwriting/<kasus>/), tetapi
HANYA bila baris tempat nilai itu tertulis benar-benar terbaca di dokumen. Bila baris tidak
ditemukan (mis. hasil OCR buruk), nilai dikembalikan null, seperti LLM yang tidak bisa membacanya.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from mab_pipeline.llm.mock import _Locator
from mab_pipeline.underwriting.constants import ECG_TEXT, LAB_LABELS, QUESTIONS

_SPAJ_RE = re.compile(r"SPAJ-\d{4}-\d{4}")
_index: dict[Path, dict[str, Path]] = {}


def _dmy(iso: str) -> str:
    return date.fromisoformat(iso).strftime("%d/%m/%Y")


def _rp(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _dec(x: float) -> str:
    return f"{x:.1f}".replace(".", ",")


def find_case(fixtures_dir: Path, text: str, hint: str | None = None) -> dict | None:
    root = fixtures_dir / "underwriting"
    if root not in _index:
        _index[root] = {}
        for path in root.glob("*/case.json"):
            case = json.loads(path.read_text(encoding="utf-8"))
            _index[root][case["spaj_number"]] = path
    for number in [*_SPAJ_RE.findall(text), hint]:
        if number and number in _index[root]:
            return json.loads(_index[root][number].read_text(encoding="utf-8"))
    return None


def _fact(loc: _Locator, value: Any, *needles: str) -> dict:
    row = loc.find(*needles)
    if row is None:
        return {"value": None, "source_line_ids": []}
    return {"value": value, "source_line_ids": loc.ids(row)}


def _spaj(case: dict, loc: _Locator) -> dict:
    a, p = case["applicant"], case["product"]
    return {
        "spaj_number": _fact(loc, case["spaj_number"], "no. spaj", case["spaj_number"]),
        "applicant_name": _fact(loc, a["name"], "nama calon tertanggung", a["name"]),
        "sex": _fact(loc, a["sex"], "jenis kelamin"),
        "birth_date": _fact(loc, a["birth_date"], "tanggal lahir", _dmy(a["birth_date"])),
        "occupation": _fact(loc, a["occupation"], "pekerjaan", a["occupation"]),
        "product": _fact(loc, p["name"], "produk", p["name"]),
        "sum_assured": _fact(loc, p["sum_assured"], "uang pertanggungan", _rp(p["sum_assured"])),
        "base_premium": _fact(loc, p["base_premium"], "premi dasar", _rp(p["base_premium"])),
        "spaj_date": _fact(loc, case["spaj_date"], "tanggal spaj", _dmy(case["spaj_date"])),
    }


def _questionnaire(case: dict, loc: _Locator) -> dict:
    by_code = {q["code"]: q for q in case["questionnaire"]}
    answers = []
    for code, _, text in QUESTIONS:
        q = by_code[code]
        row = loc.find(text, "ya" if q["answer"] else "tidak")
        answers.append({"code": code, "value": q["answer"] if row is not None else None,
                        "detail": q["detail"] if row is not None else None, "source_line_ids": loc.ids(row)})
    return {"answers": answers}


def _mcu(case: dict, loc: _Locator) -> dict:
    m = case["mcu"]
    return {
        "exam_date": _fact(loc, m["date"], "tanggal pemeriksaan", _dmy(m["date"])),
        "height_cm": _fact(loc, m["height_cm"], "tinggi badan", f"{m['height_cm']} cm"),
        "weight_kg": _fact(loc, m["weight_kg"], "berat badan", f"{m['weight_kg']} kg"),
        "systolic": _fact(loc, m["systolic"], "tekanan darah", f"{m['systolic']}/{m['diastolic']}"),
        "diastolic": _fact(loc, m["diastolic"], "tekanan darah", f"{m['systolic']}/{m['diastolic']}"),
        "pulse": _fact(loc, m["pulse"], "nadi", f"{m['pulse']} x"),
        "ecg": _fact(loc, m["ecg"], "ekg", ECG_TEXT[m["ecg"]]),
    }


def _lab(case: dict, loc: _Locator) -> dict:
    results = []
    for test, value in case["lab"].items():
        if test == "hbsag":
            # kolom nilai rujukan selalu "Non-reaktif": yang menentukan adalah kata setelah label
            row = loc.find("hbsagnon" if value == "neg" else "hbsagreaktif")
        elif test == "urine_protein":
            row = loc.find(LAB_LABELS[test], "negatif" if value == "neg" else value)
        else:
            row = loc.find(LAB_LABELS[test], _dec(value) if isinstance(value, float) else str(value))
        results.append({"test": test, "value": value if row is not None else None, "source_line_ids": loc.ids(row)})
    return {"results": results}


def _letter(case: dict, loc: _Locator) -> dict:
    lt = case["letter"]
    return {
        "diagnosis": _fact(loc, lt["diagnosis"], "diagnosis", lt["diagnosis"].split(" (")[0]),
        "since_year": _fact(loc, lt["since_year"], "sejak tahun", str(lt["since_year"])),
        "treatment": _fact(loc, lt["treatment"], "terapi saat ini"),
        "controlled": _fact(loc, lt["controlled"], "kondisi saat ini", "terkontrol baik" if lt["controlled"] else "belum terkontrol"),
        "letter_date": _fact(loc, lt["date"], "kontrol terakhir"),
        "doctor": _fact(loc, lt["doctor"], lt["doctor"].split(",")[0]),
    }


EMPTY = {"spaj": {}, "kuesioner_kesehatan": {"answers": []}, "hasil_mcu": {}, "hasil_lab_uw": {"results": []},
         "surat_dokter": {}}
BUILDERS = {"spaj": _spaj, "kuesioner_kesehatan": _questionnaire, "hasil_mcu": _mcu, "hasil_lab_uw": _lab,
            "surat_dokter": _letter}


def answer(fixtures_dir: Path, task: str, context: dict[str, Any]) -> str:
    if task == "uw_classify":
        return json.dumps({"doc_type": "unknown"})
    doc_type = task.split(":", 1)[1]
    lines: list[dict] = context.get("lines") or []
    if not lines or doc_type not in BUILDERS:
        return json.dumps(EMPTY.get(doc_type, {}))
    case = find_case(fixtures_dir, "\n".join(l["text"] for l in lines), context.get("spaj_hint"))
    if case is None or (doc_type == "surat_dokter" and "letter" not in case):
        return json.dumps(EMPTY[doc_type])
    return json.dumps(BUILDERS[doc_type](case, _Locator(lines)), ensure_ascii=False)
