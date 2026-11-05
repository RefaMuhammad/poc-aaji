"""Evaluasi deteksi fraud (U3) terhadap pola yang ditanam di data sintetis (DATA REKAAN).

Membuat riwayat klaim dengan synthetic.generate_fraud (atau membaca CSV yang sudah ada),
menjalankan analisis fraud, lalu membandingkan sinyal dengan kunci pola:
  - pola tertangkap   : ada sinyal dari aturan yang diharapkan untuk entitas yang ditanam
  - alarm palsu       : sinyal untuk entitas yang tidak ditanam sebagai fraud
Diulang untuk beberapa seed agar terlihat apakah ambang aturan stabil, bukan kebetulan.

Pemakaian:
    python -m evaluation.fraud_eval                 # seed 2026 + 9 seed tambahan
    python -m evaluation.fraud_eval --seeds 2026    # satu seed saja
Hasil: evaluation/reports/deteksi_<versi_aturan_fraud>.md dan .json
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from mab_pipeline.fraud import FraudRuleSet, analyze, load_fraud_rules, normalize_address, record_from_row
from synthetic.generate_fraud import SEED, generate

ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "rules" / "aturan_fraud_demo.yaml"
REPORTS = ROOT / "evaluation" / "reports"


def _key(entity_type: str, key: str) -> str:
    return normalize_address(key) or key if entity_type == "ADDRESS" else key


def evaluate_seed(seed: int, ruleset: FraudRuleSet) -> dict:
    claims, patterns = generate(seed)
    records = [record_from_row({k: str(v) for k, v in asdict(c).items()}) for c in claims]
    report = analyze(records, ruleset)
    planted = {(p.jenis_entitas, _key(p.jenis_entitas, p.kunci_entitas)): p for p in patterns}
    caught = []
    for p in patterns:
        hits = [s for s in report.signals
                if s.entity_type == p.jenis_entitas and s.entity_key == _key(p.jenis_entitas, p.kunci_entitas)]
        expected = [s for s in hits if s.rule_id == p.aturan_diharapkan]
        caught.append({
            "pola_id": p.pola_id, "nama": p.nama, "aturan_diharapkan": p.aturan_diharapkan, "entitas": p.kunci_entitas,
            "tertangkap": bool(expected), "aturan_lain": sorted({s.rule_id for s in hits} - {p.aturan_diharapkan}),
            "bukti": expected[0].message if expected else None,
        })
    false_alarms = [{"aturan": s.rule_id, "entitas": s.entity_label, "pesan": s.message}
                    for s in report.signals if (s.entity_type, s.entity_key) not in planted]
    return {"seed": seed, "klaim": report.record_count, "sinyal": len(report.signals), "pola": caught,
            "tertangkap": sum(c["tertangkap"] for c in caught), "jumlah_pola": len(patterns),
            "alarm_palsu": false_alarms}


def run(seeds: list[int], rules_path: Path = RULES) -> dict:
    rs = load_fraud_rules(rules_path)
    results = [evaluate_seed(s, rs) for s in seeds]
    return {"ruleset_version": rs.version, "seeds": seeds, "hasil": results,
            "ringkasan": {
                "pola_tertangkap": sum(r["tertangkap"] for r in results),
                "pola_total": sum(r["jumlah_pola"] for r in results),
                "alarm_palsu": sum(len(r["alarm_palsu"]) for r in results),
                "sinyal_total": sum(r["sinyal"] for r in results),
            }}


def to_markdown(res: dict) -> str:
    main = res["hasil"][0]
    s = res["ringkasan"]
    lines = [
        f"# Evaluasi deteksi fraud - {res['ruleset_version']}",
        "",
        "> DATA REKAAN UNTUK DEMONSTRASI. Riwayat klaim dibuat `synthetic/generate_fraud.py` dengan pola fraud yang ditanam.",
        "",
        f"Seed utama {main['seed']}: {main['klaim']} klaim, {main['sinyal']} sinyal, "
        f"**{main['tertangkap']} dari {main['jumlah_pola']} pola tertangkap**, **{len(main['alarm_palsu'])} alarm palsu**.",
        "",
        "| Pola | Aturan diharapkan | Entitas | Tertangkap | Bukti (pesan sinyal) |",
        "|---|---|---|---|---|",
    ]
    for c in main["pola"]:
        extra = f" (juga {', '.join(c['aturan_lain'])})" if c["aturan_lain"] else ""
        lines.append(f"| {c['pola_id']} {c['nama']} | {c['aturan_diharapkan']} | {c['entitas']} | "
                     f"{'ya' if c['tertangkap'] else 'TIDAK'}{extra} | {c['bukti'] or '-'} |")
    lines += ["", "## Alarm palsu (seed utama)", ""]
    if main["alarm_palsu"]:
        lines += [f"- {a['aturan']} {a['entitas']}: {a['pesan']}" for a in main["alarm_palsu"]]
    else:
        lines.append("Tidak ada. Populasi normal (keluarga satu alamat/rekening, rujukan satu arah, peserta dengan 2-3 klaim) tidak memicu sinyal.")
    lines += ["", "## Kestabilan ambang (beberapa seed)", "",
              "| Seed | Klaim | Sinyal | Pola tertangkap | Alarm palsu |", "|---|---|---|---|---|"]
    for r in res["hasil"]:
        lines.append(f"| {r['seed']} | {r['klaim']} | {r['sinyal']} | {r['tertangkap']}/{r['jumlah_pola']} | {len(r['alarm_palsu'])} |")
    lines += ["", f"Total: {s['pola_tertangkap']}/{s['pola_total']} pola tertangkap, {s['alarm_palsu']} alarm palsu "
              f"dari {s['sinyal_total']} sinyal.", "",
              "Catatan: pola ditanam dengan efek yang cukup besar (mis. lama rawat +70%). Pada data sungguhan efek "
              "biasanya lebih halus dan populasi lebih beragam, jadi ambang perlu dikalibrasi ulang dan setiap sinyal "
              "tetap ditelaah manusia. Sinyal fraud tidak pernah menolak klaim.", ""]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seeds", type=int, nargs="*", default=[SEED] + list(range(1, 10)))
    args = ap.parse_args()
    res = run(args.seeds)
    REPORTS.mkdir(parents=True, exist_ok=True)
    base = f"deteksi_{res['ruleset_version']}"
    (REPORTS / f"{base}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    (REPORTS / f"{base}.md").write_text(to_markdown(res), encoding="utf-8")
    s = res["ringkasan"]
    print(f"{s['pola_tertangkap']}/{s['pola_total']} pola tertangkap, {s['alarm_palsu']} alarm palsu. Laporan: {REPORTS / base}.md")


if __name__ == "__main__":
    main()
