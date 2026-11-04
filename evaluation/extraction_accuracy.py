"""Ukur akurasi ekstraksi pipeline M4 terhadap ground_truth.json (DATA REKAAN).

Untuk setiap klaim di data/synthetic_output, PDF dibaca dengan pipeline lengkap
(ingest -> OCR -> klasifikasi -> ekstraksi LLM -> field turunan), lalu dibandingkan
dengan nilai benar untuk field ber-sumber 'dokumen' dan 'hitung'.

- Field ai (clin.*, bill.items_without_clinical_note) dinilai di M5; history.* dari database.
- Pasangan yang kedua nilainya kosong (null) tidak dihitung.
- Target M4: akurasi field kunci >= 90% dengan LLM sungguhan.

Pemakaian:
    python -m evaluation.extraction_accuracy [--data data/synthetic_output] [--claims SYN-DEN-01,SYN-TIF-02]
Laporan ditulis ke evaluation/reports/.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from mab_pipeline.llm.client import get_llm_client
from mab_pipeline.ocr.engine import get_ocr_engine
from mab_pipeline.pipeline import InputDocument, read_claim

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / "data" / "synthetic_output"
REPORT_DIR = ROOT / "evaluation" / "reports"
EXCLUDED = {"bill.items_without_clinical_note"}
EXCLUDED_GROUPS = {"clin", "history"}
# Field yang dipakai aturan klinis demo untuk keputusan triase
KEY_FIELDS = {
    "claim.los_days", "dx.primary", "dx.secondary", "lab.platelet_min", "lab.hct_rise_pct", "lab.dengue_ns1",
    "lab.dengue_igm", "lab.cbc_max_per_day", "lab.widal_tests", "lab.widal_o_max_titer", "lab.widal_fourfold_rise",
    "lab.blood_culture_typhi", "lab.typhi_rapid", "lab.stool_pathogen", "tx.iv_fluid_days", "tx.antibiotic_given",
    "tx.ceftriaxone_days", "tx.fluoroquinolone_given", "bill.duplicate_items", "docs.missing",
}


def flatten_truth(truth: dict) -> dict[str, Any]:
    out = {}
    for group, values in truth.items():
        if group == "claim_id" or group in EXCLUDED_GROUPS:
            continue
        for name, value in values.items():
            path = f"{group}.{name}"
            if path not in EXCLUDED:
                out[path] = value
    return out


def same(path: str, expected: Any, got: Any) -> bool:
    if isinstance(expected, list) and isinstance(got, list):
        return sorted(map(str, expected)) == sorted(map(str, got))
    if path == "lab.hct_rise_pct" and expected is not None and got is not None:
        return abs(float(expected) - float(got)) <= 0.5
    if isinstance(expected, (int, float)) and isinstance(got, (int, float)) and not isinstance(expected, bool):
        return float(expected) == float(got)
    return expected == got


def evaluate(data_dir: Path, claim_ids: list[str] | None = None) -> dict:
    truths = {t["claim_id"]: t for t in json.loads((data_dir / "ground_truth.json").read_text(encoding="utf-8"))}
    llm, ocr = get_llm_client(), get_ocr_engine()
    per_field: dict[str, dict[str, int]] = defaultdict(lambda: {"benar": 0, "total": 0})
    per_mode: dict[str, dict[str, int]] = defaultdict(lambda: {"benar": 0, "total": 0})
    mismatches, claims = [], []
    for claim_id in claim_ids or sorted(truths):
        folder = data_dir / claim_id
        case = json.loads((folder / "case.json").read_text(encoding="utf-8"))
        mode = "pindaian" if case.get("scanned") else "digital"
        inputs = [
            InputDocument(p.name, p.name, mimetypes.guess_type(p.name)[0] or "application/pdf", p.read_bytes(), p.stem)
            for p in sorted(folder.glob("*.pdf"))
        ]
        started = time.monotonic()
        result = read_claim(inputs, llm, ocr, claim_id)
        expected = flatten_truth(truths[claim_id])
        correct = total = 0
        for path, exp in expected.items():
            got = result.derived[path].value if path in result.derived else None
            if exp in (None, []) and got in (None, []):
                continue
            ok = same(path, exp, got)
            for bucket in (per_field[path], per_mode[mode], per_mode["semua"]):
                bucket["total"] += 1
                bucket["benar"] += ok
            correct += ok
            total += 1
            if not ok:
                mismatches.append({"claim_id": claim_id, "mode": mode, "field": path, "harapan": exp, "hasil": got})
        claims.append({"claim_id": claim_id, "mode": mode, "benar": correct, "total": total,
                       "detik": round(time.monotonic() - started, 1), "peringatan": result.warnings[:10]})
        print(f"{claim_id} ({mode}): {correct}/{total}")

    key = [per_field[f] for f in KEY_FIELDS if f in per_field]
    key_total = sum(b["total"] for b in key)
    return {
        "label": "DATA REKAAN UNTUK DEMONSTRASI",
        "waktu": datetime.now().isoformat(timespec="seconds"),
        "llm": llm.model_version,
        "ocr": ocr.name,
        "akurasi_semua": _pct(per_mode["semua"]),
        "akurasi_field_kunci": round(100 * sum(b["benar"] for b in key) / key_total, 1) if key_total else None,
        "per_mode": {m: {**b, "akurasi": _pct(b)} for m, b in per_mode.items()},
        "per_field": {f: {**b, "akurasi": _pct(b)} for f, b in sorted(per_field.items())},
        "klaim": claims,
        "selisih": mismatches,
    }


def _pct(bucket: dict[str, int]) -> float | None:
    return round(100 * bucket["benar"] / bucket["total"], 1) if bucket["total"] else None


def to_markdown(report: dict) -> str:
    lines = [
        "# Akurasi ekstraksi dokumen (M4)",
        "",
        f"> {report['label']}. Dibuat {report['waktu']}. LLM: `{report['llm']}`, OCR: `{report['ocr']}`.",
        "",
        f"- Akurasi field kunci: **{report['akurasi_field_kunci']}%** (target >= 90% dengan LLM sungguhan)",
        f"- Akurasi semua field dokumen/hitung: **{report['akurasi_semua']}%**",
    ]
    for mode in ("digital", "pindaian"):
        b = report["per_mode"].get(mode)
        if b:
            lines.append(f"- {mode}: {b['benar']}/{b['total']} ({b['akurasi']}%)")
    lines += ["", "## Per field", "", "| Field | Benar | Total | Akurasi |", "|---|---|---|---|"]
    for f, b in report["per_field"].items():
        lines.append(f"| `{f}`{' *' if f in KEY_FIELDS else ''} | {b['benar']} | {b['total']} | {b['akurasi']}% |")
    lines += ["", "\\* field kunci", "", "## Selisih", ""]
    if not report["selisih"]:
        lines.append("Tidak ada.")
    else:
        lines += ["| Klaim | Mode | Field | Harapan | Hasil |", "|---|---|---|---|---|"]
        lines += [f"| {m['claim_id']} | {m['mode']} | `{m['field']}` | {m['harapan']} | {m['hasil']} |" for m in report["selisih"]]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--claims", help="daftar claim_id dipisah koma")
    args = parser.parse_args()
    report = evaluate(args.data, args.claims.split(",") if args.claims else None)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"akurasi_ekstraksi_{report['llm'].replace('/', '_')}_{report['ocr']}"
    (REPORT_DIR / f"{stem}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (REPORT_DIR / f"{stem}.md").write_text(to_markdown(report), encoding="utf-8")
    print(f"\nField kunci: {report['akurasi_field_kunci']}% | semua: {report['akurasi_semua']}% | laporan: {REPORT_DIR / stem}.md")


if __name__ == "__main__":
    main()
