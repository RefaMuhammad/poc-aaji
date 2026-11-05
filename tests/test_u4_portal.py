"""Tes U4: portal faskes & peserta, alur "tunda: minta dokumen", notifikasi, ringkasan TPA.

Skenario utama SYN-TIF-10: rincian tagihan tidak ikut dikirim. Dokter menunda, asuransi meminta
dokumen, faskes mengunggah tagihan, klaim diproses ulang, dokter menelaah lagi, asuransi memutuskan.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from mab_api.models import AuditLog, DocumentRequest, Notification, User
from mab_api.security import hash_secret
from mab_pipeline.ocr.engine import NullOCREngine
from mab_pipeline.tasks import process_claim
from tests.test_reasoning import FIXTURES, _case, mock_llm, ruleset  # noqa: F401  (fixture)

PIN = "246810"
CASE = "SYN-TIF-10"


@pytest.fixture
def pins(session_factory, users):
    with session_factory() as db:
        for key in ("dokter_umum", "spesialis"):
            db.get(User, users[key]).pin_hash = hash_secret(PIN)
        db.commit()


@pytest.fixture
def run(session_factory, storage, mock_llm, ruleset):  # noqa: F811
    def _run(claim_id: str) -> str:
        return process_claim(claim_id, session_factory=session_factory, storage=storage, llm=mock_llm,
                             ocr=NullOCREngine(), ruleset=ruleset)
    return _run


def _pdf(name: str) -> bytes:
    return (FIXTURES / CASE / name).read_bytes()


def _create(client, headers) -> str:
    case = _case(CASE)
    body = {"claim_number": CASE, "policy_number": "POL-DEMO-1", "member_id": "PST-REKAAN-1", "hospital_name": "RS rekaan",
            "admission_date": case["admission_date"], "discharge_date": case["discharge_date"],
            "billed_amount": case["billing_total"]}
    claim = client.post("/claims", json=body, headers=headers).json()
    files = [("files", (f"{t}.pdf", _pdf(f"{t}.pdf"), "application/pdf")) for t in case["documents"]]
    assert client.post(f"/claims/{claim['id']}/documents", files=files, headers=headers).status_code == 201
    return claim["id"]


def _sign(client, headers, claim_id: str, code: str) -> dict:
    assert client.post(f"/review/{claim_id}/start", headers=headers).status_code == 201
    r = client.post(f"/review/{claim_id}/sign", json={"recommendation": code, "pin": PIN}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _inbox(client, headers) -> list[dict]:
    return client.get("/notifications", headers=headers).json()


def test_syn_tif_10_end_to_end(client, login, run, pins, session_factory, users):
    staf, faskes, peserta, gp = login("staf"), login("faskes"), login("peserta"), login("dokter_umum")
    claim_id = _create(client, staf)

    # 1. Diproses: rincian tagihan hilang -> kuning, ke dokter umum
    assert run(claim_id) == "AWAITING_DOCTOR"
    assert client.get(f"/claims/{claim_id}", headers=staf).json()["missing_documents"] == ["rincian_tagihan"]
    ws = client.get(f"/review/{claim_id}", headers=gp).json()
    assert ws["draft"]["triage_status"] == "YELLOW"
    assert "GEN-03" in [f["rule_id"] for f in ws["draft"]["findings"]]
    assert ws["suggestion"]["recommendation"] == "PEND"
    pend = _sign(client, gp, claim_id, "PEND")
    assert pend["state"] == "SIGNED"

    # 2. Asuransi setuju menunda -> permintaan dokumen terbuka, klaim PENDING_DOCUMENTS
    r = client.post(f"/claims/{claim_id}/decision", json={"decision": "AGREE", "message": "Mohon rincian tagihan."},
                    headers=staf)
    assert r.status_code == 201, r.text
    detail = client.get(f"/claims/{claim_id}", headers=staf).json()
    assert detail["status"] == "PENDING_DOCUMENTS"
    req = detail["document_requests"][0]
    assert req["status"] == "OPEN" and req["doc_types"] == ["rincian_tagihan"] and req["outstanding"] == ["rincian_tagihan"]
    assert req["message"] == "Mohon rincian tagihan." and not req["overdue"]
    # tidak bisa diputuskan / diminta ulang selama menunggu
    assert client.post(f"/claims/{claim_id}/decision", json={"decision": "AGREE"}, headers=staf).status_code == 409
    assert client.post(f"/claims/{claim_id}/document-requests", json={}, headers=staf).status_code == 409

    # notifikasi email simulasi ke faskes dan peserta
    note = _inbox(client, faskes)[0]
    assert note["event"] == "claim.documents_requested" and note["delivery"] == "SIMULATED"
    assert "rincian tagihan" in note["body"] and note["email"] == "faskes@uji.test"
    assert _inbox(client, peserta)[0]["event"] == "claim.documents_requested"
    assert client.get("/notifications/unread-count", headers=faskes).json() == {"unread": 1}
    client.post(f"/notifications/{note['id']}/read", headers=faskes)
    assert client.get("/notifications/unread-count", headers=faskes).json() == {"unread": 0}

    # 3. Portal: faskes melihat klaim yang menunggu dokumennya; peserta melihat status awam
    items = client.get("/portal/claims", headers=faskes).json()
    assert [i["id"] for i in items] == [claim_id]
    assert items[0]["status_label"] == "Menunggu dokumen dari Anda" and items[0]["open_request"]["doc_types"] == ["rincian_tagihan"]
    pv = client.get(f"/portal/claims/{claim_id}", headers=peserta).json()
    assert pv["status_label"] == "Menunggu dokumen dari rumah sakit" and pv["outcome"] is None
    assert "ditunda sementara" in pv["explanation"]
    assert "risk_score" not in pv and "findings" not in pv

    # peserta tidak boleh mengunggah; jenis dokumen lain tidak menutup permintaan
    files = [("files", ("tagihan.pdf", _pdf("susulan/rincian_tagihan.pdf"), "application/pdf"))]
    assert client.post(f"/portal/claims/{claim_id}/documents", files=files, headers=peserta).status_code == 403
    r = client.post(f"/portal/claims/{claim_id}/documents", headers=faskes, data={"doc_types": ["resep"]},
                    files=[("files", ("resep.pdf", _pdf("cppt.pdf"), "application/pdf"))])
    assert r.status_code == 201 and r.json()["job_id"] is None and r.json()["status"] == "PENDING_DOCUMENTS"

    # 4. Faskes mengunggah rincian tagihan -> permintaan terpenuhi, klaim masuk antrean proses ulang
    r = client.post(f"/portal/claims/{claim_id}/documents", headers=faskes, files=files,
                    data={"doc_types": ["rincian_tagihan"], "note": "Tagihan terlampir"})
    assert r.status_code == 201, r.text
    assert r.json()["job_id"] and r.json()["status"] == "QUEUED"
    req = client.get(f"/claims/{claim_id}/document-requests", headers=staf).json()[0]
    assert req["status"] == "FULFILLED" and req["fulfilled_by"] == "Pengguna faskes" and req["response_note"] == "Tagihan terlampir"
    assert len(req["document_ids"]) == 2
    events = {n["event"] for n in _inbox(client, staf)}
    assert "claim.documents_received" in events
    assert any(n["event"] == "claim.documents_received" for n in _inbox(client, login("tpa")))

    # 5. Proses ulang: tagihan kini ada, tetapi klaim tetap kembali ke dokter yang menunda
    assert run(claim_id) == "AWAITING_DOCTOR"
    staff_view = client.get(f"/claims/{claim_id}", headers=staf).json()
    assert staff_view["missing_documents"] == [] and staff_view["decision"] is None
    ws = client.get(f"/review/{claim_id}", headers=gp).json()
    assert "GEN-03" not in [f["rule_id"] for f in ws["draft"]["findings"]]
    with session_factory() as db:
        from mab_api.models import Claim

        assert db.get(Claim, claim_id).assigned_doctor_id == users["dokter_umum"]
        audit = db.scalars(select(AuditLog).where(AuditLog.claim_id == claim_id, AuditLog.action == "PIPELINE_COMPLETED")).all()
        assert [a.detail["after_late_documents"] for a in audit] == [False, True]
    final = _sign(client, gp, claim_id, ws["suggestion"]["recommendation"])
    assert final["insurer_decision"] is None

    # 6. Asuransi memutuskan -> selesai; peserta melihat hasil dan penjelasan
    assert client.post(f"/claims/{claim_id}/decision", json={"decision": "AGREE"}, headers=staf).status_code == 201
    assert client.get(f"/claims/{claim_id}", headers=staf).json()["status"] == "COMPLETED"
    pv = client.get(f"/portal/claims/{claim_id}", headers=peserta).json()
    assert pv["status_label"] == "Selesai" and pv["outcome"] and pv["explanation"].startswith("Hasil klaim:")
    assert pv["reviewer"] == "Pengguna dokter_umum"
    titles = [e["title"] for e in pv["timeline"]]
    for t in ("Klaim diterima", "Asuransi meminta dokumen susulan", "Dokumen susulan diterima",
              "Dokumen selesai diperiksa sistem", "Ditelaah dan ditandatangani dokter", "Asuransi mencatat keputusan"):
        assert t in titles, t
    assert titles.index("Asuransi meminta dokumen susulan") < titles.index("Dokumen susulan diterima") \
        < titles.index("Asuransi mencatat keputusan")
    assert _inbox(client, peserta)[0]["event"] == "claim.decision_recorded"


def test_insurer_requests_documents_directly_and_can_cancel(client, login, run, pins, session_factory):
    staf, gp = login("staf"), login("dokter_umum")
    claim_id = _create(client, staf)
    run(claim_id)
    _sign(client, gp, claim_id, "PEND")
    # jenis tidak dikenal ditolak; faskes tidak boleh meminta dokumen
    assert client.post(f"/claims/{claim_id}/document-requests", json={"doc_types": ["foto"]}, headers=staf).status_code == 422
    assert client.post(f"/claims/{claim_id}/document-requests", json={}, headers=login("faskes")).status_code == 403
    r = client.post(f"/claims/{claim_id}/document-requests", json={"doc_types": ["rincian_tagihan", "resep"], "due_days": 3},
                    headers=staf)
    assert r.status_code == 201 and r.json()["doc_types"] == ["rincian_tagihan", "resep"]
    # asuransi sendiri juga bisa mengunggah dokumen susulan; permintaan baru tertutup bila semua jenis ada
    files = [("files", ("rincian_tagihan.pdf", _pdf("susulan/rincian_tagihan.pdf"), "application/pdf"))]
    r = client.post(f"/claims/{claim_id}/documents", files=files, data={"doc_types": ["rincian_tagihan"]}, headers=staf)
    assert r.status_code == 201 and r.json()["job_id"] is None
    assert client.get(f"/claims/{claim_id}/document-requests", headers=staf).json()[0]["outstanding"] == ["resep"]
    r = client.post(f"/claims/{claim_id}/document-requests/cancel", headers=staf)
    assert r.status_code == 200 and r.json()["status"] == "CANCELLED"
    assert client.get(f"/claims/{claim_id}", headers=staf).json()["status"] == "AWAITING_DECISION"
    with session_factory() as db:
        assert db.scalar(select(DocumentRequest)).status == "CANCELLED"
        actions = {a.action for a in db.scalars(select(AuditLog).where(AuditLog.claim_id == claim_id))}
        assert {"DOCUMENTS_REQUESTED", "LATE_DOCUMENTS_UPLOADED", "DOCUMENT_REQUEST_CANCELLED"} <= actions


def test_portal_scope_and_tpa_summary(client, login, run, pins, users, session_factory):
    staf = login("staf")
    claim_id = _create(client, staf)
    run(claim_id)
    # faskes RS lain dan peserta lain tidak melihat klaim ini
    with session_factory() as db:
        db.get(User, users["faskes"]).facility_name = "RS lain"
        db.commit()
    assert client.get("/portal/claims", headers=login("faskes")).json() == []
    assert client.get(f"/portal/claims/{claim_id}", headers=login("faskes")).status_code == 404
    # staf asuransi memakai portal klaim biasa, bukan portal faskes/peserta
    assert client.get("/portal/claims", headers=staf).status_code == 403
    # notifikasi milik pengguna lain tidak bisa ditandai
    with session_factory() as db:
        other = Notification(user_id=users["staf_b"], event="x", email="x@uji.test", subject="x", body="x")
        db.add(other)
        db.commit()
        other_id = other.id
    assert client.post(f"/notifications/{other_id}/read", headers=staf).status_code == 404

    # TPA: ringkasan per asuransi yang dilayani, plus saring daftar klaim per asuransi
    tpa = login("tpa")
    summary = {s["insurer_id"]: s for s in client.get("/tpa/summary", headers=tpa).json()}
    assert set(summary) == {users["insurer_a"], users["insurer_b"]}
    assert summary[users["insurer_a"]]["total"] == 1 and summary[users["insurer_b"]]["total"] == 0
    assert summary[users["insurer_a"]]["by_status"] == {"AWAITING_DOCTOR": 1}
    assert [c["id"] for c in client.get(f"/claims?insurer_id={users['insurer_a']}", headers=tpa).json()] == [claim_id]
    assert client.get(f"/claims?insurer_id={users['insurer_b']}", headers=tpa).json() == []
    assert client.get("/tpa/summary", headers=staf).status_code == 403


def test_pend_without_missing_documents_is_a_plain_decision(client, login, run, pins):
    """Tunda untuk klarifikasi klinis (dokumen lengkap, tanpa doc_types) tetap keputusan biasa: klaim selesai."""
    from tests.test_reasoning import _create_and_upload

    staf, sp = login("staf"), login("spesialis")
    claim_id = _create_and_upload(client, staf, "SYN-TIF-06")["id"]
    run(claim_id)
    _sign(client, sp, claim_id, "PEND")
    assert client.post(f"/claims/{claim_id}/decision", json={"decision": "AGREE"}, headers=staf).status_code == 201
    detail = client.get(f"/claims/{claim_id}", headers=staf).json()
    assert detail["status"] == "COMPLETED" and detail["document_requests"] == []
