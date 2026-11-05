"""Evaluasi underwriting medis (U7) pada kasus sintetis (DATA REKAAN), satu kali jalan per kasus.

Yang diukur, terhadap kunci jawaban yang ditulis per skenario (bukan dihitung dari mesin aturan):
- akurasi kelas risiko (STANDARD, SUB1-SUB4, POSTPONE, DECLINE)
- akurasi rekomendasi (terima standar / terima dengan syarat / tunda / tolak)
- loading premi tepat sama, pengecualian tepat sama, catatan (mis. dugaan jawaban tidak sesuai)
- akurasi ekstraksi field yang dipakai aturan, terhadap isi dokumen (case.json)
- jaminan keselamatan: tidak ada usulan tolak/tunda/bersyarat yang lolos tanpa telaah dokter

PENTING untuk membaca angka:
- Semua angka berasal dari data sintetis buatan generator repo ini, bukan data calon peserta sungguhan.
- Dengan LLM_PROVIDER=mock, "LLM" menjawab dari case.json bila baris yang dicari benar-benar terbaca.
  Angkanya menguji pembacaan dokumen (pdfplumber/OCR), pencocokan bukti, dan aturan, BUKAN kualitas
  model AI. Untuk mengukur model sungguhan, jalankan dengan LLM_PROVIDER=deepseek (atau provider lain).
- Angka debit, kelas risiko, dan loading adalah contoh. Pada pemakaian sungguhan diambil dari tabel klien.

Pemakaian:
    python -m evaluation.underwriting_eval [--data data/synthetic_output/underwriting]
Laporan: evaluation/reports/underwriting_<llm>_<ocr>.md dan .json
"""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

from mab_pipeline.llm.client import get_llm_client
from mab_pipeline.ocr.engine import get_ocr_engine
from mab_pipeline.underwriting.constants import QUESTION_FIELDS
from mab_pipeline.underwriting.pipeline import InputDocument, assess_application, guess_uw_doc_type
from mab_pipeline.underwriting.rules import load_uw_rules

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / "data" / "synthetic_output" / "underwriting"
REPORT_DIR = ROOT / "evaluation" / "reports"
CLASSES = ["STANDARD", "SUB1", "SUB2", "SUB3", "SUB4", "POSTPONE", "DECLINE"]


def _pct(ok: int, total: int) -> float | None:
    return round(100 * ok / total, 1) if total else None


def truth_fields(case: dict) -> dict:
    """Nilai field kamus data menurut isi dokumen (case.json)."""
    m, lab, a = case["mcu"], case["lab"], case["applicant"]
    b, s = date.fromisoformat(a["birth_date"]), date.fromisoformat(case["spaj_date"])
    out = {
        "applicant.age": s.year - b.year - ((s.month, s.day) < (b.month, b.day)),
        "applicant.sex": a["sex"],
        "vital.height_cm": m["height_cm"], "vital.weight_kg": m["weight_kg"],
        "vital.bmi": round(m["weight_kg"] / (m["height_cm"] / 100) ** 2, 1),
        "vital.systolic": m["systolic"], "vital.diastolic": m["diastolic"], "vital.ecg": m["ecg"],
        "doctor.letter": "letter" in case,
    }
    out |= {f"lab.{k}": v for k, v in lab.items() if k not in ("hdl", "triglycerides", "sgot")}
    for q in case["questionnaire"]:
        name = QUESTION_FIELDS[q["code"]]
        out["applicant.smoker" if name == "smoker" else f"history.{name}"] = q["answer"]
    if "letter" in case:
        out["doctor.controlled"] = case["letter"]["controlled"]
    return out


def _same(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return abs(float(a) - float(b)) < 0.051
    return a == b


def evaluate(data_dir: Path) -> dict:
    ruleset = load_uw_rules()
    llm, ocr = get_llm_client(), get_ocr_engine()
    per_field: dict[str, Counter] = defaultdict(Counter)
    confusion: dict[str, Counter] = defaultdict(Counter)
    rows, mismatches = [], []
    unsafe = 0
    for case_dir in sorted(p for p in data_dir.iterdir() if (p / "case.json").exists()):
        case = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
        exp = case["expected"]
        inputs = [InputDocument(p.stem, p.name, "application/pdf", p.read_bytes(), guess_uw_doc_type(p.name))
                  for p in sorted(case_dir.glob("*.pdf"))]
        t0 = time.perf_counter()
        result = assess_application(inputs, llm, ocr, ruleset)
        seconds = time.perf_counter() - t0
        o = result.outcome
        for path, value in truth_fields(case).items():
            got = (result.fields.get(path) or {}).get("value")
            per_field[path]["total"] += 1
            if _same(got, value):
                per_field[path]["ok"] += 1
            else:
                mismatches.append({"case": case["case_id"], "field": path, "expected": value, "got": got})
        exclusions = sorted(e["reason_code"] for e in o.exclusions)
        notes = sorted(f["reason_code"] for f in o.findings if f["note"])
        if o.recommendation != "ACCEPT_STANDARD" and not o.needs_doctor:
            unsafe += 1
        confusion[exp["risk_class"]][o.risk_class] += 1
        rows.append({
            "case": case["case_id"], "scenario": case["scenario"], "scanned": case["scanned_documents"],
            "expected_class": exp["risk_class"], "class": o.risk_class,
            "expected_decision": exp["decision"], "decision": o.recommendation,
            "expected_loading": exp["loading_pct"], "loading": o.loading_pct,
            "expected_exclusions": exp["exclusions"], "exclusions": exclusions,
            "expected_notes": exp["notes"], "notes": notes, "debit": o.debit_total,
            "needs_doctor": o.needs_doctor, "findings": len(o.findings),
            "findings_with_evidence": sum(1 for f in o.findings if f["line_ids"]),
            "seconds": round(seconds, 2),
        })
    n = len(rows)
    count = lambda pred: sum(1 for r in rows if pred(r))  # noqa: E731
    findings = sum(r["findings"] for r in rows)
    field_total = sum(c["total"] for c in per_field.values())
    field_ok = sum(c["ok"] for c in per_field.values())
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "llm": getattr(llm, "model_version", "?"), "ocr": getattr(ocr, "name", type(ocr).__name__),
        "rules_version": ruleset.version, "cases": n,
        "risk_class_accuracy": _pct(count(lambda r: r["class"] == r["expected_class"]), n),
        "decision_accuracy": _pct(count(lambda r: r["decision"] == r["expected_decision"]), n),
        "loading_exact": _pct(count(lambda r: r["loading"] == r["expected_loading"]), n),
        "exclusions_exact": _pct(count(lambda r: r["exclusions"] == r["expected_exclusions"]), n),
        "notes_exact": _pct(count(lambda r: r["notes"] == r["expected_notes"]), n),
        "all_exact": _pct(count(lambda r: (r["class"], r["decision"], r["loading"], r["exclusions"], r["notes"]) ==
                                (r["expected_class"], r["expected_decision"], r["expected_loading"],
                                 r["expected_exclusions"], r["expected_notes"])), n),
        "field_accuracy": _pct(field_ok, field_total),
        "per_field": {k: {"ok": v["ok"], "total": v["total"], "pct": _pct(v["ok"], v["total"])} for k, v in sorted(per_field.items())},
        "non_standard_without_doctor": unsafe,
        "declined_without_doctor": count(lambda r: r["decision"] == "DECLINE" and not r["needs_doctor"]),
        "to_doctor": count(lambda r: r["needs_doctor"]),
        "findings": findings, "findings_with_evidence": sum(r["findings_with_evidence"] for r in rows),
        "seconds_mean": round(sum(r["seconds"] for r in rows) / n, 2) if n else None,
        "confusion": {k: dict(v) for k, v in confusion.items()},
        "rows": rows, "field_mismatches": mismatches,
    }


def to_markdown(r: dict) -> str:
    lines = [
        f"# Evaluasi underwriting medis (U7) · {r['llm']} · OCR {r['ocr']}",
        "",
        "Data rekaan untuk demonstrasi. Angka dari kasus sintetis, bukan data calon peserta sungguhan. "
        "Dengan LLM tiruan (mock), angka ini menguji pembacaan dokumen, bukti, dan aturan, bukan kualitas model AI. "
        "Debit, kelas risiko, dan loading adalah contoh; pada pemakaian sungguhan diambil dari tabel klien.",
        "",
        f"Dibuat {r['generated_at']} · aturan `{r['rules_version']}` · {r['cases']} kasus",
        "",
        "| Ukuran | Hasil |",
        "|---|---|",
        f"| Akurasi kelas risiko | **{r['risk_class_accuracy']}%** |",
        f"| Akurasi rekomendasi (standar/bersyarat/tunda/tolak) | {r['decision_accuracy']}% |",
        f"| Loading premi tepat sama | {r['loading_exact']}% |",
        f"| Pengecualian tepat sama | {r['exclusions_exact']}% |",
        f"| Catatan (dugaan tidak diungkap, surat dokter) tepat sama | {r['notes_exact']}% |",
        f"| Semua komponen tepat sama | {r['all_exact']}% |",
        f"| Akurasi ekstraksi field aturan | {r['field_accuracy']}% |",
        f"| Usulan selain terima standar tanpa telaah dokter | **{r['non_standard_without_doctor']}** (target 0) |",
        f"| Usulan tolak tanpa telaah dokter | **{r['declined_without_doctor']}** (target 0) |",
        f"| Kasus dikirim ke dokter | {r['to_doctor']} dari {r['cases']} |",
        f"| Temuan dengan bukti baris dokumen | {r['findings_with_evidence']} dari {r['findings']} |",
        f"| Rata-rata waktu proses per kasus | {r['seconds_mean']} detik |",
        "",
        "## Matriks kelas risiko (baris = kunci jawaban, kolom = sistem)",
        "",
        "| Kunci \\ Sistem | " + " | ".join(CLASSES) + " |",
        "|---" * (len(CLASSES) + 1) + "|",
    ]
    for exp in CLASSES:
        row = r["confusion"].get(exp, {})
        if row:
            lines.append(f"| {exp} | " + " | ".join(str(row.get(c, "")) for c in CLASSES) + " |")
    lines += ["", "## Per kasus", "",
              "| Kasus | Skenario | Pindaian | Kelas (kunci → sistem) | Rekomendasi (kunci → sistem) | Loading | Debit | Ke dokter |",
              "|---|---|---|---|---|---|---|---|"]
    for x in r["rows"]:
        mark = "" if x["class"] == x["expected_class"] and x["decision"] == x["expected_decision"] else " ⚠"
        lines.append(f"| {x['case']}{mark} | {x['scenario']} | {', '.join(x['scanned']) or '-'} | "
                     f"{x['expected_class']} → {x['class']} | {x['expected_decision']} → {x['decision']} | "
                     f"{x['expected_loading']} → {x['loading']} | {x['debit']} | {'ya' if x['needs_doctor'] else 'tidak'} |")
    lines += ["", "## Akurasi ekstraksi per field", "", "| Field | Benar | % |", "|---|---|---|"]
    for k, v in r["per_field"].items():
        lines.append(f"| `{k}` | {v['ok']}/{v['total']} | {v['pct']} |")
    if r["field_mismatches"]:
        lines += ["", "## Field yang tidak cocok", "", "| Kasus | Field | Kunci | Sistem |", "|---|---|---|---|"]
        for m in r["field_mismatches"][:60]:
            lines.append(f"| {m['case']} | `{m['field']}` | {m['expected']} | {m['got']} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=DEFAULT_DATA)
    args = ap.parse_args()
    if not args.data.exists():
        raise SystemExit(f"{args.data} tidak ada. Jalankan dulu: python -m synthetic.generate_underwriting")
    r = evaluate(args.data)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"underwriting_{r['llm']}_{r['ocr']}".replace("/", "-")
    (REPORT_DIR / f"{stem}.json").write_text(json.dumps(r, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (REPORT_DIR / f"{stem}.md").write_text(to_markdown(r), encoding="utf-8")
    print(to_markdown(r).split("## Matriks")[0])
    print(f"Laporan: {REPORT_DIR / stem}.md")


if __name__ == "__main__":
    main()
