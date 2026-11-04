"""Tes M7: antrean dokter, telaah, koreksi field, eskalasi, tanda tangan PIN, rilis ke asuransi."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from mab_api.models import AuditLog, Recommendation, Review, User
from mab_api.security import hash_secret
from mab_pipeline.ocr.engine import NullOCREngine
from mab_pipeline.tasks import process_claim
from tests.test_reasoning import _create_and_upload, mock_llm, ruleset  # noqa: F401  (fixture)

PIN = "246810"


@pytest.fixture
def pins(session_factory, users):
    with session_factory() as db:
        for key in ("dokter_umum", "spesialis"):
            db.get(User, users[key]).pin_hash = hash_secret(PIN)
        db.commit()


@pytest.fixture
def processed(client, login, session_factory, storage, mock_llm, ruleset, pins):  # noqa: F811
    """Unggah dan proses klaim sintetis; kembalikan id klaim."""
    def _run(claim_id: str, member: str) -> str:
        claim = _create_and_upload(client, login("staf"), claim_id, member=member)
        process_claim(claim["id"], session_factory=session_factory, storage=storage, llm=mock_llm,
                      ocr=NullOCREngine(), ruleset=ruleset)
        return claim["id"]
    return _run


def test_queue_routes_red_to_specialist_and_yellow_to_gp(client, login, processed):
    red = processed("SYN-TIF-06", "PST-1")
    yellow = processed("SYN-GEA-07", "PST-2")
    processed("SYN-GEA-02", "PST-3")  # hijau: tidak masuk antrean dokter

    gp = client.get("/review/queue", headers=login("dokter_umum")).json()
    sp = client.get("/review/queue", headers=login("spesialis")).json()
    assert [i["id"] for i in gp] == [yellow] and gp[0]["level"] == "GP"
    assert [i["id"] for i in sp] == [red] and sp[0]["level"] == "SPECIALIST" and sp[0]["specialty"] == "Penyakit Dalam"
    assert sp[0]["diagnosis_name"] == "Demam tifoid" and sp[0]["findings"] == 2
    assert client.get("/review/queue?icd=A09", headers=login("dokter_umum")).json()[0]["id"] == yellow
    assert client.get("/review/queue?icd=A91", headers=login("dokter_umum")).json() == []
    # staf asuransi tidak boleh membuka antrean dokter
    assert client.get("/review/queue", headers=login("staf")).status_code == 403
    # dokter umum tidak boleh mengambil kasus merah
    r = client.post(f"/review/{red}/start", headers=login("dokter_umum"))
    assert r.status_code == 403 and "spesialis" in r.json()["detail"]


def test_specialist_signs_red_case_and_insurer_sees_it(client, login, processed, session_factory):
    claim = processed("SYN-TIF-06", "PST-1")
    sp = login("spesialis")
    ws = client.get(f"/review/{claim}", headers=sp).json()
    assert ws["can_start"] and ws["my_review"] is None and ws["draft"]["state"] == "DRAFT"
    assert ws["suggestion"] == {"recommendation": "PEND", "recommended_amount": None}
    assert ws["fields"] and all("label" in f for f in ws["fields"])
    assert "DX_NOT_SUPPORTED" in ws["reason_codes"]

    # belum mulai telaah: tidak boleh tanda tangan
    assert client.post(f"/review/{claim}/sign", json={"recommendation": "PEND", "pin": PIN}, headers=sp).status_code == 409
    assert client.post(f"/review/{claim}/start", headers=sp).status_code == 201
    # klaim terkunci: dokter umum tidak melihatnya lagi
    assert client.get(f"/review/{claim}", headers=login("dokter_umum")).status_code == 404

    # koreksi field tercatat dengan nilai lama dan baru
    field = next(f for f in ws["fields"] if f["field_path"] == "lab.widal_o_max_titer")
    r = client.patch(f"/review/{claim}/fields/{field['id']}", json={"value": 320, "note": "salah baca"}, headers=sp)
    assert r.status_code == 200 and r.json()["corrected_value"] == 320 and r.json()["value"] == field["value"]
    hist = client.get(f"/review/{claim}", headers=sp).json()["field_history"]
    assert hist[-1]["old"] == field["value"] and hist[-1]["new"] == 320 and hist[-1]["note"] == "salah baca"

    # mengubah draf tanpa kode alasan ditolak; PIN salah ditolak
    body = {"recommendation": "PAY_PARTIAL", "recommended_amount": 1_000_000, "pin": PIN}
    assert client.post(f"/review/{claim}/sign", json=body, headers=sp).status_code == 422
    body["reason_code"] = "DRUG_NOT_INDICATED"
    assert client.post(f"/review/{claim}/sign", json={**body, "pin": "000000"}, headers=sp).status_code == 403
    r = client.post(f"/review/{claim}/sign", json=body, headers=sp)
    assert r.status_code == 200, r.text
    rec = r.json()
    assert rec["state"] == "SIGNED" and rec["recommendation"] == "PAY_PARTIAL" and rec["recommended_amount"] == 1_000_000
    assert rec["reviewer"]["name"] == "Pengguna spesialis" and rec["reviewer"]["specialty"] == "Penyakit Dalam"
    assert [f["rule_id"] for f in rec["findings"]] == ["TIF-01", "TIF-03"]  # temuan & bukti ikut versi baru
    assert "Ini draf dari sistem" not in rec["explanation_text"]
    assert rec["explanation_text"].endswith("Rekomendasi dokter: bayar sebagian, dibayar Rp1.000.000.")

    # asuransi kini bisa melihat dan memutuskan
    staf = login("staf")
    assert client.get(f"/claims/{claim}", headers=staf).json()["status"] == "AWAITING_DECISION"
    seen = client.get(f"/claims/{claim}/recommendation", headers=staf).json()
    assert seen["recommendation"] == "PAY_PARTIAL" and seen["reviewer"] is not None
    assert client.post(f"/claims/{claim}/decision", json={"decision": "AGREE"}, headers=staf).status_code == 201

    with session_factory() as db:
        recs = list(db.scalars(select(Recommendation).where(Recommendation.claim_id == claim).order_by(Recommendation.version)))
        assert [(r.state, r.is_current) for r in recs] == [("DRAFT", False), ("SIGNED", True)]
        review = db.scalar(select(Review).where(Review.claim_id == claim))
        assert review.action == "MODIFY" and review.agrees_with_ai is False and review.reason_code == "DRUG_NOT_INDICATED"
        assert review.finished_at is not None
        actions = [a.action for a in db.scalars(select(AuditLog).where(AuditLog.claim_id == claim))]
        assert {"REVIEW_STARTED", "FIELD_CORRECTED", "SIGN_PIN_FAILED", "RECOMMENDATION_SIGNED"} <= set(actions)

    # sudah ditandatangani: muncul di daftar "selesai" dokter, tidak di antrean
    assert client.get("/review/queue", headers=sp).json() == []
    assert [i["id"] for i in client.get("/review/queue?done=true", headers=sp).json()] == [claim]


def test_gp_approves_draft_or_escalates_to_specialist(client, login, processed, session_factory):
    claim = processed("SYN-GEA-07", "PST-2")
    gp, sp = login("dokter_umum"), login("spesialis")
    ws = client.get(f"/review/{claim}", headers=gp).json()
    assert ws["level"] == "GP" and ws["can_start"]
    assert client.post(f"/review/{claim}/start", headers=gp).status_code == 201

    # eskalasi wajib ada catatan
    assert client.post(f"/review/{claim}/escalate", json={"notes": " "}, headers=gp).status_code == 422
    r = client.post(f"/review/{claim}/escalate", json={"notes": "Perlu pendapat spesialis soal antibiotik"}, headers=gp)
    assert r.status_code == 200 and r.json()["action"] == "ESCALATE" and r.json()["escalated_specialty"] == "Penyakit Dalam"

    # kini masuk antrean spesialis, bukan dokter umum
    assert client.get("/review/queue", headers=gp).json() == []
    item = client.get("/review/queue", headers=sp).json()[0]
    assert item["id"] == claim and item["escalated"] and item["level"] == "SPECIALIST"
    assert client.post(f"/review/{claim}/start", headers=sp).status_code == 201

    # setujui usulan draf apa adanya: tidak perlu kode alasan, tercatat setuju dengan AI
    sugg = client.get(f"/review/{claim}", headers=sp).json()["suggestion"]
    r = client.post(f"/review/{claim}/sign", json={**sugg, "pin": PIN}, headers=sp)
    assert r.status_code == 200, r.text
    with session_factory() as db:
        reviews = list(db.scalars(select(Review).where(Review.claim_id == claim).order_by(Review.started_at)))
        assert [(r.action, r.agrees_with_ai) for r in reviews] == [("ESCALATE", None), ("APPROVE", True)]


def test_release_returns_case_to_queue_and_admin_reads_ruleset(client, login, processed):
    claim = processed("SYN-GEA-07", "PST-2")
    gp = login("dokter_umum")
    client.post(f"/review/{claim}/start", headers=gp)
    assert client.post(f"/review/{claim}/release", headers=gp).status_code == 204
    assert client.get("/review/queue", headers=gp).json()[0]["assigned_to"] is None

    rs = client.get("/admin/ruleset", headers=login("admin")).json()
    assert rs["version"] and {d["id"] for d in rs["diagnoses"]} == {"dengue", "tifoid", "gea"}
    assert all(d["specialty"] == "Penyakit Dalam" for d in rs["diagnoses"])
    assert rs["triage"][-1]["status"] == "GREEN"
    assert client.get("/admin/ruleset", headers=login("staf")).status_code == 403
    assert client.get("/users", headers=login("admin")).status_code == 200
