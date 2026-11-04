"""Fakta dokumen -> field kamus data (sumber 'dokumen' dan 'hitung'), beserta id baris bukti.

Aturan umum: None berarti "tidak tertulis / tidak bisa dihitung", bukan "tidak ada".
- Field lab hanya diisi bila dokumen hasil laboratorium ada; hitungan (mis. jumlah
  tes Widal) bernilai 0 bila dokumen lab ada tetapi tesnya tidak ditemukan.
- Field terapi dibaca dari rincian tagihan; bila tagihan tidak ada, dari CPPT.
- Field ber-sumber 'ai' (klinis) dikerjakan di M5; history.* dihitung dari database.
Fungsi ini juga dipakai generator data sintetis untuk membuat ground truth, sehingga
definisi "nilai benar" sama persis dengan cara pipeline menghitung.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from mab_pipeline.extraction.facts import ClaimFacts, LabResult, LabTest

DEFAULT_REQUIRED_DOCS = ("resume_medis", "rincian_tagihan", "hasil_laboratorium")

# Kata kunci nama obat (huruf kecil). Daftar sederhana untuk POC.
CEFTRIAXONE_WORDS = ("seftriakson", "ceftriaxone", "ceftriakson")
FLUOROQUINOLONE_WORDS = ("siprofloksasin", "ciprofloxacin", "levofloksasin", "levofloxacin", "ofloksasin", "ofloxacin", "norfloksasin", "norfloxacin", "moksifloksasin", "moxifloxacin")
ANTIBIOTIC_WORDS = CEFTRIAXONE_WORDS + FLUOROQUINOLONE_WORDS + (
    "sefiksim", "cefixime", "sefotaksim", "cefotaxime", "kloramfenikol", "chloramphenicol", "tiamfenikol",
    "amoksisilin", "amoxicillin", "ampisilin", "ampicillin", "azitromisin", "azithromycin", "kotrimoksazol",
    "cotrimoxazole", "metronidazol", "metronidazole", "meropenem", "gentamisin", "gentamicin", "doksisiklin",
)
IV_FLUID_WORDS = ("infus", "ringer", "nacl 0,9", "nacl 0.9", "kristaloid", "dextrose", "asering")
CBC_TESTS = (LabTest.HB, LabTest.HCT, LabTest.WBC, LabTest.PLT)


@dataclass
class DerivedValue:
    value: Any
    source: str                       # dokumen | hitung
    line_ids: list[str] = field(default_factory=list)


def _has(name: str, words: tuple[str, ...]) -> bool:
    lowered = name.lower()
    return any(w in lowered for w in words)


def _ids(*groups: list[str]) -> list[str]:
    return list(dict.fromkeys(i for g in groups for i in g))


def _posneg(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in ("pos", "positif", "positive", "reaktif", "+", "true"):
        return "pos"
    if text in ("neg", "negatif", "negative", "non reaktif", "nonreaktif", "-", "false"):
        return "neg"
    return None


def _number(value: Any) -> float | None:
    """Angka dari nilai LLM: 95000, "95.000", "13,4", "40.1 %"."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = re.search(r"\d{1,3}(?:\.\d{3})+(?!\d)|\d+(?:[.,]\d+)?", str(value))
    if not m:
        return None
    text = m.group()
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", text):  # pemisah ribuan gaya Indonesia
        return float(text.replace(".", ""))
    return float(text.replace(",", "."))


def _titer(value: Any) -> int | None:
    if value is None:
        return None
    m = re.search(r"1\s*/\s*(\d+)", str(value))
    if m:
        return int(m.group(1))
    n = _number(value)
    return int(n) if n is not None else None


def _first(results: list[LabResult], test: LabTest) -> LabResult | None:
    return next((r for r in results if r.test == test and r.value is not None), None)


def derive(facts: ClaimFacts, required_docs: tuple[str, ...] = DEFAULT_REQUIRED_DOCS) -> dict[str, DerivedValue]:
    out: dict[str, DerivedValue] = {}

    def put(path: str, value: Any, source: str, *ids: list[str]) -> None:
        out[path] = DerivedValue(value, source, _ids(*ids))

    # --- resume -----------------------------------------------------------------------
    r = facts.resume
    admit = r.admission_date if r else None
    discharge = r.discharge_date if r else None
    care = r.care_type.value if r else None
    if care is None and admit and discharge and admit.value and discharge.value and discharge.value > admit.value:
        care = "inpatient"
    put("claim.care_type", care, "dokumen", r.care_type.source_line_ids if r else [])
    los = None
    if admit and discharge and isinstance(admit.value, date) and isinstance(discharge.value, date):
        los = (discharge.value - admit.value).days
    put("claim.los_days", los, "hitung", admit.source_line_ids if los is not None else [], discharge.source_line_ids if los is not None else [])
    put("claim.patient_age", r.patient_age.value if r else None, "dokumen", r.patient_age.source_line_ids if r else [])
    put("dx.primary", (r.primary_dx.value or None) if r else None, "dokumen", r.primary_dx.source_line_ids if r else [])
    put("dx.secondary", list(r.secondary_dx.value or []) if r else None, "dokumen", r.secondary_dx.source_line_ids if r else [])

    # --- lab --------------------------------------------------------------------------
    labs = facts.labs
    results = labs.results if labs else []
    has_labs = labs is not None

    plts = [(x, _number(x.value)) for x in results if x.test == LabTest.PLT]
    plts = [(x, v) for x, v in plts if v is not None]
    if plts:
        low = min(plts, key=lambda p: p[1])
        put("lab.platelet_min", int(low[1]), "dokumen", low[0].source_line_ids)
    else:
        put("lab.platelet_min", None, "dokumen")

    hcts = [(x, _number(x.value)) for x in results if x.test == LabTest.HCT]
    hcts = [(x, v) for x, v in hcts if v is not None]
    if len(hcts) >= 2:
        lo = min(hcts, key=lambda p: p[1])
        hi = max(hcts, key=lambda p: p[1])
        put("lab.hct_rise_pct", round((hi[1] - lo[1]) / lo[1] * 100, 1), "hitung", lo[0].source_line_ids, hi[0].source_line_ids)
    else:
        put("lab.hct_rise_pct", None, "hitung")

    for path, test in (("lab.dengue_ns1", LabTest.NS1), ("lab.dengue_igm", LabTest.IGM),
                       ("lab.blood_culture_typhi", LabTest.CULTURE_TYPHI), ("lab.typhi_rapid", LabTest.TYPHI_RAPID)):
        found = _first(results, test)
        put(path, _posneg(found.value) if found else None, "dokumen", found.source_line_ids if found else [])

    # satu pemeriksaan darah lengkap = satu pasangan (tanggal, jam) dengan tes darah lengkap
    panels: dict[Any, dict[Any, list[str]]] = defaultdict(dict)
    for x in results:
        if x.test in CBC_TESTS:
            panels[x.date].setdefault(x.time, [])
            panels[x.date][x.time] += x.source_line_ids
    if panels:
        busiest = max(panels, key=lambda d: len(panels[d]))
        put("lab.cbc_max_per_day", len(panels[busiest]), "hitung", *panels[busiest].values())
    else:
        put("lab.cbc_max_per_day", None, "hitung")

    widal_o = [(x, _titer(x.value)) for x in results if x.test == LabTest.WIDAL_O]
    widal_o = [(x, t) for x, t in widal_o if t is not None]
    widal_o.sort(key=lambda p: (p[0].date or date.min, p[0].time or ""))
    widal_events = {(x.date, x.time) for x in results if x.test in (LabTest.WIDAL_O, LabTest.WIDAL_H)}
    put("lab.widal_tests", len(widal_events) if has_labs else None, "hitung", *[x.source_line_ids for x, _ in widal_o])
    if widal_o:
        top = max(widal_o, key=lambda p: p[1])
        put("lab.widal_o_max_titer", top[1], "dokumen", top[0].source_line_ids)
        rise = len(widal_o) >= 2 and widal_o[-1][1] >= 4 * widal_o[0][1]
        put("lab.widal_fourfold_rise", rise, "hitung", widal_o[0][0].source_line_ids, widal_o[-1][0].source_line_ids)
    else:
        put("lab.widal_o_max_titer", None, "dokumen")
        put("lab.widal_fourfold_rise", None, "hitung")

    stool = _first(results, LabTest.STOOL)
    stool_value = None
    if stool is not None:
        stool_value = stool.value if isinstance(stool.value, bool) else _posneg(stool.value) == "pos"
    put("lab.stool_pathogen", stool_value, "dokumen", stool.source_line_ids if stool else [])

    # --- terapi -----------------------------------------------------------------------
    if facts.billing is not None:
        meds = [(it.date, it.name, it.source_line_ids) for it in facts.billing.items]
    elif facts.cppt is not None:
        meds = [(m.date, m.name, m.source_line_ids) for m in facts.cppt.medications]
    else:
        meds = None

    def days_with(words: tuple[str, ...]) -> tuple[int | None, list[str]]:
        if meds is None:
            return None, []
        hits = [(d, ids) for d, name, ids in meds if _has(name, words)]
        return len({d for d, _ in hits}), _ids(*(ids for _, ids in hits))

    def any_with(words: tuple[str, ...]) -> tuple[bool | None, list[str]]:
        if meds is None:
            return None, []
        hits = [ids for _, name, ids in meds if _has(name, words)]
        return bool(hits), (hits[0] if hits else [])

    put("tx.iv_fluid_days", *_split(days_with(IV_FLUID_WORDS), "dokumen"))
    put("tx.antibiotic_given", *_split(any_with(ANTIBIOTIC_WORDS), "dokumen"))
    put("tx.ceftriaxone_days", *_split(days_with(CEFTRIAXONE_WORDS), "hitung"))
    put("tx.fluoroquinolone_given", *_split(any_with(FLUOROQUINOLONE_WORDS), "dokumen"))

    # --- tagihan ----------------------------------------------------------------------
    if facts.billing is not None:
        groups: dict[tuple, list] = defaultdict(list)
        for it in facts.billing.items:
            groups[(" ".join(it.name.lower().split()), it.date, it.time)].append(it)
        dups = [g for g in groups.values() if len(g) > 1]
        put("bill.duplicate_items", sum(len(g) - 1 for g in dups), "hitung", *[it.source_line_ids for g in dups for it in g])
    else:
        put("bill.duplicate_items", None, "hitung")

    # --- dokumen ----------------------------------------------------------------------
    present = set(facts.documents_present)
    put("docs.missing", [d for d in required_docs if d not in present], "hitung")
    return out


def _split(pair: tuple[Any, list[str]], source: str) -> tuple[Any, str, list[str]]:
    return pair[0], source, pair[1]


def to_claim_dict(derived: dict[str, DerivedValue]) -> dict[str, dict[str, Any]]:
    """{'lab.platelet_min': DerivedValue} -> {'lab': {'platelet_min': ...}} untuk ClaimData."""
    nested: dict[str, dict[str, Any]] = defaultdict(dict)
    for path, dv in derived.items():
        group, name = path.split(".", 1)
        nested[group][name] = dv.value
    return dict(nested)
