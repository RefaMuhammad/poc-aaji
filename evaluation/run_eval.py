"""Evaluasi Tahap 0 pada 30 klaim sintetis (DATA REKAAN), satu kali jalan per klaim.

Yang diukur:
- akurasi ekstraksi per field (dokumen + hitung) terhadap ground_truth.json
- kecocokan status triase dan rekomendasi awal terhadap kunci_jawaban.csv
- jumlah klaim bermasalah yang keliru menjadi hijau (target 0)
- temuan yang punya bukti, dan waktu proses per klaim

PENTING untuk membaca angka:
- Semua angka berasal dari data sintetis buatan generator repo ini, bukan data klaim sungguhan.
- Dengan LLM_PROVIDER=mock, "LLM" menjawab dari case.json skenario. Angkanya hanya menguji
  pembacaan dokumen (pdfplumber/OCR), pencocokan bukti, aturan, dan triase, BUKAN kualitas model AI.
  Untuk mengukur model sungguhan, jalankan dengan LLM_PROVIDER=deepseek (atau provider lain).
- Aturan klinis masih draf dan belum divalidasi dokter.

Pemakaian:
    python -m evaluation.run_eval [--data data/synthetic_output] [--claims SYN-DEN-01,...]
Laporan: evaluation/reports/eval_<llm>_<ocr>.md dan .json
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from evaluation.extraction_accuracy import KEY_FIELDS, flatten_truth, same
from mab_pipeline.llm.client import get_llm_client
from mab_pipeline.ocr.engine import get_ocr_engine
from mab_pipeline.pipeline import InputDocument, assess_claim, read_claim
from mab_pipeline.rules import load_rules

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / "data" / "synthetic_output"
REPORT_DIR = ROOT / "evaluation" / "reports"
DEFAULT_RULES = Path(os.getenv("RULES_PATH", ROOT / "rules" / "aturan_klinis_demo.yaml"))


def _pct(ok: int, total: int) -> float | None:
    return round(100 * ok / total, 1) if total else None


def evaluate(data_dir: Path, rules_path: Path, claim_ids: list[str] | None = None) -> dict:
    ruleset = load_rules(rules_path)
    llm, ocr = get_llm_client(), get_ocr_engine()
    key = {r["claim_id"]: r for r in csv.DictReader(open(data_dir / "kunci_jawaban.csv", encoding="utf-8"))}
    truths = {t["claim_id"]: t for t in json.loads((data_dir / "ground_truth.json").read_text(encoding="utf-8"))}

    per_field: dict[str, Counter] = defaultdict(Counter)
    per_mode: dict[str, Counter] = defaultdict(Counter)
    mismatches, rows = [], []
    findings_total = findings_with_evidence = 0

    for claim_id in claim_ids or list(key):
        k = key[claim_id]
        folder = data_dir / claim_id
        case = json.loads((folder / "case.json").read_text(encoding="utf-8"))
        mode = "pindaian" if case.get("scanned") else "digital"
        inputs = [InputDocument(p.name, p.name, "application/pdf", p.read_bytes(), p.stem) for p in sorted(folder.glob("*.pdf"))]
        overlapping = [{"claim_id": c, "quote": f"Klaim {c} (riwayat sintetis)"} for c in case.get("overlapping_claims", [])]

        t0 = time.monotonic()
        read = read_claim(inputs, llm, ocr, claim_id, tuple(ruleset.triage.required_inpatient_docs))
        t_read = time.monotonic() - t0
        assessment = assess_claim(read, ruleset, llm, int(case["billing_total"]), claim_id, overlapping)
        seconds = time.monotonic() - t0
        d = assessment.recommendation

        # ekstraksi
        ok_n = total_n = 0
        for path, exp in flatten_truth(truths[claim_id]).items():
            got = read.derived[path].value if path in read.derived else None
            if exp in (None, []) and got in (None, []):
                continue
            ok = same(path, exp, got)
            for bucket in (per_field[path], per_mode[mode], per_mode["semua"]):
                bucket["total"] += 1
                bucket["benar"] += ok
            ok_n += ok
            total_n += 1
            if not ok:
                mismatches.append({"claim_id": claim_id, "mode": mode, "field": path, "harapan": exp, "hasil": got})

        # bukti temuan
        for f in d.findings:
            findings_total += 1
            findings_with_evidence += any(e.get("doc") and e.get("page") for e in f.evidence) or any(e.get("claim_id") for e in f.evidence)

        rows.append({
            "claim_id": claim_id,
            "mode": mode,
            "kategori": k["kategori"],
            "ekstraksi": f"{ok_n}/{total_n}",
            "status_harapan": k["status_triase_harapan"],
            "status_hasil": d.triage_status,
            "rekomendasi_harapan": k["rekomendasi_harapan"],
            "rekomendasi_hasil": d.recommendation,
            "aturan_harapan": [r for r in k["aturan_harapan"].split(";") if r],
            "aturan_hasil": [f.rule_id for f in d.findings],
            "catatan_kualitas": [q["code"] for q in d.quality_flags],
            "detik_baca": round(t_read, 1),
            "detik_total": round(seconds, 1),
        })
        r = rows[-1]
        print(f"{claim_id} ({mode}): ekstraksi {r['ekstraksi']}, {r['status_hasil']}/{r['rekomendasi_hasil']} "
              f"(harapan {r['status_harapan']}/{r['rekomendasi_harapan']}), {r['detik_total']} dtk")

    n = len(rows)
    status_ok = sum(r["status_hasil"] == r["status_harapan"] for r in rows)
    full_ok = sum(r["status_hasil"] == r["status_harapan"] and r["rekomendasi_hasil"] == r["rekomendasi_harapan"] for r in rows)
    false_green = [r["claim_id"] for r in rows if r["kategori"] != "wajar" and r["status_hasil"] == "GREEN"]
    key_buckets = [per_field[f] for f in KEY_FIELDS if f in per_field]
    times = [r["detik_total"] for r in rows]
    return {
        "label": "DATA REKAAN UNTUK DEMONSTRASI",
        "waktu": datetime.now().isoformat(timespec="seconds"),
        "llm": llm.model_version,
        "llm_mock": llm.model_version.startswith("mock"),
        "ocr": ocr.name,
        "ruleset": ruleset.version,
        "jumlah_klaim": n,
        "ekstraksi": {
            "akurasi_semua_pct": _pct(per_mode["semua"]["benar"], per_mode["semua"]["total"]),
            "akurasi_field_kunci_pct": _pct(sum(b["benar"] for b in key_buckets), sum(b["total"] for b in key_buckets)),
            "per_mode": {m: {**b, "akurasi": _pct(b["benar"], b["total"])} for m, b in per_mode.items()},
            "per_field": {f: {**b, "akurasi": _pct(b["benar"], b["total"])} for f, b in sorted(per_field.items())},
        },
        "triase": {
            "status_sesuai_pct": _pct(status_ok, n),
            "status_dan_rekomendasi_sesuai_pct": _pct(full_ok, n),
            "bermasalah_jadi_hijau": false_green,
            "temuan_dengan_bukti": f"{findings_with_evidence}/{findings_total}",
        },
        "waktu_proses_detik": {
            "rata_rata": round(statistics.mean(times), 1) if times else None,
            "median": round(statistics.median(times), 1) if times else None,
            "maksimum": max(times) if times else None,
        },
        "klaim": rows,
        "selisih_ekstraksi": mismatches,
    }


def to_markdown(r: dict) -> str:
    e, t, w = r["ekstraksi"], r["triase"], r["waktu_proses_detik"]
    caveat = (
        "LLM yang dipakai adalah **mock** yang menjawab dari skenario sintetis. Angka di bawah menguji pembacaan dokumen, "
        "cek bukti, aturan, dan triase, **bukan** kualitas model AI sungguhan."
        if r["llm_mock"]
        else f"LLM: `{r['llm']}` (model sungguhan) pada data sintetis."
    )
    out = [
        "# Laporan evaluasi Tahap 0", "",
        f"> **{r['label']}.** Semua angka berasal dari {r['jumlah_klaim']} klaim sintetis buatan generator repo ini, "
        "bukan data klaim sungguhan. Aturan klinis masih draf dan belum divalidasi dokter.", "",
        f"> {caveat}", "",
        f"Dibuat {r['waktu']} · LLM `{r['llm']}` · OCR `{r['ocr']}` · aturan `{r['ruleset']}`", "",
        "## Ringkasan", "",
        "| Ukuran | Hasil | Target |", "|---|---|---|",
        f"| Akurasi ekstraksi field kunci | {e['akurasi_field_kunci_pct']}% | >= 90% |",
        f"| Akurasi ekstraksi semua field | {e['akurasi_semua_pct']}% | - |",
        f"| Status triase sesuai kunci jawaban | {t['status_sesuai_pct']}% | >= 90% |",
        f"| Status + rekomendasi awal sesuai | {t['status_dan_rekomendasi_sesuai_pct']}% | - |",
        f"| Klaim bermasalah keliru jadi hijau | {len(t['bermasalah_jadi_hijau'])} {t['bermasalah_jadi_hijau'] or ''} | 0 |",
        f"| Temuan dengan bukti yang bisa ditelusuri | {t['temuan_dengan_bukti']} | semua |",
        f"| Waktu proses per klaim (rata-rata / median / maks) | {w['rata_rata']} / {w['median']} / {w['maksimum']} detik | - |",
        "", "## Ekstraksi per mode dokumen", "", "| Mode | Benar | Total | Akurasi |", "|---|---|---|---|",
    ]
    out += [f"| {m} | {b['benar']} | {b['total']} | {b['akurasi']}% |" for m, b in e["per_mode"].items()]
    out += ["", "## Per klaim", "",
            "| Klaim | Mode | Ekstraksi | Harapan | Hasil | Aturan hasil | Catatan kualitas | Detik |", "|---|---|---|---|---|---|---|---|"]
    for k in r["klaim"]:
        mark = "" if k["status_hasil"] == k["status_harapan"] else " ⚠"
        out.append(f"| {k['claim_id']} | {k['mode']} | {k['ekstraksi']} | {k['status_harapan']} / {k['rekomendasi_harapan']} | "
                   f"{k['status_hasil']} / {k['rekomendasi_hasil']}{mark} | {', '.join(k['aturan_hasil']) or '-'} | "
                   f"{', '.join(k['catatan_kualitas']) or '-'} | {k['detik_total']} |")
    out += ["", "## Akurasi per field", "", "| Field | Benar | Total | Akurasi |", "|---|---|---|---|"]
    out += [f"| `{p}` | {b['benar']} | {b['total']} | {b['akurasi']}% |" for p, b in e["per_field"].items()]
    if r["selisih_ekstraksi"]:
        out += ["", "## Selisih ekstraksi", "", "| Klaim | Mode | Field | Harapan | Hasil |", "|---|---|---|---|---|"]
        out += [f"| {m['claim_id']} | {m['mode']} | `{m['field']}` | {m['harapan']} | {m['hasil']} |" for m in r["selisih_ekstraksi"]]
    out += ["", "Waktu proses diukur di mesin yang menjalankan evaluasi (baca dokumen + OCR + LLM + aturan), tanpa antrean."]
    return "\n".join(out) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES)
    parser.add_argument("--claims")
    args = parser.parse_args()
    report = evaluate(args.data, args.rules, args.claims.split(",") if args.claims else None)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"eval_{report['llm'].replace('/', '_')}_{report['ocr']}"
    (REPORT_DIR / f"{stem}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (REPORT_DIR / f"{stem}.md").write_text(to_markdown(report), encoding="utf-8")
    t = report["triase"]
    print(f"\nEkstraksi field kunci: {report['ekstraksi']['akurasi_field_kunci_pct']}% | triase sesuai: {t['status_sesuai_pct']}% | "
          f"bermasalah jadi hijau: {len(t['bermasalah_jadi_hijau'])} | laporan: {REPORT_DIR / stem}.md")


if __name__ == "__main__":
    main()
