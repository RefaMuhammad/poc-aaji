"""Generator isi klaim sintetis (DATA REKAAN UNTUK DEMONSTRASI).

Dari synthetic/scenarios.yaml dibangun, per klaim:
  - identitas pasien, RS, dokter, tanggal (semuanya fiktif)
  - hasil lab harian (darah lengkap, serologi, Widal, kultur, feses)
  - CPPT harian dengan narasi yang konsisten dengan skenario
  - resume medis
  - rincian tagihan (kamar, visite, lab, obat, tindakan)
Lalu ground truth dihitung DARI DOKUMEN tersebut (field dokumen/hitung) dan
dari kebenaran klinis skenario (field ai).

Pemakaian:
    python -m synthetic.generate_cases            # tulis case.json, ground_truth.json, kunci_jawaban.csv
"""
from __future__ import annotations

import csv
import json
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS_FILE = Path(__file__).with_name("scenarios.yaml")
DEFAULT_OUTPUT = ROOT / "data" / "synthetic_output"

REQUIRED_DOCS = ("resume_medis", "rincian_tagihan", "hasil_laboratorium")
ALL_DOCS = ("resume_medis", "hasil_laboratorium", "cppt", "rincian_tagihan")

DX_NAMES = {
    "A90": "Demam dengue",
    "A91": "Demam berdarah dengue",
    "A01.0": "Demam tifoid",
    "A09": "Diare dan gastroenteritis yang diduga infeksi",
    "A08.4": "Infeksi usus akibat virus",
    "A04.9": "Infeksi usus akibat bakteri",
    "K52.9": "Gastroenteritis dan kolitis non-infeksi",
    "K92.2": "Perdarahan saluran cerna",
    "K75.9": "Penyakit hati inflamasi (hepatitis tifosa)",
}

# Rumah sakit fiktif dengan format dokumen yang berbeda-beda
HOSPITALS = [
    {
        "key": "rs_a",
        "name": "RS Sehat Sentosa",
        "city": "Kota Rekaan Barat",
        "style": "a",
        "date_format": "%d/%m/%Y",
        "labels": {"plt": "Trombosit", "hct": "Hematokrit", "hb": "Hemoglobin", "wbc": "Leukosit"},
    },
    {
        "key": "rs_b",
        "name": "RSU Harapan Bunda",
        "city": "Kabupaten Contoh",
        "style": "b",
        "date_format": "%d-%m-%Y",
        "labels": {"plt": "PLT", "hct": "HCT", "hb": "HGB", "wbc": "WBC"},
    },
    {
        "key": "rs_c",
        "name": "RS Mitra Medika Nusantara",
        "city": "Kota Fiktif Timur",
        "style": "c",
        "date_format": "indo",
        "labels": {"plt": "Trombosit (PLT)", "hct": "Hematokrit (HCT)", "hb": "Hemoglobin (Hb)", "wbc": "Leukosit (WBC)"},
    },
]

FIRST_NAMES_P = ["Sari", "Dewi", "Rina", "Ayu", "Lestari", "Wulan", "Fitri", "Indah", "Maya", "Nadia"]
FIRST_NAMES_L = ["Budi", "Agus", "Rizki", "Dimas", "Hendra", "Fajar", "Yoga", "Arif", "Bayu", "Eko"]
LAST_NAMES = ["Pratama", "Santoso", "Wibowo", "Saputra", "Hidayat", "Kusuma", "Permana", "Nugroho", "Rahayu", "Setiawan"]
DOCTORS = {
    "dengue": ["dr. Andika Wirawan, Sp.PD", "dr. Ratna Puspita, Sp.A"],
    "tifoid": ["dr. Hasan Basri, Sp.PD", "dr. Melati Anggraini, Sp.A"],
    "gea": ["dr. Yudha Prasetyo, Sp.PD", "dr. Kirana Dewanti, Sp.A"],
}
MONTHS = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember"]

PRICES = {
    "kamar": 450_000,
    "visite": 150_000,
    "darah_lengkap": 95_000,
    "ns1": 350_000,
    "igm": 300_000,
    "widal": 85_000,
    "kultur": 450_000,
    "tes_cepat": 275_000,
    "feses": 70_000,
    "elektrolit": 180_000,
    "infus": 65_000,
    "seftriakson": 120_000,
    "kuinolon": 45_000,
    "antibiotik_gea": 40_000,
    "parasetamol": 8_000,
    "oralit": 5_000,
    "zinc": 6_000,
    "USG Abdomen": 450_000,
    "USG Toraks": 450_000,
    "Konsultasi Gizi": 125_000,
    "Endoskopi": 2_500_000,
    "Transfusi Trombosit": 850_000,
}

WARNING_SIGN_TEXT = {
    "nyeri abdomen": "nyeri perut kanan atas",
    "perdarahan mukosa": "gusi berdarah saat sikat gigi",
    "muntah persisten": "muntah terus-menerus setiap diberi makan/minum",
    "letargi": "pasien tampak letargis",
}

# Kata yang hanya boleh muncul bila ada perembesan plasma (dipakai juga di tes)
PLASMA_LEAKAGE_WORDS = ("efusi pleura", "asites", "hemokonsentrasi")


def dx_group(icd10: str) -> str:
    if icd10 in ("A90", "A91"):
        return "dengue"
    if icd10 == "A01.0":
        return "tifoid"
    return "gea"


@dataclass
class Context:
    rng: random.Random
    scenario: dict[str, Any]
    group: str
    admit: date
    hospital: dict[str, Any]

    @property
    def los(self) -> int:
        return int(self.scenario["lama_rawat"])

    def day(self, n: int) -> date:
        """Hari rawat ke-n (1 = hari masuk)."""
        return self.admit + timedelta(days=n - 1)

    def fmt(self, d: date) -> str:
        if self.hospital["date_format"] == "indo":
            return f"{d.day} {MONTHS[d.month - 1]} {d.year}"
        return d.strftime(self.hospital["date_format"])


# ----------------------------------------------------------------------------- lab


def _cbc(ctx: Context, day: int, time: str, plt: int, hct: float, wbc: float | None = None, hb: float | None = None) -> dict:
    return {
        "type": "darah_lengkap",
        "day": day,
        "date": ctx.day(day).isoformat(),
        "time": time,
        "values": {
            "hb": hb if hb is not None else round(hct / 3, 1),
            "hct": hct,
            "wbc": wbc if wbc is not None else round(ctx.rng.uniform(3.0, 9.5), 1),
            "plt": plt,
        },
    }


def _dengue_labs(ctx: Context) -> list[dict]:
    lab = ctx.scenario.get("lab", {})
    los = ctx.los
    plt_min = int(lab["trombosit_min"])
    rise = float(lab["kenaikan_ht"])
    cbc_max = int(lab.get("cbc_maks_per_hari", 2))
    female = ctx.scenario["pasien"]["jk"] == "P"
    base_hct = 37.0 if female else 41.0
    peak_hct = round(base_hct * (1 + rise / 100), 1)

    nadir_day = min(max(2, los // 2 + 1), los - 1) if los > 2 else 2
    start_plt = max(int(plt_min * 1.7), 150_000)
    plts: dict[int, int] = {}
    for d in range(1, los + 1):
        if d < nadir_day:
            frac = (d - 1) / max(nadir_day - 1, 1)
            plts[d] = int(round((start_plt - (start_plt - plt_min) * frac * 0.8) / 1000) * 1000)
        elif d == nadir_day:
            plts[d] = plt_min
        else:
            plts[d] = plt_min + 25_000 * (d - nadir_day) + ctx.rng.choice([0, 3000, 6000])
    hcts: dict[int, float] = {}
    for d in range(1, los + 1):
        if d == nadir_day:
            hcts[d] = peak_hct
        elif d == los:
            hcts[d] = base_hct
        else:
            hcts[d] = round(base_hct + (peak_hct - base_hct) * ctx.rng.uniform(0.3, 0.8), 1)

    results: list[dict] = []
    times = ["06:00", "12:00", "18:00", "23:00", "03:00"]
    for d in range(1, los + 1):
        n_tests = cbc_max if d == nadir_day else (2 if d == nadir_day - 1 and cbc_max >= 2 else 1)
        for i in range(n_tests):
            if i == 0:
                results.append(_cbc(ctx, d, times[0], plts[d], hcts[d]))
            else:  # pemeriksaan ulang di hari yang sama: trombosit sedikit lebih tinggi, Ht di antara min-maks
                results.append(_cbc(ctx, d, times[i], plts[d] + 2000 * i, round((hcts[d] + base_hct) / 2, 1)))

    results.append({"type": "ns1", "day": 1, "date": ctx.day(1).isoformat(), "time": "07:00", "values": {"result": lab.get("ns1", "pos")}})
    if lab.get("igm"):
        results.append({"type": "igm", "day": 2, "date": ctx.day(2).isoformat(), "time": "07:00", "values": {"result": lab["igm"]}})
    return results


def _typhoid_labs(ctx: Context) -> list[dict]:
    lab = ctx.scenario.get("lab", {})
    results = [_cbc(ctx, 1, "07:00", ctx.rng.choice([168_000, 182_000, 205_000]), 39.5, wbc=round(ctx.rng.uniform(3.2, 5.0), 1))]
    widal_days = [1, min(6, ctx.los)]
    for i, titer in enumerate(lab.get("widal", [])):
        results.append(
            {
                "type": "widal",
                "day": widal_days[i],
                "date": ctx.day(widal_days[i]).isoformat(),
                "time": "08:00",
                "values": {"o": titer, "h": max(80, titer // 2)},
            }
        )
    if lab.get("kultur"):
        results.append({"type": "kultur", "day": 1, "date": ctx.day(1).isoformat(), "time": "08:00", "values": {"result": lab["kultur"]}})
    if lab.get("tes_cepat"):
        results.append({"type": "tes_cepat", "day": 1, "date": ctx.day(1).isoformat(), "time": "09:00", "values": {"result": lab["tes_cepat"], "name": "Tubex TF"}})
    return results


def _gea_labs(ctx: Context) -> list[dict]:
    lab = ctx.scenario.get("lab", {})
    results = [_cbc(ctx, 1, "07:00", ctx.rng.choice([245_000, 278_000, 310_000]), 45.0 if ctx.scenario["pasien"]["jk"] == "L" else 41.0)]
    results.append({"type": "elektrolit", "day": 1, "date": ctx.day(1).isoformat(), "time": "07:00", "values": {"na": 132, "k": 3.2, "cl": 98}})
    results.append(
        {"type": "feses", "day": 1, "date": ctx.day(1).isoformat(), "time": "10:00", "values": {"pathogen": bool(lab.get("patogen_feses", False))}}
    )
    return results


# ----------------------------------------------------------------------------- terapi


def _treatment(ctx: Context) -> dict[str, Any]:
    t = ctx.scenario.get("terapi", {})
    los = ctx.los
    meds: list[dict] = []  # {name, kind, days: [..]}
    if ctx.group == "dengue":
        iv_days = list(range(1, los))  # infus dihentikan sehari sebelum pulang
        meds.append({"name": "Parasetamol 500 mg", "kind": "parasetamol", "days": list(range(1, los + 1))})
    elif ctx.group == "tifoid":
        iv_days = list(range(1, min(los, 4) + 1))
        cef = int(t.get("seftriakson_hari", 5))
        if cef:
            meds.append({"name": "Seftriakson 2 g IV", "kind": "seftriakson", "days": list(range(1, cef + 1))})
        if t.get("kuinolon"):
            meds.append({"name": f"{t['kuinolon']} 500 mg", "kind": "kuinolon", "days": list(range(1, los + 1))})
        meds.append({"name": "Parasetamol 500 mg", "kind": "parasetamol", "days": list(range(1, los + 1))})
    else:
        iv_days = list(range(1, int(t.get("infus_hari", 2)) + 1))
        meds.append({"name": "Oralit", "kind": "oralit", "days": list(range(1, los + 1))})
        meds.append({"name": "Zinc 20 mg", "kind": "zinc", "days": list(range(1, los + 1))})
        if t.get("antibiotik"):
            meds.append({"name": f"{t['antibiotik']} 500 mg" if t["antibiotik"] != "Sefiksim" else "Sefiksim 200 mg", "kind": "antibiotik_gea", "days": list(range(1, los + 1)), "drug": t["antibiotik"]})
    return {"iv_days": iv_days, "meds": meds}


# ----------------------------------------------------------------------------- klinis


def _clinical(ctx: Context) -> dict[str, Any]:
    """Kebenaran klinis (field ber-sumber ai), dengan default per diagnosis."""
    k = dict(ctx.scenario.get("klinis", {}))
    base: dict[str, Any] = {"comorbidities": [], "days_after_discharge_criteria": 0}
    if ctx.group == "dengue":
        base.update(plasma_leakage=False, warning_signs=[], spontaneous_bleeding=False, shock=False, unable_to_drink=False)
    elif ctx.group == "tifoid":
        base.update(complication_documented=bool(ctx.scenario.get("sekunder")) and k.get("complication_documented", False))
    else:
        base.update(
            dehydration="berat", shock=False, persistent_vomiting=False, poor_general_condition=False,
            bloody_diarrhea=False, suspected_cholera=False, daldiyono_score=None,
        )
    base.update(k)
    return base


def _vital(ctx: Context, clin: dict, day: int) -> str:
    if clin.get("shock") and day == 1:
        return "TD 80/60 mmHg, nadi 124x/menit lemah, akral dingin, CRT > 2 detik"
    temp = 38.6 if day <= 2 else 36.8
    return f"TD 110/70 mmHg, nadi 96x/menit, suhu {temp} C"


def _cppt(ctx: Context, clin: dict, labs: list[dict], tx: dict) -> list[dict]:
    los = ctx.los
    after = int(clin.get("days_after_discharge_criteria") or 0)
    discharge_ready_day = los - after
    notes: list[dict] = []
    extra_procs = ctx.scenario.get("tagihan", {}).get("tanpa_catatan", [])

    for d in range(1, los + 1):
        s: list[str] = []
        o: list[str] = [_vital(ctx, clin, d)]
        a: list[str] = []
        p: list[str] = []
        if ctx.group == "dengue":
            if d == 1:
                s.append("Demam tinggi 3 hari, nyeri kepala, nyeri otot")
                for ws in clin["warning_signs"]:
                    s.append(WARNING_SIGN_TEXT[ws])
                if clin.get("unable_to_drink"):
                    s.append("intake oral sulit, tidak mau minum")
                if clin.get("spontaneous_bleeding"):
                    o.append("petekie spontan di ekstremitas, epistaksis")
                if not clin["warning_signs"] and not clin.get("shock"):
                    s.append("tidak ada muntah, tidak ada nyeri perut, masih bisa makan dan minum")
                for c in clin["comorbidities"]:
                    s.append(f"riwayat {c}")
            day_cbc = [r for r in labs if r["type"] == "darah_lengkap" and r["day"] == d]
            if day_cbc:
                v = day_cbc[0]["values"]
                o.append(f"Lab: Hb {v['hb']}, Ht {v['hct']}%, trombosit {v['plt']:,}".replace(",", "."))
            if clin["plasma_leakage"] and d == 2:
                o.append("USG toraks: efusi pleura kanan minimal; kesan hemokonsentrasi")
            if d < discharge_ready_day:
                a.append(DX_NAMES[ctx.scenario["icd10"]])
                p.append("Infus kristaloid, pantau tanda vital dan darah lengkap")
            elif d == discharge_ready_day:
                a.append("Kondisi membaik")
                p.append("Bebas demam > 48 jam, trombosit cenderung naik, hematokrit stabil tanpa infus. Pasien layak pulang.")
            else:
                a.append("Kondisi baik")
                p.append("Pasien masih dirawat, keadaan umum baik, tidak ada keluhan baru. Observasi.")

        elif ctx.group == "tifoid":
            if d == 1:
                s.append("Demam naik turun 7 hari, terutama sore-malam, mual, nyeri perut, sulit BAB")
                o.append("Lidah kotor, nyeri tekan epigastrium")
            if clin.get("complication_documented") and d == 3:
                s.append("BAB hitam (melena) 2 kali")
                o.append("Hb turun dari 12,1 menjadi 9,4 g/dL; konsultasi penyakit dalam")
            if d < discharge_ready_day:
                a.append("Demam tifoid")
                plan = [m["name"] for m in tx["meds"] if d in m["days"] and m["kind"] in ("seftriakson", "kuinolon")]
                p.append("Terapi: " + (", ".join(plan) if plan else "lanjut obat oral") + "; diet lunak")
            elif d == discharge_ready_day:
                a.append("Kondisi membaik")
                p.append("Bebas demam > 48 jam, nafsu makan baik. Pasien layak pulang.")
            else:
                a.append("Kondisi baik")
                p.append("Pasien masih dirawat, keadaan umum baik, tidak ada keluhan baru. Observasi.")

        else:  # gea
            if d == 1:
                freq = ctx.rng.choice([6, 8, 10])
                desc = "BAB cair berlendir darah" if clin.get("bloody_diarrhea") else "BAB cair"
                s.append(f"{desc} {freq}x/hari sejak 1 hari")
                if clin.get("persistent_vomiting"):
                    s.append("muntah setiap diberi minum")
                else:
                    s.append("mual tanpa muntah, masih bisa minum")
                for c in clin["comorbidities"]:
                    s.append(f"riwayat {c}")
                deh = clin.get("dehydration")
                if deh == "berat":
                    o.append("Mata sangat cekung, turgor kulit kembali sangat lambat, malas minum; kesan dehidrasi berat")
                elif deh == "ringan-sedang":
                    o.append("Mata cekung, haus, turgor kulit kembali lambat; kesan dehidrasi ringan-sedang")
                else:
                    o.append("Mata tidak cekung, turgor baik; tanpa dehidrasi")
                if clin.get("poor_general_condition"):
                    o.append("Keadaan umum lemah")
                if clin.get("daldiyono_score") is not None:
                    o.append(f"Skor Daldiyono: {clin['daldiyono_score']}")
            if d < discharge_ready_day:
                a.append(DX_NAMES[ctx.scenario["icd10"]])
                plan = ["oralit, zinc"]
                if d in tx["iv_days"]:
                    plan.insert(0, "infus RL")
                plan += [m["name"] for m in tx["meds"] if m["kind"] == "antibiotik_gea" and d in m["days"]]
                p.append("Terapi: " + ", ".join(plan))
            elif d == discharge_ready_day:
                a.append("Kondisi membaik")
                p.append("BAB lembek 1-2x/hari, tidak muntah, minum baik. Pasien layak pulang.")
            else:
                a.append("Kondisi baik")
                p.append("Pasien masih dirawat, keadaan umum baik, tidak ada keluhan baru. Observasi.")

        notes.append({"day": d, "date": ctx.day(d).isoformat(), "S": "; ".join(s) or "Tidak ada keluhan baru", "O": "; ".join(o), "A": "; ".join(a), "P": "; ".join(p)})
    # Tindakan di tagihan tanpa catatan klinis sengaja TIDAK disebut di CPPT.
    assert not any(proc in json.dumps(notes, ensure_ascii=False) for proc in extra_procs)
    return notes


# ----------------------------------------------------------------------------- tagihan


def _billing(ctx: Context, labs: list[dict], tx: dict) -> list[dict]:
    items: list[dict] = []

    def add(day: int, time: str, name: str, price_key: str, qty: int = 1) -> None:
        items.append({"date": ctx.day(day).isoformat(), "time": time, "name": name, "qty": qty, "price": PRICES[price_key]})

    for d in range(1, ctx.los + 1):
        add(d, "00:00", "Kamar rawat inap kelas 1", "kamar")
        add(d, "09:00", "Visite dokter spesialis", "visite")
    lab_names = {
        "darah_lengkap": "Pemeriksaan Darah Lengkap", "ns1": "NS1 Antigen Dengue", "igm": "IgM Anti-Dengue",
        "widal": "Tes Widal", "kultur": "Kultur Darah", "tes_cepat": "Tubex TF", "feses": "Feses Rutin",
        "elektrolit": "Elektrolit (Na, K, Cl)",
    }
    for r in labs:
        add(r["day"], r["time"], lab_names[r["type"]], r["type"])
    for d in tx["iv_days"]:
        add(d, "08:00", "Cairan infus Ringer Laktat 500 ml", "infus", qty=3)
    for m in tx["meds"]:
        for d in m["days"]:
            add(d, "08:00", m["name"], m["kind"])
    if ctx.group == "dengue" and ctx.scenario.get("klinis", {}).get("plasma_leakage"):
        add(2, "10:00", "USG Toraks", "USG Toraks")  # tercatat di CPPT hari ke-2
    for proc in ctx.scenario.get("tagihan", {}).get("tanpa_catatan", []):
        add(2, "10:00", proc, proc)
    lab_items = [it for it in items if it["name"] == "Pemeriksaan Darah Lengkap"]
    for i in range(int(ctx.scenario.get("tagihan", {}).get("item_ganda", 0))):
        items.append(dict(lab_items[i]))  # item identik: nama, tanggal, jam sama
    items.sort(key=lambda it: (it["date"], it["time"], it["name"]))
    return items


# ----------------------------------------------------------------------------- resume


def _resume(ctx: Context, clin: dict, labs: list[dict], tx: dict) -> dict:
    s = ctx.scenario
    secondary = [f"{c} {DX_NAMES.get(c, '')}".strip() for c in s.get("sekunder", [])]
    cbcs = [r["values"] for r in labs if r["type"] == "darah_lengkap"]
    findings: list[str] = []
    if cbcs:
        findings.append(f"Trombosit terendah {min(v['plt'] for v in cbcs):,}/uL".replace(",", "."))
    if ctx.group == "dengue":
        if clin["plasma_leakage"]:
            findings.append("efusi pleura kanan minimal pada USG toraks")
        ns1 = next((r for r in labs if r["type"] == "ns1"), None)
        if ns1:
            findings.append(f"NS1 {'positif' if ns1['values']['result'] == 'pos' else 'negatif'}")
    if ctx.group == "tifoid":
        for r in labs:
            if r["type"] == "widal":
                findings.append(f"Widal O 1/{r['values']['o']} (hari ke-{r['day']})")
            if r["type"] == "kultur":
                findings.append("kultur darah: Salmonella typhi " + ("tumbuh" if r["values"]["result"] == "pos" else "tidak tumbuh"))
            if r["type"] == "tes_cepat":
                findings.append(f"Tubex TF {'positif' if r['values']['result'] == 'pos' else 'negatif'}")
    therapy = sorted({m["name"] for m in tx["meds"]})
    if tx["iv_days"]:
        therapy.insert(0, f"infus RL {len(tx['iv_days'])} hari")
    return {
        "chief_complaint": {"dengue": "Demam", "tifoid": "Demam lebih dari 7 hari", "gea": "Diare dan muntah"}[ctx.group],
        "primary_dx": f"{s['icd10']} {DX_NAMES[s['icd10']]}",
        "secondary_dx": secondary,
        "supporting_findings": findings,
        "therapy": therapy,
        "discharge_condition": "Membaik, diizinkan pulang",
    }


# ----------------------------------------------------------------------------- ground truth


def derive_ground_truth(case: dict) -> dict:
    """Hitung nilai field kamus data dari isi dokumen + kebenaran klinis."""
    docs = set(case["documents"])
    labs = case["labs"] if "hasil_laboratorium" in docs else []
    billing = case["billing"] if "rincian_tagihan" in docs else None
    clin = case["clinical"]
    tx = case["treatment"]
    admit = date.fromisoformat(case["admission_date"])
    discharge = date.fromisoformat(case["discharge_date"])

    def lab_result(kind: str) -> str | None:
        r = next((x for x in labs if x["type"] == kind), None)
        return r["values"]["result"] if r else None

    cbcs = [r for r in labs if r["type"] == "darah_lengkap"]
    per_day: dict[str, int] = {}
    for r in cbcs:
        per_day[r["date"]] = per_day.get(r["date"], 0) + 1
    hcts = [r["values"]["hct"] for r in cbcs]
    widals = [r for r in labs if r["type"] == "widal"]
    feses = next((r for r in labs if r["type"] == "feses"), None)

    meds_kinds = {m["kind"] for m in tx["meds"]}
    cef = next((m for m in tx["meds"] if m["kind"] == "seftriakson"), None)
    dup = None
    if billing is not None:
        keys = [(it["name"], it["date"], it["time"]) for it in billing]
        dup = len(keys) - len(set(keys))

    lab_group = {
        "platelet_min": min(r["values"]["plt"] for r in cbcs) if cbcs else None,
        "hct_rise_pct": round((max(hcts) - min(hcts)) / min(hcts) * 100, 1) if hcts else None,
        "dengue_ns1": lab_result("ns1"),
        "dengue_igm": lab_result("igm"),
        "cbc_max_per_day": max(per_day.values()) if per_day else None,
        "widal_tests": len(widals) if labs else None,
        "widal_o_max_titer": max(r["values"]["o"] for r in widals) if widals else None,
        "widal_fourfold_rise": None,
        "blood_culture_typhi": lab_result("kultur"),
        "typhi_rapid": lab_result("tes_cepat"),
        "stool_pathogen": feses["values"]["pathogen"] if feses else None,
    }
    group = case["dx_group"]
    # Field lab yang tidak relevan untuk diagnosis ini dibiarkan None (tidak diperiksa)
    if group != "dengue":
        lab_group["hct_rise_pct"] = None
    if group == "tifoid" and labs:
        lab_group["widal_fourfold_rise"] = len(widals) >= 2 and widals[-1]["values"]["o"] >= 4 * widals[0]["values"]["o"]
    else:
        lab_group["widal_tests"] = None
        lab_group["widal_fourfold_rise"] = None
    if group != "gea":
        lab_group["stool_pathogen"] = None

    return {
        "claim_id": case["claim_id"],
        "claim": {
            "care_type": "inpatient",
            "los_days": (discharge - admit).days,
            "patient_age": case["patient"]["age"],
        },
        "dx": {"primary": case["icd10"], "secondary": list(case["secondary_icd10"])},
        "lab": lab_group,
        "clin": clin,
        "tx": {
            "iv_fluid_days": len(tx["iv_days"]),
            "antibiotic_given": bool(meds_kinds & {"seftriakson", "kuinolon", "antibiotik_gea"}),
            "ceftriaxone_days": len(cef["days"]) if cef else (0 if group == "tifoid" else None),
            "fluoroquinolone_given": "kuinolon" in meds_kinds
            or any(m.get("drug") in ("Siprofloksasin", "Levofloksasin", "Ofloksasin") for m in tx["meds"]),
        },
        "bill": {
            "duplicate_items": dup,
            "items_without_clinical_note": len(case["undocumented_billed_items"]) if billing is not None else None,
        },
        "docs": {"missing": [d for d in REQUIRED_DOCS if d not in docs]},
        "history": {"overlapping_claims": len(case["overlapping_claims"])},
    }


# ----------------------------------------------------------------------------- utama


def _hospital_for(index: int) -> dict:
    return HOSPITALS[index % len(HOSPITALS)]


def build_case(scenario: dict, index: int, seed: int, start: date) -> dict:
    rng = random.Random(f"{seed}-{scenario['claim_id']}")
    group = dx_group(scenario["icd10"])
    # klaim duplikat menyalin tanggal dari klaim riwayat; lainnya tersebar tiap 3 hari
    admit = start + timedelta(days=3 * index)
    ctx = Context(rng=rng, scenario=scenario, group=group, admit=admit, hospital=_hospital_for(index))

    sex = scenario["pasien"]["jk"]
    first = rng.choice(FIRST_NAMES_P if sex == "P" else FIRST_NAMES_L)
    name = f"{first} {rng.choice(LAST_NAMES)}"
    age = int(scenario["pasien"]["usia"])
    doctor = DOCTORS[group][1 if age < 18 else 0]

    labs = {"dengue": _dengue_labs, "tifoid": _typhoid_labs, "gea": _gea_labs}[group](ctx)
    tx = _treatment(ctx)
    clin = _clinical(ctx)
    cppt = _cppt(ctx, clin, labs, tx)
    billing = _billing(ctx, labs, tx)
    resume = _resume(ctx, clin, labs, tx)
    missing = scenario.get("dokumen_tidak_ada", [])
    documents = [d for d in ALL_DOCS if d not in missing]

    case = {
        "claim_id": scenario["claim_id"],
        "label": "DATA REKAAN UNTUK DEMONSTRASI",
        "scenario": {k: v for k, v in scenario.items() if not k.startswith("_")},
        "dx_group": group,
        "icd10": scenario["icd10"],
        "secondary_icd10": scenario.get("sekunder", []),
        "hospital": {k: ctx.hospital[k] for k in ("key", "name", "city", "style", "date_format", "labels")},
        "doctor": doctor,
        "patient": {
            "name": name,
            "sex": sex,
            "age": age,
            "mrn": f"RM-{rng.randint(100000, 999999)}",
            "member_id": f"PST-{rng.randint(10_000_000, 99_999_999)}",
            "policy_no": f"POL-DEMO-{rng.randint(1000, 9999)}",
        },
        "admission_date": ctx.day(1).isoformat(),
        "discharge_date": (ctx.admit + timedelta(days=ctx.los)).isoformat(),
        "documents": documents,
        "labs": labs,
        "treatment": tx,
        "clinical": clin,
        "cppt": cppt,
        "billing": billing,
        "billing_total": sum(it["price"] * it["qty"] for it in billing),
        "resume": resume,
        "undocumented_billed_items": list(scenario.get("tagihan", {}).get("tanpa_catatan", [])),
        "overlapping_claims": list(scenario.get("riwayat", {}).get("klaim_tumpang_tindih", [])),
    }
    return case


def load_scenarios(path: Path = SCENARIOS_FILE) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def generate_all(path: Path = SCENARIOS_FILE) -> tuple[list[dict], list[dict], dict]:
    """Kembalikan (cases, ground_truths, config) tanpa menulis file."""
    cfg = load_scenarios(path)
    start = date.fromisoformat(cfg["tanggal_mulai"])
    seed = int(cfg["seed"])
    cases = [build_case(s, i, seed, start) for i, s in enumerate(cfg["skenario"])]
    scan_rng = random.Random(f"{seed}-scan")
    n_scan = round(len(cases) * float(cfg.get("proporsi_pindaian", 0.4)))
    scanned = set(scan_rng.sample([c["claim_id"] for c in cases], n_scan))
    for c in cases:
        c["scanned"] = c["claim_id"] in scanned
    truths = [derive_ground_truth(c) for c in cases]
    return cases, truths, cfg


def answer_key_rows(cases: list[dict]) -> list[dict]:
    rows = []
    for c in cases:
        s = c["scenario"]
        status = s["harapan"]["status"]
        rec = "PAY_FULL" if status == "GREEN" else ("PEND" if s["kategori"] == "dokumen_tidak_lengkap" else "DOCTOR_REVIEW")
        rows.append(
            {
                "claim_id": c["claim_id"],
                "diagnosis": c["icd10"],
                "kategori": s["kategori"],
                "status_triase_harapan": status,
                "rekomendasi_harapan": rec,
                "aturan_harapan": ";".join(s["harapan"]["aturan"]),
                "pindaian": "ya" if c["scanned"] else "tidak",
                "catatan": s["deskripsi"],
            }
        )
    return rows


def write_outputs(out_dir: Path = DEFAULT_OUTPUT) -> list[dict]:
    cases, truths, _ = generate_all()
    out_dir.mkdir(parents=True, exist_ok=True)
    for c in cases:
        d = out_dir / c["claim_id"]
        d.mkdir(exist_ok=True)
        (d / "case.json").write_text(json.dumps(c, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "ground_truth.json").write_text(json.dumps(truths, ensure_ascii=False, indent=2), encoding="utf-8")
    rows = answer_key_rows(cases)
    with open(out_dir / "kunci_jawaban.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"{len(cases)} klaim ditulis ke {out_dir} ({sum(c['scanned'] for c in cases)} akan dibuat versi pindaian)")
    return cases


if __name__ == "__main__":
    write_outputs()
