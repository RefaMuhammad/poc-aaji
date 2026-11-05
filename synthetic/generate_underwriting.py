"""Generator kasus underwriting medis sintetis (U7, DATA REKAAN UNTUK DEMONSTRASI).

Per kasus dibuat dokumen pengajuan calon peserta:
  - SPAJ (identitas, produk, uang pertanggungan, premi dasar)
  - kuesioner kesehatan (9 pertanyaan ya/tidak)
  - hasil medical check up (tinggi, berat, tekanan darah, EKG)
  - hasil laboratorium (gula darah, HbA1c, lemak darah, fungsi hati dan ginjal, HBsAg, urin)
  - surat keterangan dokter (bila ada riwayat penyakit; sebagian dipindai)

Kunci jawaban (kelas risiko, keputusan, loading, pengecualian) ditulis per skenario oleh
penyusun kasus, BUKAN dihitung dari mesin aturan, supaya evaluasi benar-benar menguji
pipeline dan aturan. Angka debit/loading mengikuti tabel contoh di
rules/aturan_underwriting_demo.yaml, yang pada pemakaian sungguhan diganti tabel klien.

Pemakaian:
    python -m synthetic.generate_underwriting        # case.json + PDF + kunci jawaban
"""
from __future__ import annotations

import csv
import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from mab_pipeline.underwriting.constants import DOC_TITLES, ECG_TEXT, LAB_TESTS, QUESTIONS
from synthetic.generate_cases import DEFAULT_OUTPUT, FIRST_NAMES_L, FIRST_NAMES_P, LAST_NAMES

UW_OUTPUT = DEFAULT_OUTPUT / "underwriting"
TEMPLATES = Path(__file__).with_name("templates")
LABEL = "Data rekaan untuk demonstrasi"
SEED = 2026_07
START = date(2026, 10, 1)

INSURER = {"name": "Asuransi Sehat Demo (rekaan)", "addr": "Jl. Contoh Raya No. 1, Kota Rekaan", "color": "#0f766e"}
CLINIC = {"name": "Klinik Rekaan Medika", "addr": "Jl. Fiktif No. 9, Kota Rekaan Barat", "color": "#1d4ed8",
          "city": "Kota Rekaan Barat"}
MCU_DOCTORS = ["dr. Bagus Hartono", "dr. Citra Lestiani"]
LAB_DOCTOR = "dr. Nur Fadhilah, Sp.PK"
TREATING_DOCTORS = {
    "hypertension": "dr. Rahmat Hidayat, Sp.PD",
    "diabetes": "dr. Wening Asih, Sp.PD-KEMD",
    "heart_disease": "dr. Teguh Santosa, Sp.JP",
    "cancer_5y": "dr. Puspa Kirana, Sp.B(K)Onk",
}
OCCUPATIONS = ["Karyawan swasta", "Guru", "Wiraswasta", "Pegawai negeri", "Perawat", "Akuntan", "Pedagang",
               "Insinyur sipil", "Desainer grafis", "Apoteker"]
CITIES = ["Kota Rekaan Barat", "Kabupaten Contoh", "Kota Fiktif Timur"]
AGENTS = ["Agen Rekaan 0107", "Agen Rekaan 0215", "Agen Rekaan 0342"]
PRODUCT = "Sehat Prima Rawat Inap (rekaan)"
MONTHS = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober",
          "November", "Desember"]

LETTERS = {
    "hypertension": ("Hipertensi esensial (I10)", "Amlodipin 5 mg 1x sehari"),
    "diabetes": ("Diabetes melitus tipe 2 (E11)", "Metformin 500 mg 2x sehari"),
    "heart_disease": ("Penyakit jantung koroner stabil (I25.1)", "Aspirin 80 mg, bisoprolol 2,5 mg 1x sehari"),
    "cancer_5y": ("Karsinoma payudara kiri stadium I (C50.9)", "Tamoksifen 20 mg 1x sehari, pascaoperasi 2024"),
}

# -----------------------------------------------------------------------------
# Skenario: (nama, jumlah, isi, kunci jawaban)
# isi: perubahan dari calon peserta sehat. history/letter: riwayat & surat dokter.
# kunci: risk_class, decision, loading_pct, exclusions (kode alasan pengecualian), notes (kode catatan)
# -----------------------------------------------------------------------------
SCENARIOS: list[dict] = [
    {"name": "sehat", "count": 8, "desc": "Sehat, semua pemeriksaan normal",
     "expect": ("STANDARD", "ACCEPT_STANDARD", 0)},
    {"name": "perokok", "count": 2, "desc": "Perokok, pemeriksaan lain normal", "smoker": True,
     "expect": ("SUB1", "ACCEPT_CONDITIONAL", 25)},
    {"name": "obesitas_1", "count": 2, "desc": "IMT 31-33", "bmi": (31.0, 33.5),
     "expect": ("SUB1", "ACCEPT_CONDITIONAL", 25)},
    {"name": "obesitas_2", "count": 1, "desc": "IMT 36-37", "bmi": (36.0, 37.5),
     "expect": ("SUB2", "ACCEPT_CONDITIONAL", 50)},
    {"name": "ht_terkontrol", "count": 2, "desc": "Hipertensi dengan obat, tekanan darah terkontrol, ada surat dokter",
     "history": ["hypertension"], "letter": True, "bp": ((126, 136), (80, 86)),
     "expect": ("SUB1", "ACCEPT_CONDITIONAL", 25)},
    {"name": "ht_derajat1", "count": 1, "desc": "Tekanan darah 140-159 saat MCU, tidak diungkap",
     "bp": ((146, 154), (90, 96)), "expect": ("SUB1", "ACCEPT_CONDITIONAL", 25)},
    {"name": "ht_derajat2", "count": 1, "desc": "Tekanan darah 160-179 saat MCU",
     "bp": ((164, 172), (100, 106)), "expect": ("SUB2", "ACCEPT_CONDITIONAL", 50)},
    {"name": "ht_krisis", "count": 1, "desc": "Tekanan darah >= 180/110 saat MCU",
     "bp": ((184, 192), (112, 118)), "expect": ("POSTPONE", "POSTPONE", 0)},
    {"name": "dm_terkontrol", "count": 2, "desc": "Diabetes dengan obat, HbA1c 6,6-7,6, ada surat dokter",
     "history": ["diabetes"], "letter": True, "lab": {"hba1c": (6.6, 7.6), "fasting_glucose": (118, 138)},
     "expect": ("SUB2", "ACCEPT_CONDITIONAL", 50)},
    {"name": "dm_tidak_diungkap", "count": 1, "desc": "HbA1c 8,4-9,2 tetapi kuesioner menjawab tidak diabetes",
     "lab": {"hba1c": (8.4, 9.2), "fasting_glucose": (160, 178)},
     "expect": ("SUB3", "ACCEPT_CONDITIONAL", 100), "notes": ["NONDISCLOSURE_SUSPECT"]},
    {"name": "dm_tidak_terkontrol", "count": 1, "desc": "Diabetes, HbA1c >= 10",
     "history": ["diabetes"], "letter": True, "uncontrolled": True,
     "lab": {"hba1c": (10.4, 11.2), "fasting_glucose": (230, 260)}, "expect": ("DECLINE", "DECLINE", 0)},
    {"name": "kombinasi_sub4", "count": 1, "desc": "IMT 36 + diabetes terkontrol + perokok (debit 125)",
     "bmi": (36.0, 37.0), "smoker": True, "history": ["diabetes"], "letter": True,
     "lab": {"hba1c": (6.8, 7.4), "fasting_glucose": (120, 134)}, "expect": ("SUB4", "ACCEPT_CONDITIONAL", 125)},
    {"name": "kombinasi_tolak", "count": 1, "desc": "IMT >= 40 + HbA1c 8-9,9 (debit 200 > batas)",
     "bmi": (40.5, 42.0), "history": ["diabetes"], "letter": True,
     "lab": {"hba1c": (8.5, 9.4), "fasting_glucose": (165, 185)}, "expect": ("DECLINE", "DECLINE", 0)},
    {"name": "asma", "count": 1, "desc": "Asma terkontrol (pengecualian tanpa debit)", "history": ["asthma"],
     "detail": {"asthma": "Asma sejak kecil, inhaler bila perlu"},
     "expect": ("STANDARD", "ACCEPT_CONDITIONAL", 0), "exclusions": ["ASTHMA_EXCLUSION"]},
    {"name": "hepatitis_b", "count": 1, "desc": "HBsAg reaktif, pembawa hepatitis B", "history": ["liver_disease"],
     "detail": {"liver_disease": "Pembawa hepatitis B"}, "lab": {"hbsag": "pos"},
     "expect": ("SUB1", "ACCEPT_CONDITIONAL", 25), "exclusions": ["HBSAG_POSITIVE"]},
    {"name": "sgpt_tinggi", "count": 1, "desc": "SGPT > 3x batas atas", "lab": {"sgpt": (150, 175), "sgot": (90, 110)},
     "expect": ("POSTPONE", "POSTPONE", 0)},
    {"name": "kanker_5th", "count": 1, "desc": "Kanker payudara 2 tahun lalu", "sex": "P", "history": ["cancer_5y"],
     "letter": True, "detail": {"cancer_5y": "Ca mammae, operasi 2024"}, "expect": ("POSTPONE", "POSTPONE", 0)},
    {"name": "hamil", "count": 1, "desc": "Sedang hamil 20 minggu", "sex": "P", "history": ["pregnant"],
     "detail": {"pregnant": "Hamil 20 minggu"}, "age": (26, 34), "expect": ("POSTPONE", "POSTPONE", 0)},
    {"name": "menunggu_operasi", "count": 1, "desc": "Menunggu operasi batu empedu", "history": ["pending_treatment"],
     "detail": {"pending_treatment": "Jadwal operasi batu empedu"}, "expect": ("POSTPONE", "POSTPONE", 0)},
    {"name": "ginjal_berat", "count": 1, "desc": "Kreatinin > 2,0 dan proteinuria",
     "lab": {"creatinine": (2.4, 2.9), "urine_protein": "+2"}, "expect": ("DECLINE", "DECLINE", 0)},
    {"name": "kolesterol_perokok", "count": 1, "desc": "Kolesterol tinggi + perokok", "smoker": True,
     "lab": {"total_cholesterol": (286, 305), "ldl": (195, 215)}, "expect": ("SUB2", "ACCEPT_CONDITIONAL", 50)},
    {"name": "ekg_iskemia", "count": 1, "desc": "EKG berkesan iskemia saat MCU", "ecg": "iskemia", "age": (48, 58),
     "expect": ("POSTPONE", "POSTPONE", 0)},
    {"name": "pjk_stabil", "count": 1, "desc": "PJK stabil dengan obat, ada surat dokter", "history": ["heart_disease"],
     "letter": True, "age": (50, 60), "ecg": "abnormal_ringan", "expect": ("SUB3", "ACCEPT_CONDITIONAL", 100)},
    {"name": "ht_tanpa_surat", "count": 1, "desc": "Hipertensi terkontrol, surat dokter tidak dilampirkan",
     "history": ["hypertension"], "detail": {"hypertension": "Minum amlodipin"}, "bp": ((128, 134), (80, 86)),
     "expect": ("SUB1", "ACCEPT_CONDITIONAL", 25), "notes": ["DOCTOR_LETTER_MISSING"]},
]

HEALTHY_LAB = {"fasting_glucose": (80, 97), "hba1c": (4.8, 5.6), "total_cholesterol": (160, 225), "ldl": (90, 140),
               "hdl": (42, 62), "triglycerides": (80, 145), "sgot": (15, 32), "sgpt": (12, 38),
               "creatinine": (0.7, 1.1), "hbsag": "neg", "urine_protein": "neg"}
ONE_DECIMAL = {"hba1c", "creatinine"}


def _num(n: int | float) -> str:
    return f"{int(n):,}".replace(",", ".")


def _dec(x: float) -> str:
    return f"{x:.1f}".replace(".", ",")


def _fmt_date(iso: str) -> str:
    return date.fromisoformat(iso).strftime("%d/%m/%Y")


def _age(birth: date, on: date) -> int:
    return on.year - birth.year - ((on.month, on.day) < (birth.month, birth.day))


def _premium(age: int, sum_assured: int) -> int:
    """Premi dasar contoh (bukan tarif sungguhan): per Rp1 juta UP per tahun, naik per kelompok usia."""
    rate = 9_000 if age < 30 else 12_000 if age < 40 else 17_000 if age < 50 else 26_000
    return sum_assured // 1_000_000 * rate


def _pick(rng: random.Random, spec, decimals: bool):
    if isinstance(spec, tuple):
        lo, hi = spec
        if decimals or isinstance(lo, float):
            return round(rng.uniform(lo, hi), 1)
        return rng.randint(lo, hi)
    return spec


def build_case(sc: dict, index: int, rng: random.Random) -> dict:
    sex = sc.get("sex") or rng.choice("LP")
    first = rng.choice(FIRST_NAMES_L if sex == "L" else FIRST_NAMES_P)
    name = f"{first} {rng.choice(LAST_NAMES)}"
    spaj_date = START + timedelta(days=index)
    lo, hi = sc.get("age", (24, 56))
    age = rng.randint(lo, hi)
    birth = date(spaj_date.year - age, rng.randint(1, 12), rng.randint(1, 28))
    age = _age(birth, spaj_date)
    sum_assured = rng.choice([200, 300, 500, 750, 1000]) * 1_000_000

    height = rng.randint(165, 180) if sex == "L" else rng.randint(150, 166)
    bmi_target = rng.uniform(*sc["bmi"]) if "bmi" in sc else rng.uniform(19.5, 24.5)
    weight = round(bmi_target * (height / 100) ** 2)
    (s_lo, s_hi), (d_lo, d_hi) = sc.get("bp", ((108, 128), (68, 82)))
    lab = {k: _pick(rng, v, k in ONE_DECIMAL) for k, v in HEALTHY_LAB.items()}
    lab.update({k: _pick(rng, v, k in ONE_DECIMAL) for k, v in sc.get("lab", {}).items()})
    if "sgot" not in sc.get("lab", {}):
        lab["sgot"] = min(lab["sgot"], lab["sgpt"] + 20)

    history = set(sc.get("history", []))
    smoker = bool(sc.get("smoker"))
    details = dict(sc.get("detail", {}))
    for cond in history:
        details.setdefault(cond, {"hypertension": "Minum obat rutin", "diabetes": "Minum obat rutin",
                                  "heart_disease": "Kontrol rutin ke Sp.JP"}.get(cond, "Ya"))
    if smoker:
        details["smoker"] = f"{rng.choice([6, 10, 12, 16])} batang/hari"
    answers = [{"code": code, "field": field, "text": text, "answer": field in history or (field == "smoker" and smoker),
                "detail": details.get(field) if (field in history or (field == "smoker" and smoker)) else None}
               for code, field, text in QUESTIONS]

    number = f"SPAJ-2026-{index + 1:04d}"
    case = {
        "case_id": f"UW-{index + 1:02d}",
        "label": LABEL,
        "scenario": sc["name"],
        "scenario_desc": sc["desc"],
        "spaj_number": number,
        "spaj_date": spaj_date.isoformat(),
        "agent": rng.choice(AGENTS),
        "applicant": {"name": name, "sex": sex, "birth_date": birth.isoformat(), "age": age,
                      "occupation": rng.choice(OCCUPATIONS), "city": rng.choice(CITIES)},
        "product": {"name": PRODUCT, "sum_assured": sum_assured, "base_premium": _premium(age, sum_assured)},
        "questionnaire": answers,
        "mcu": {"date": (spaj_date + timedelta(days=rng.randint(2, 6))).isoformat(), "height_cm": height,
                "weight_kg": weight, "systolic": rng.randint(s_lo, s_hi), "diastolic": rng.randint(d_lo, d_hi),
                "pulse": rng.randint(64, 88), "ecg": sc.get("ecg", "normal"), "doctor": rng.choice(MCU_DOCTORS),
                "lab_doctor": LAB_DOCTOR, "clinic_city": CLINIC["city"]},
        "lab": lab,
        "documents": ["spaj", "kuesioner_kesehatan", "hasil_mcu", "hasil_lab_uw"],
        "scanned_documents": [],
    }
    letter_for = next((c for c in ("heart_disease", "cancer_5y", "diabetes", "hypertension") if c in history), None)
    if sc.get("letter") and letter_for:
        diagnosis, treatment = LETTERS[letter_for]
        controlled = not sc.get("uncontrolled")
        case["letter"] = {
            "condition": letter_for, "diagnosis": diagnosis, "treatment": treatment,
            "since_year": spaj_date.year - (2 if letter_for == "cancer_5y" else rng.randint(3, 9)),
            "controlled": controlled,
            "condition_text": "Terkontrol baik dengan pengobatan" if controlled
            else "Belum terkontrol, gula darah masih tinggi meski sudah berobat",
            "doctor": TREATING_DOCTORS[letter_for],
            "date": (spaj_date - timedelta(days=rng.randint(5, 40))).isoformat(),
        }
        case["documents"].append("surat_dokter")
        if index % 2 == 0:
            case["scanned_documents"].append("surat_dokter")  # surat dokter sering diserahkan sebagai pindaian

    if index % 5 == 2:
        case["scanned_documents"].append("hasil_mcu")  # sebagian hasil MCU juga hanya ada sebagai pindaian
    risk_class, decision, loading = sc["expect"]
    case["expected"] = {"risk_class": risk_class, "decision": decision, "loading_pct": loading,
                        "exclusions": sorted(sc.get("exclusions", [])), "notes": sorted(sc.get("notes", []))}
    return case


def generate_all() -> list[dict]:
    rng = random.Random(SEED)
    cases, index = [], 0
    for sc in SCENARIOS:
        for _ in range(sc["count"]):
            cases.append(build_case(sc, index, rng))
            index += 1
    return cases


# ----------------------------------------------------------------------------- render


def lab_rows(case: dict) -> list[dict]:
    lab = case["lab"]
    rows = []
    for code, label, unit, ref in LAB_TESTS:
        v = lab[code]
        if code == "hbsag":
            text = "Reaktif" if v == "pos" else "Non-reaktif"
        elif code == "urine_protein":
            text = "Negatif" if v == "neg" else f"Positif ({v})"
        elif code in ONE_DECIMAL:
            text = _dec(v)
        else:
            text = str(v)
        rows.append({"code": code, "label": label, "text": text, "unit": unit, "ref": ref})
    return rows


def render_html(case: dict, doc_type: str) -> str:
    env = Environment(loader=FileSystemLoader(TEMPLATES), undefined=StrictUndefined, autoescape=True)
    template = {"spaj": "spaj.html", "kuesioner_kesehatan": "kuesioner.html", "hasil_mcu": "mcu.html",
                "hasil_lab_uw": "lab.html", "surat_dokter": "surat_dokter.html"}[doc_type]
    org = CLINIC if doc_type in ("hasil_mcu", "hasil_lab_uw") else INSURER
    if doc_type == "surat_dokter":
        org = {"name": f"Praktik {case['letter']['doctor']}", "addr": "Jl. Rekaan No. 3", "color": "#7c3aed"}
    return env.get_template(f"uw/{template}").render(
        case=case, title=DOC_TITLES[doc_type], org=org["name"], org_addr=org["addr"], color=org["color"],
        fmt=_fmt_date, num=_num, questions=case["questionnaire"], lab_rows=lab_rows(case),
        ecg_text=ECG_TEXT[case["mcu"]["ecg"]],
    )


def render_case(case: dict, case_dir: Path) -> None:
    from weasyprint import HTML  # impor lambat: butuh pustaka sistem (pango)

    from synthetic.scan_effects import scan_pdf

    for doc_type in case["documents"]:
        out = case_dir / f"{doc_type}.pdf"
        out.write_bytes(HTML(string=render_html(case, doc_type), base_url=str(TEMPLATES)).write_pdf())
        if doc_type in case["scanned_documents"]:
            scan_pdf(out, random.Random(f"scan-{case['case_id']}-{doc_type}"))


def answer_key_rows(cases: list[dict]) -> list[dict]:
    return [{"case_id": c["case_id"], "spaj_number": c["spaj_number"], "skenario": c["scenario"],
             "keterangan": c["scenario_desc"], "kelas_risiko": c["expected"]["risk_class"],
             "keputusan": c["expected"]["decision"], "loading_pct": c["expected"]["loading_pct"],
             "pengecualian": " ".join(c["expected"]["exclusions"]), "catatan": " ".join(c["expected"]["notes"]),
             "dokumen": " ".join(c["documents"]), "dipindai": " ".join(c["scanned_documents"])} for c in cases]


def write_outputs(out_dir: Path = UW_OUTPUT, render: bool = True) -> list[dict]:
    cases = generate_all()
    out_dir.mkdir(parents=True, exist_ok=True)
    for case in cases:
        d = out_dir / case["case_id"]
        d.mkdir(exist_ok=True)
        (d / "case.json").write_text(json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8")
        (d / "ground_truth.json").write_text(json.dumps(case["expected"], indent=2), encoding="utf-8")
        if render:
            render_case(case, d)
    rows = answer_key_rows(cases)
    with (out_dir / "kunci_jawaban_underwriting.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"{len(cases)} kasus underwriting sintetis ditulis ke {out_dir}")
    return cases


if __name__ == "__main__":
    write_outputs(Path(sys.argv[1]) if len(sys.argv) > 1 else UW_OUTPUT)
