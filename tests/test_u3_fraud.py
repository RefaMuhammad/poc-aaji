"""Tes U3: aturan fraud, analisis pola (statistik sejawat, graf relasi, urutan klaim), API Fraud Monitor.

Semua data rekaan. Pola fraud ditanam oleh synthetic.generate_fraud.
"""
from __future__ import annotations

import copy
import csv
import datetime as dt
import io
from dataclasses import asdict
from pathlib import Path

import pytest
import yaml
from sqlalchemy import select

from evaluation.fraud_eval import run as run_eval
from mab_api.models import AuditLog, Claim, FraudClaimRecord, Recommendation
from mab_pipeline.fraud import ClaimRecord, analyze, load_fraud_rules, parse_fraud_rules, record_from_row, RowError
from mab_pipeline.ocr.engine import NullOCREngine
from mab_pipeline.rules import RuleValidationError
from mab_pipeline.tasks import process_claim
from synthetic.generate_fraud import HISTORY_COLUMNS, generate
from tests.test_reasoning import _create_and_upload, mock_llm, ruleset  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parents[1]
FRAUD_FILE = ROOT / "rules" / "aturan_fraud_demo.yaml"


@pytest.fixture(scope="module")
def fraud_rules():
    return load_fraud_rules(FRAUD_FILE)


@pytest.fixture(scope="module")
def history():
    claims, patterns = generate()
    return claims, patterns


def _csv(claims) -> bytes:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=HISTORY_COLUMNS)
    w.writeheader()
    for c in claims:
        w.writerow(asdict(c))
    return buf.getvalue().encode()


# ----------------------------------------------------------------------------- aturan dan analisis murni


def test_fraud_rules_load_and_reject_bad_files(fraud_rules):
    assert fraud_rules.version == "fraud-2026.11-demo"
    assert {r.id for r in fraud_rules.rules} == {f"FRD-0{i}" for i in range(1, 10)}
    assert fraud_rules.level(0) is None and fraud_rules.level(30) == "SEDANG" and fraud_rules.level(90) == "TINGGI"

    doc = yaml.safe_load(FRAUD_FILE.read_text(encoding="utf-8"))
    bad = copy.deepcopy(doc)
    bad["aturan"][0]["kondisi"] = "dokter.claims >= 8"           # field entitas lain
    bad["aturan"][1]["entitas"] = "faskes"                        # entitas tidak dikenal
    bad["aturan"][2]["bobot"] = 150                               # bobot di luar 0-100
    bad["aturan"][3]["kondisi"] = "__import__('os')"              # ekspresi tidak aman
    with pytest.raises(RuleValidationError) as exc:
        parse_fraud_rules(bad)
    text = "\n".join(exc.value.errors)
    assert "FRD-01" in text and "FRD-02" in text and "FRD-03" in text and "FRD-04" in text


def test_all_planted_patterns_found_with_evidence_and_no_false_alarms(fraud_rules, history):
    claims, patterns = history
    records = [record_from_row({k: str(v) for k, v in asdict(c).items()}) for c in claims]
    report = analyze(records, fraud_rules)
    got = {(s.rule_id, s.entity_type): s for s in report.signals}
    assert len(report.signals) == len(patterns)
    for p in patterns:
        s = got[(p.aturan_diharapkan, p.jenis_entitas)]
        assert s.claim_numbers, p.pola_id
        ev = s.evidence
        assert ev["claims"], p.pola_id                               # klaim sebagai bukti
        assert ev["graph"]["nodes"], p.pola_id                       # graf relasi untuk Fraud Monitor
        if ev["kind"] == "peer":                                     # angka pembanding sejawat
            cmp_ = ev["comparison"][0]
            assert cmp_["value"] > cmp_["peer"] and cmp_["z"] >= 3
            assert any(d["is_subject"] for d in ev["peer_distribution"])
        else:
            assert ev["relations"], p.pola_id                        # relasi graf / tumpang tindih
    # skor fraud per entitas terpisah dari skor klinis; entitas pola teratas berskor
    top = {(e.entity_type, e.entity_key): e for e in report.entities}
    assert top[("HOSPITAL", "RS Cempaka Rekaan")].score == 40
    assert all(e.level for e in report.entities)


def test_detection_report_is_stable_across_seeds():
    res = run_eval([2026, 3, 7])
    s = res["ringkasan"]
    assert s["pola_tertangkap"] == s["pola_total"] == 24
    assert s["alarm_palsu"] == 0


def test_normal_population_has_no_signals(fraud_rules):
    """Keluarga satu alamat + satu rekening, rujukan satu arah, 2 klaim berjauhan: wajar."""
    base = dt.date(2026, 1, 1)
    recs = []
    for i, name in enumerate(["Sari Wibowo", "Budi Wibowo", "Ayu Wibowo", "Eko Wibowo"]):
        for j in range(2):
            adm = base + dt.timedelta(days=60 * j + i)
            recs.append(ClaimRecord(f"K-{i}-{j}", f"PST-{i}", "RS A", adm, adm + dt.timedelta(days=3), 3_600_000,
                                    icd10="A09", doctor="dr. A", lab_panels=3, member_name=name,
                                    address="Jl. Mawar No. 1", bank_account="REK-1", referral_from="RS B"))
    assert analyze(recs, fraud_rules).signals == []


def test_record_from_row_validates():
    row = {"nomor_klaim": "K1", "id_peserta": "P1", "rumah_sakit": "RS", "tanggal_masuk": "2026-01-05",
           "tanggal_keluar": "2026-01-03", "total_tagihan": "1000"}
    with pytest.raises(RowError, match="sebelum"):
        record_from_row(row)
    with pytest.raises(RowError, match="wajib"):
        record_from_row({**row, "rumah_sakit": ""})
    ok = record_from_row({**row, "tanggal_keluar": "2026-01-08", "jumlah_pemeriksaan_lab": ""})
    assert ok.los_days == 3 and ok.lab_panels is None


# ----------------------------------------------------------------------------- API


def test_fraud_monitor_api_flow(client, login, history, session_factory):
    claims, _ = history
    manager, staff = login("manajer"), login("staf")

    # staf boleh melihat, tidak boleh impor / menjalankan analisis
    assert client.get("/fraud/overview", headers=staff).status_code == 200
    r = client.post("/fraud/records/import", headers=staff, files={"file": ("riwayat.csv", _csv(claims), "text/csv")})
    assert r.status_code == 403

    duplicate = _csv(claims[:1]).split(b"\n", 1)[1]
    broken = b"HIS-X,PST-X,,,,RS X,,,,2026-01-01,2025-12-01,1000,1\n"
    r = client.post("/fraud/records/import", headers=manager,
                    files={"file": ("riwayat.csv", _csv(claims) + duplicate + broken, "text/csv")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == len(claims) and body["status"] == "PARTIAL" and body["run"]["signal_count"] == 8
    assert any("duplikat" in e for e in body["errors"]) and any("sebelum" in e for e in body["errors"])

    ov = client.get("/fraud/overview", headers=staff).json()
    assert ov["record_count"] == len(claims) and ov["signals_open"] == 8 and not ov["stale"]
    assert ov["entities"][0]["score"] >= 40

    signals = client.get("/fraud/signals", headers=staff).json()
    assert len(signals) == 8 and all(s["evidence"] == {} for s in signals)
    ring = next(s for s in signals if s["rule_id"] == "FRD-05")
    detail = client.get(f"/fraud/signals/{ring['id']}", headers=staff).json()
    assert detail["evidence"]["graph"]["nodes"] and len(detail["claim_numbers"]) == detail["claim_count"]

    # telaah: wajar butuh alasan; staf tidak boleh menelaah
    url = f"/fraud/signals/{ring['id']}/review"
    assert client.put(url, headers=staff, json={"status": "CONFIRMED"}).status_code == 403
    assert client.put(url, headers=manager, json={"status": "DISMISSED"}).status_code == 422
    r = client.put(url, headers=manager, json={"status": "CONFIRMED", "notes": "Diteruskan ke tim investigasi"})
    assert r.status_code == 200 and r.json()["review"]["status"] == "CONFIRMED"

    # telaah bertahan setelah analisis ulang
    assert client.post("/fraud/runs", headers=manager).status_code == 200
    again = client.get("/fraud/signals?review_status=CONFIRMED", headers=staff).json()
    assert [s["rule_id"] for s in again] == ["FRD-05"]
    with session_factory() as db:
        actions = set(db.scalars(select(AuditLog.action)))
    assert {"FRAUD_HISTORY_IMPORTED", "FRAUD_ANALYSIS_RUN", "FRAUD_SIGNAL_REVIEWED"} <= actions

    # tenant lain tidak melihat data / sinyal tenant ini
    other = login("staf_b")
    assert client.get("/fraud/overview", headers=other).json()["record_count"] == 0
    assert client.get(f"/fraud/signals/{ring['id']}", headers=other).status_code == 404
    # peran tanpa izin fraud
    assert client.get("/fraud/overview", headers=login("dokter_umum")).status_code == 403


def test_processed_claim_joins_analysis_without_changing_claim(
    client, login, session_factory, storage, mock_llm, ruleset, history,  # noqa: F811
):
    claims, _ = history
    manager = login("manajer")
    # peserta klaim platform = peserta dengan klaim tumpang tindih di riwayat
    claim = _create_and_upload(client, login("staf"), "SYN-GEA-02", member="PST-H-9002")
    process_claim(claim["id"], session_factory=session_factory, storage=storage, llm=mock_llm, ocr=NullOCREngine(),
                  ruleset=ruleset)
    with session_factory() as db:
        rec = db.scalar(select(FraudClaimRecord).where(FraudClaimRecord.claim_id == claim["id"]))
        assert rec.source == "PLATFORM" and rec.doctor_name and rec.lab_panels
        before = db.get(Claim, claim["id"]).status
        rec_before = db.scalar(select(Recommendation).where(Recommendation.claim_id == claim["id"])).risk_score

    card = client.get(f"/fraud/claims/{claim['id']}", headers=manager).json()
    assert card["in_analysis"] and card["score"] == 0 and card["run_at"] is None

    r = client.post("/fraud/records/import", headers=manager, files={"file": ("riwayat.csv", _csv(claims), "text/csv")})
    assert r.status_code == 200
    card = client.get(f"/fraud/claims/{claim['id']}", headers=manager).json()
    assert {s["rule_id"] for s in card["signals"]} >= {"FRD-09"} and card["score"] >= 50 and card["level"]

    with session_factory() as db:   # sinyal fraud tidak mengubah klaim
        assert db.get(Claim, claim["id"]).status == before
        assert db.scalar(select(Recommendation).where(Recommendation.claim_id == claim["id"])).risk_score == rec_before

    # sinyal yang dinilai wajar tidak menambah skor fraud klaim
    sig = next(s for s in card["signals"] if s["rule_id"] == "FRD-09")
    client.put(f"/fraud/signals/{sig['id']}/review", headers=manager, json={"status": "DISMISSED", "notes": "Salah input tanggal"})
    card2 = client.get(f"/fraud/claims/{claim['id']}", headers=manager).json()
    assert card2["score"] == card["score"] - sig["weight"]
