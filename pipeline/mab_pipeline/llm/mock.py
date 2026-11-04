"""LLM tiruan untuk tes dan demo tanpa API key.

Jawaban disusun dari isi klaim sintetis (data/synthetic_output/<claim_id>/case.json),
dalam bentuk JSON yang sama dengan jawaban LLM sungguhan. source_line_ids dicari
dengan mencocokkan teks nilai pada baris dokumen yang benar-benar terbaca; bila
dokumen tidak punya teks (mis. pindaian tanpa OCR), mock tidak mengembalikan apa pun,
persis seperti LLM yang tidak bisa membaca apa-apa.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date
from pathlib import Path
from typing import Any

MONTHS = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember"]
MOCK_MODEL_VERSION = "mock-llm-1"

# Frasa yang ditulis generator sintetis untuk setiap temuan klinis (dipakai juga oleh generator)
WARNING_SIGN_TEXT = {
    "nyeri abdomen": "nyeri perut kanan atas",
    "perdarahan mukosa": "gusi berdarah saat sikat gigi",
    "muntah persisten": "muntah terus-menerus setiap diberi makan/minum",
    "letargi": "pasien tampak letargis",
}
CLINICAL_PHRASES = {
    "clin.plasma_leakage": "efusi pleura",
    "clin.spontaneous_bleeding": "petekie spontan",
    "clin.shock": "akral dingin",
    "clin.unable_to_drink": "tidak mau minum",
    "clin.persistent_vomiting": "muntah setiap diberi minum",
    "clin.bloody_diarrhea": "berlendir darah",
    "clin.poor_general_condition": "keadaan umum lemah",
    "clin.days_after_discharge_criteria": "layak pulang",
    "clin.complication_documented": "melena",
}
DEHYDRATION_TEXT = {"berat": "kesan dehidrasi berat", "ringan-sedang": "kesan dehidrasi ringan-sedang", "tanpa": "tanpa dehidrasi"}


def _default_fixtures_dir() -> Path:
    env = os.getenv("LLM_MOCK_FIXTURES_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3] / "data" / "synthetic_output"


# ----------------------------------------------------------------------------- case.json -> fakta


def _num(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def case_to_facts(case: dict) -> dict[str, dict]:
    """Isi tiap jenis dokumen sintetis sebagai fakta (tanpa id baris).

    Dipakai mock LLM dan generator ground truth, supaya keduanya membaca
    "dokumen" yang sama.
    """
    facts: dict[str, dict] = {}
    docs = set(case["documents"])
    if "resume_medis" in docs:
        facts["resume_medis"] = {
            "care_type": {"value": "inpatient"},
            "patient_age": {"value": case["patient"]["age"]},
            "admission_date": {"value": case["admission_date"]},
            "discharge_date": {"value": case["discharge_date"]},
            "primary_dx": {"value": case["icd10"]},
            "secondary_dx": {"value": list(case["secondary_icd10"])},
            "attending_doctor": {"value": case["doctor"]},
        }
    if "hasil_laboratorium" in docs:
        results: list[dict] = []
        for r in case["labs"]:
            v = r["values"]
            base = {"date": r["date"], "time": r["time"]}
            if r["type"] == "darah_lengkap":
                for test in ("hb", "hct", "wbc", "plt"):
                    results.append({**base, "test": test, "value": v[test]})
            elif r["type"] in ("ns1", "igm", "kultur", "tes_cepat"):
                test = {"ns1": "ns1", "igm": "dengue_igm", "kultur": "culture_typhi", "tes_cepat": "typhi_rapid"}[r["type"]]
                results.append({**base, "test": test, "value": v["result"]})
            elif r["type"] == "widal":
                results.append({**base, "test": "widal_o", "value": v["o"]})
                results.append({**base, "test": "widal_h", "value": v["h"]})
            elif r["type"] == "feses":
                results.append({**base, "test": "stool_pathogen", "value": bool(v["pathogen"])})
            elif r["type"] == "elektrolit":
                results.append({**base, "test": "electrolyte", "value": f"{v['na']} / {v['k']} / {v['cl']} mmol/L"})
        facts["hasil_laboratorium"] = {"results": results}
    if "rincian_tagihan" in docs:
        facts["rincian_tagihan"] = {
            "items": [
                {"date": it["date"], "time": it["time"], "name": it["name"], "qty": it["qty"], "unit_price": it["price"]}
                for it in case["billing"]
            ]
        }
    if "cppt" in docs:
        facts["cppt"] = {
            "medications": [{"date": n["date"], "name": m} for n in case["cppt"] for m in n.get("meds", [])]
        }
    return facts


# ----------------------------------------------------------------------------- pencarian baris


def _norm(text: str) -> str:
    # tanpa spasi: hasil OCR sering menghapus atau menambah spasi
    return re.sub(r"\s+", "", text.lower())


class _Locator:
    def __init__(self, lines: list[dict]):
        self.lines = lines
        self.texts = [_norm(l["text"]) for l in lines]

    def find(self, *needles: str, start: int = 0, stop: int | None = None) -> int | None:
        wanted = [_norm(n) for n in needles if n]
        for i in range(start, len(self.texts) if stop is None else min(stop, len(self.texts))):
            if all(n in self.texts[i] for n in wanted):
                return i
        return None

    def ids(self, *indexes: int | None) -> list[str]:
        return [self.lines[i]["id"] for i in dict.fromkeys(i for i in indexes if i is not None)]


def _fmt_date(iso: str, hospital: dict) -> str:
    d = date.fromisoformat(iso)
    if hospital.get("date_format") == "indo":
        return f"{d.day} {MONTHS[d.month - 1]} {d.year}"
    return d.strftime(hospital["date_format"])


def _locate_resume(facts: dict, loc: _Locator, case: dict) -> None:
    dates = loc.find("tanggal masuk")
    facts["care_type"]["source_line_ids"] = loc.ids(dates)
    facts["admission_date"]["source_line_ids"] = loc.ids(dates)
    facts["discharge_date"]["source_line_ids"] = loc.ids(loc.find("tanggal keluar"))
    facts["patient_age"]["source_line_ids"] = loc.ids(loc.find(f"{case['patient']['age']} tahun"))
    facts["primary_dx"]["source_line_ids"] = loc.ids(loc.find("diagnosis utama", case["icd10"]))
    facts["secondary_dx"]["source_line_ids"] = loc.ids(loc.find("diagnosis sekunder"), *(loc.find(c) for c in case["secondary_icd10"]))
    facts["attending_doctor"]["source_line_ids"] = loc.ids(loc.find(case["doctor"]))


def _lab_needles(r: dict, labels: dict) -> tuple[str, ...]:
    test, value = r["test"], r["value"]
    if test in ("hb", "hct", "wbc"):
        return (labels[test], str(value))
    if test == "plt":
        return (labels["plt"], _num(int(value)))
    if test == "ns1":
        return ("ns1",)
    if test == "dengue_igm":
        return ("igm",)
    if test == "widal_o":
        return ("typhi o", f"1/{value}")
    if test == "widal_h":
        return ("typhi h", f"1/{value}")
    if test == "culture_typhi":
        return ("kultur darah",)
    if test == "typhi_rapid":
        return ("positif" if value == "pos" else "negatif",)
    if test == "stool_pathogen":
        return ("feses",)
    return ("natrium",)


def _locate_labs(facts: dict, loc: _Locator, case: dict) -> None:
    hospital = case["hospital"]
    headers = {}
    for r in facts["results"]:
        if r["date"] not in headers:
            headers[r["date"]] = loc.find(_fmt_date(r["date"], hospital))
    starts = sorted(i for i in headers.values() if i is not None)
    for r in facts["results"]:
        head = headers[r["date"]]
        stop = next((s for s in starts if head is not None and s > head), None)
        row = loc.find(*_lab_needles(r, hospital["labels"]), start=head or 0, stop=stop)
        r["source_line_ids"] = loc.ids(head, row) if row is not None else []


def _locate_sequential(items: list[dict], loc: _Locator, needles) -> None:
    pos = 0
    for item in items:
        row = loc.find(*needles(item), start=pos)
        if row is None:
            item["source_line_ids"] = []
            continue
        item["source_line_ids"] = loc.ids(row)
        pos = row + 1


def _locate_cppt(meds: list[dict], loc: _Locator) -> None:
    """Beberapa obat bisa berada di baris yang sama; pencarian maju per tanggal catatan."""
    start, current, last = 0, None, -1
    for m in meds:
        if m["date"] != current:
            current, start = m["date"], last + 1
        row = loc.find(m["name"].split()[0], start=start)
        m["source_line_ids"] = loc.ids(row) if row is not None else []
        if row is not None:
            last = max(last, row)


class MockLLMClient:
    model_version = MOCK_MODEL_VERSION

    def __init__(self, fixtures_dir: str | Path | None = None):
        self.fixtures_dir = Path(fixtures_dir) if fixtures_dir else _default_fixtures_dir()
        self._by_mrn: dict[str, Path] | None = None

    def _find_case(self, claim_number: str | None, text: str) -> dict | None:
        if claim_number:
            path = self.fixtures_dir / claim_number / "case.json"
            if path.is_file():
                return json.loads(path.read_text(encoding="utf-8"))
        if self._by_mrn is None:
            self._by_mrn = {}
            for path in self.fixtures_dir.glob("*/case.json"):
                case = json.loads(path.read_text(encoding="utf-8"))
                self._by_mrn[case["patient"]["mrn"]] = path
        for mrn in re.findall(r"RM-\d{6}", text):
            if mrn in self._by_mrn:
                return json.loads(self._by_mrn[mrn].read_text(encoding="utf-8"))
        return None

    def _reason(self, case: dict, lines: list[dict], paths: list[str]) -> dict:
        """Jawaban penalaran klinis: nilai dari kebenaran klinis skenario, kutipan = baris
        dokumen yang memuat frasanya (bila terbaca)."""
        compact = [(re.sub(r"\s+", "", l["text"].lower()), l["text"]) for l in lines]

        def quote(phrase: str) -> str:
            key = re.sub(r"\s+", "", phrase.lower())
            return next((text for norm, text in compact if key in norm), phrase)

        clin = case["clinical"]
        out: dict[str, Any] = {}
        for path in paths:
            if path == "bill.items_without_clinical_note":
                if "rincian_tagihan" not in case["documents"]:
                    out[path] = {"value": None}
                else:
                    out[path] = {"value": [{"item": i, "quote": quote(i)} for i in case["undocumented_billed_items"]]}
                continue
            name = path.split(".", 1)[1]
            value = clin.get(name)
            if value is None:
                out[path] = {"value": None}
            elif name == "warning_signs":
                out[path] = {"value": [{"item": w, "quote": quote(WARNING_SIGN_TEXT[w])} for w in value]}
            elif name == "comorbidities":
                out[path] = {"value": [{"item": c, "quote": quote(f"riwayat {c}")} for c in value]}
            elif name == "dehydration":
                out[path] = {"value": value, "quotes": [quote(DEHYDRATION_TEXT[value])]}
            elif name == "daldiyono_score":
                out[path] = {"value": value, "quotes": [quote(f"Skor Daldiyono: {value}")]}
            elif value in (False, 0):
                out[path] = {"value": value, "quotes": []}
            else:
                out[path] = {"value": value, "quotes": [quote(CLINICAL_PHRASES.get(path, str(value)))]}
        return {"fields": out}

    def complete_json(self, system: str, user: str, *, task: str, context: dict[str, Any]) -> str:
        lines: list[dict] = context.get("lines") or []
        if task == "classify":
            return json.dumps({"doc_type": "unknown"})
        if task == "reason":
            case = self._find_case(context.get("claim_number"), "\n".join(l["text"] for l in lines)) if lines else None
            if case is None:
                return json.dumps({"fields": {}})
            return json.dumps(self._reason(case, lines, context.get("fields") or []), ensure_ascii=False)
        doc_type = task.split(":", 1)[1]
        empty = {"resume_medis": {}, "hasil_laboratorium": {"results": []}, "rincian_tagihan": {"items": []}, "cppt": {"medications": []}}
        if not lines:
            return json.dumps(empty.get(doc_type, {}))
        case = self._find_case(context.get("claim_number"), "\n".join(l["text"] for l in lines))
        if case is None:
            return json.dumps(empty.get(doc_type, {}))
        facts = case_to_facts({**case, "documents": [doc_type]}).get(doc_type, empty.get(doc_type, {}))
        loc = _Locator(lines)
        if doc_type == "resume_medis":
            _locate_resume(facts, loc, case)
        elif doc_type == "hasil_laboratorium":
            _locate_labs(facts, loc, case)
        elif doc_type == "rincian_tagihan":
            _locate_sequential(facts["items"], loc, lambda it: (it["name"], it["time"]))
        elif doc_type == "cppt":
            _locate_cppt(facts["medications"], loc)
        return json.dumps(facts, ensure_ascii=False)
