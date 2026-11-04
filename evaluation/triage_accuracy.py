"""Ukur hasil M5 pada 30 klaim sintetis (DATA REKAAN) terhadap kunci_jawaban.csv.

Alur lengkap per klaim: baca dokumen -> penalaran klinis + cek bukti -> aturan -> rekomendasi.
Riwayat klaim tumpang tindih diambil dari skenario sintetis (di aplikasi dihitung dari database).

Target M5:
- >= 90% status triase sama dengan kunci jawaban
- 0 klaim bermasalah berstatus hijau
- setiap temuan punya minimal satu bukti yang bisa ditelusuri ke halaman dokumen

Pemakaian:
    python -m evaluation.triage_accuracy [--data data/synthetic_output] [--claims SYN-DEN-01,...]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from mab_pipeline.llm.client import get_llm_client
from mab_pipeline.ocr.engine import get_ocr_engine
from mab_pipeline.pipeline import InputDocument, assess_claim, read_claim
from mab_pipeline.rules import load_rules

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / "data" / "synthetic_output"
REPORT_DIR = ROOT / "evaluation" / "reports"
DEFAULT_RULES = Path(os.getenv("RULES_PATH", ROOT / "rules" / "aturan_klinis_demo.yaml"))


def _same(a, b) -> bool:
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b)  # nama item boleh berbeda istilah; aturan hanya memakai jumlahnya
    return a == b


def evaluate(data_dir: Path, rules_path: Path, claim_ids: list[str] | None = None) -> dict:
    ruleset = load_rules(rules_path)
    llm, ocr = get_llm_client(), get_ocr_engine()
    key = {r["claim_id"]: r for r in csv.DictReader(open(data_dir / "kunci_jawaban.csv", encoding="utf-8"))}
    truths = {t["claim_id"]: t for t in json.loads((data_dir / "ground_truth.json").read_text(encoding="utf-8"))}
    rows, clin = [], defaultdict(lambda: {"benar": 0, "total": 0})
    findings_total = findings_with_doc = 0
    for claim_id in claim_ids or list(key):
        k = key[claim_id]
        folder = data_dir / claim_id
        case = json.loads((folder / "case.json").read_text(encoding="utf-8"))
        inputs = [InputDocument(p.name, p.name, "application/pdf", p.read_bytes(), p.stem) for p in sorted(folder.glob("*.pdf"))]
        overlapping = [{"claim_id": c, "quote": f"Klaim {c} (riwayat sintetis)"} for c in case.get("overlapping_claims", [])]
        started = time.monotonic()
        read = read_claim(inputs, llm, ocr, claim_id, tuple(ruleset.triage.required_inpatient_docs))
        a = assess_claim(read, ruleset, llm, int(case["billing_total"]), claim_id, overlapping)
        d = a.recommendation
        for f in d.findings:
            findings_total += 1
            findings_with_doc += any(e.get("doc") and e.get("page") for e in f.evidence) or any(e.get("claim_id") for e in f.evidence)
        for path, f in a.reasoning.fields.items():
            group, name = path.split(".", 1)
            truth = truths[claim_id].get(group, {}).get(name)
            if truth is None and f.value is None:
                continue
            clin[path]["total"] += 1
            clin[path]["benar"] += _same(truth, f.value)
        expected_rules = [r for r in k["aturan_harapan"].split(";") if r]
        rows.append({
            "claim_id": claim_id,
            "mode": "pindaian" if k["pindaian"] == "ya" else "digital",
            "kategori": k["kategori"],
            "status_harapan": k["status_triase_harapan"],
            "status_hasil": d.triage_status,
            "rekomendasi_harapan": k["rekomendasi_harapan"],
            "rekomendasi_hasil": d.recommendation,
            "aturan_harapan": expected_rules,
            "aturan_hasil": [f.rule_id for f in d.findings],
            "catatan_kualitas": [q["code"] for q in d.quality_flags],
            "detik": round(time.monotonic() - started, 1),
        })
        r = rows[-1]
        print(f"{claim_id}: {r['status_hasil']}/{r['rekomendasi_hasil']} (harapan {r['status_harapan']}/{r['rekomendasi_harapan']}) {r['aturan_hasil']}")

    n = len(rows)
    status_ok = sum(r["status_hasil"] == r["status_harapan"] for r in rows)
    full_ok = sum(r["status_hasil"] == r["status_harapan"] and r["rekomendasi_hasil"] == r["rekomendasi_harapan"] for r in rows)
    rules_ok = sum(r["aturan_hasil"] == r["aturan_harapan"] for r in rows)
    false_green = [r["claim_id"] for r in rows if r["kategori"] != "wajar" and r["status_hasil"] == "GREEN"]
    return {
        "label": "DATA REKAAN UNTUK DEMONSTRASI",
        "waktu": datetime.now().isoformat(timespec="seconds"),
        "llm": llm.model_version, "ocr": ocr.name, "ruleset": ruleset.version,
        "jumlah_klaim": n,
        "status_sesuai_pct": round(100 * status_ok / n, 1) if n else None,
        "status_dan_rekomendasi_sesuai_pct": round(100 * full_ok / n, 1) if n else None,
        "aturan_persis_sama_pct": round(100 * rules_ok / n, 1) if n else None,
        "bermasalah_jadi_hijau": false_green,
        "temuan_dengan_bukti": f"{findings_with_doc}/{findings_total}",
        "akurasi_field_klinis": {p: {**b, "akurasi": round(100 * b["benar"] / b["total"], 1)} for p, b in sorted(clin.items()) if b["total"]},
        "klaim": rows,
    }


def to_markdown(r: dict) -> str:
    out = [
        "# Evaluasi triase dan rekomendasi (M5)", "",
        f"> {r['label']}. Dibuat {r['waktu']}. LLM: `{r['llm']}`, OCR: `{r['ocr']}`, aturan: `{r['ruleset']}`.", "",
        f"- Status triase sesuai kunci: **{r['status_sesuai_pct']}%** (target >= 90%)",
        f"- Status + rekomendasi awal sesuai: {r['status_dan_rekomendasi_sesuai_pct']}%",
        f"- Daftar aturan terpicu persis sama: {r['aturan_persis_sama_pct']}%",
        f"- Klaim bermasalah yang menjadi hijau: **{len(r['bermasalah_jadi_hijau'])}** (target 0) {r['bermasalah_jadi_hijau'] or ''}",
        f"- Temuan dengan bukti yang bisa ditelusuri: **{r['temuan_dengan_bukti']}**", "",
        "## Per klaim", "", "| Klaim | Mode | Harapan | Hasil | Aturan harapan | Aturan hasil | Catatan kualitas |", "|---|---|---|---|---|---|---|",
    ]
    for k in r["klaim"]:
        mark = "" if k["status_hasil"] == k["status_harapan"] else " ⚠"
        out.append(f"| {k['claim_id']} | {k['mode']} | {k['status_harapan']} / {k['rekomendasi_harapan']} | "
                   f"{k['status_hasil']} / {k['rekomendasi_hasil']}{mark} | {', '.join(k['aturan_harapan']) or '-'} | "
                   f"{', '.join(k['aturan_hasil']) or '-'} | {', '.join(k['catatan_kualitas']) or '-'} |")
    out += ["", "## Akurasi field klinis (AI)", "", "| Field | Benar | Total | Akurasi |", "|---|---|---|---|"]
    out += [f"| `{p}` | {b['benar']} | {b['total']} | {b['akurasi']}% |" for p, b in r["akurasi_field_klinis"].items()]
    out += ["", "Field daftar (warning signs, komorbid) dibandingkan dari jumlah itemnya, karena aturan hanya memakai jumlah."]
    return "\n".join(out) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES)
    parser.add_argument("--claims")
    args = parser.parse_args()
    report = evaluate(args.data, args.rules, args.claims.split(",") if args.claims else None)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"triase_{report['llm'].replace('/', '_')}_{report['ocr']}"
    (REPORT_DIR / f"{stem}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (REPORT_DIR / f"{stem}.md").write_text(to_markdown(report), encoding="utf-8")
    print(f"\nStatus sesuai: {report['status_sesuai_pct']}% | bermasalah jadi hijau: {len(report['bermasalah_jadi_hijau'])} | "
          f"temuan berbukti: {report['temuan_dengan_bukti']} | laporan: {REPORT_DIR / stem}.md")


if __name__ == "__main__":
    main()
