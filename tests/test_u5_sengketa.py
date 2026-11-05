"""Tes U5: sengketa / banding. Klaim "tidak dijamin" dibanding, ditelaah ulang dokter LAIN, diputus ulang,
dan jejaknya lengkap di audit."""
from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from mab_api.models import AuditLog, Dispute, InsurerDecision, Recommendation, Review, Role, User
from mab_api.security import hash_secret
from mab_pipeline.ocr.engine import NullOCREngine
from mab_pipeline.tasks import process_claim
from tests.conftest import PASSWORD
from tests.test_reasoning import FIXTURES, _create_and_upload, mock_llm, ruleset  # noqa: F401  (fixture)

PIN = "246810"


@pytest.fixture
def doctors(session_factory, users):
    """PIN untuk dokter uji + spesialis kedua (Penyakit Dalam) untuk menelaah banding."""
    with session_factory() as db:
        for key in ("dokter_umum", "spesialis"):
            db.get(User, users[key]).pin_hash = hash_secret(PIN)
        sp2 = User(email="spesialis_banding@uji.test", full_name="Pengguna spesialis2", role=Role.DOCTOR_SPECIALIST.value,
                   specialty="Penyakit Dalam", password_hash=hash_secret(PASSWORD), pin_hash=hash_secret(PIN))
        db.add(sp2)
        db.commit()
        return sp2.id


@pytest.fixture
def decided(client, login, session_factory, storage, mock_llm, ruleset, doctors):  # noqa: F811
    """Klaim merah yang ditandatangani spesialis "tidak dijamin" lalu disetujui asuransi."""
    def _make(case="SYN-TIF-06", code="NOT_COVERED", number=None) -> str:
        claim = _create_and_upload(client, login("staf"), case, number=number)
        process_claim(claim["id"], session_factory=session_factory, storage=storage, llm=mock_llm,
                      ocr=NullOCREngine(), ruleset=ruleset)
        sp = login("spesialis")
        assert client.post(f"/review/{claim['id']}/start", headers=sp).status_code == 201
        r = client.post(f"/review/{claim['id']}/sign", headers=sp,
                        json={"recommendation": code, "pin": PIN, "reason_code": "DX_NOT_SUPPORTED"})
        assert r.status_code == 200, r.text
        assert client.post(f"/claims/{claim['id']}/decision", json={"decision": "AGREE"}, headers=login("staf")).status_code == 201
        return claim["id"]
    return _make


def _file(client, headers, claim_id, **extra):
    data = {"category": "CLINICAL", "reason": "Hasil kultur darah positif tifoid terlampir, mohon ditelaah ulang."}
    data.update(extra.pop("data", {}))
    return client.post(f"/portal/claims/{claim_id}/disputes", headers=headers, data=data, **extra)


def test_not_covered_claim_disputed_reviewed_by_other_doctor_and_redecided(client, login, decided, doctors, session_factory, users):
    staf, peserta, faskes, sp, sp2 = login("staf"), login("peserta"), login("faskes"), login("spesialis"), login("spesialis_banding")
    claim_id = decided()

    # portal: klaim tidak dijamin boleh dibanding
    item = client.get(f"/portal/claims/{claim_id}", headers=peserta).json()
    assert item["can_dispute"] and item["outcome"].startswith("tidak dijamin")
    assert client.get(f"/portal/claims/{claim_id}", headers=faskes).json()["can_dispute"]

    # 1. peserta mengajukan banding dengan dokumen pendukung
    lab = (FIXTURES / "SYN-TIF-06" / "hasil_laboratorium.pdf").read_bytes()
    r = _file(client, peserta, claim_id, files=[("files", ("kultur.pdf", lab, "application/pdf"))],
              data={"doc_types": "hasil_laboratorium"})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["status"] == "IN_REVIEW" and d["original_reviewer"] == "Pengguna spesialis" and len(d["document_ids"]) == 1
    assert _file(client, faskes, claim_id).status_code == 409  # satu banding berjalan per klaim
    pv = client.get(f"/portal/claims/{claim_id}", headers=peserta).json()
    assert pv["status_label"] == "Banding sedang ditelaah ulang" and pv["open_dispute"]["id"] == d["id"]
    assert "dokter yang berbeda" in pv["explanation"]

    # asuransi belum bisa memutus; klaim kembali menunggu dokter
    detail = client.get(f"/claims/{claim_id}", headers=staf).json()
    assert detail["status"] == "AWAITING_DOCTOR" and detail["disputes"][0]["status"] == "IN_REVIEW"
    assert client.post(f"/claims/{claim_id}/decision", json={"decision": "AGREE"}, headers=staf).status_code == 409

    # 2. penelaah awal TIDAK boleh menelaah bandingnya; spesialis lain ditugaskan otomatis
    assert client.get("/review/queue", headers=sp).json() == []
    ws = client.get(f"/review/{claim_id}", headers=sp)
    assert ws.status_code == 404 or ws.json()["can_start"] is False
    queue = client.get("/review/queue", headers=sp2).json()
    assert [q["id"] for q in queue] == [claim_id] and queue[0]["dispute"] and queue[0]["assigned_to_me"]
    assert queue[0]["level"] == "SPECIALIST"
    ws = client.get(f"/review/{claim_id}", headers=sp2).json()
    assert ws["can_start"] and ws["dispute"]["reason"].startswith("Hasil kultur")
    assert ws["suggestion"]["recommendation"] == "NOT_COVERED"
    assert any(f["code"] == "DISPUTE" for f in ws["draft"]["quality_flags"])
    # admin pun tidak bisa memindahkan banding ke penelaah awal
    r = client.post(f"/admin/claims/{claim_id}/assign", json={"doctor_id": users["spesialis"]}, headers=login("admin"))
    assert r.status_code == 422

    # 3. spesialis kedua membatalkan "tidak dijamin" -> bayar penuh (tanpa kode alasan, tapi wajib pertimbangan)
    assert client.post(f"/review/{claim_id}/start", headers=sp2).status_code == 201
    body = {"recommendation": "PAY_FULL", "pin": PIN}
    r = client.post(f"/review/{claim_id}/sign", json=body, headers=sp2)
    assert r.status_code == 422 and "pertimbangan" in r.text
    r = client.post(f"/review/{claim_id}/sign", json={**body, "notes": "Kultur darah positif, diagnosis tifoid terbukti."},
                    headers=sp2)
    assert r.status_code == 200, r.text
    signed = r.json()
    assert signed["recommendation"] == "PAY_FULL" and signed["reviewer"]["name"] == "Pengguna spesialis2"
    assert signed["explanation_text"].count("Rekomendasi dokter:") == 1
    d = client.get(f"/claims/{claim_id}/disputes", headers=staf).json()[0]
    assert d["status"] == "AWAITING_DECISION" and d["review_outcome"] == "OVERTURNED" and d["reviewer"] == "Pengguna spesialis2"

    # 4. asuransi memutus ulang -> sengketa selesai
    assert client.get(f"/claims/{claim_id}", headers=staf).json()["decision"] is None
    assert client.post(f"/claims/{claim_id}/decision", json={"decision": "AGREE"}, headers=staf).status_code == 201
    d = client.get(f"/claims/{claim_id}/disputes", headers=staf).json()[0]
    assert d["status"] == "RESOLVED" and d["outcome"] == "OVERTURNED" and d["outcome_label"] == "dibatalkan"
    assert d["disputed_recommendation"] == "NOT_COVERED" and d["new_recommendation"] == "PAY_FULL"
    assert client.get(f"/claims/{claim_id}", headers=staf).json()["status"] == "COMPLETED"

    pv = client.get(f"/portal/claims/{claim_id}", headers=peserta).json()
    assert pv["outcome"] == "dibayar penuh" and "Hasil banding: keputusan awal dibatalkan" in pv["explanation"]
    assert not pv["can_dispute"] and pv["dispute_blocked_reason"] == "Banding atas klaim ini sudah diputus; banding hanya satu tingkat"
    titles = [e["title"] for e in pv["timeline"]]
    assert "Banding ditelaah ulang dokter lain" in titles and titles.count("Ditelaah dan ditandatangani dokter") == 1
    titles = [e["title"] for e in pv["timeline"]]
    assert {"Banding diajukan peserta", "Banding ditelaah ulang dokter lain", "Banding selesai"} <= set(titles)
    events = {n["event"] for n in client.get("/notifications", headers=peserta).json()}
    assert {"claim.dispute_filed", "claim.dispute_resolved"} <= events
    assert "claim.dispute_filed" in {n["event"] for n in client.get("/notifications", headers=staf).json()}

    # jejak audit lengkap; telaah banding tidak masuk metrik setuju-dengan-AI
    with session_factory() as db:
        actions = [a.action for a in db.scalars(select(AuditLog).where(AuditLog.claim_id == claim_id).order_by(AuditLog.occurred_at))]
        for a in ("DISPUTE_FILED", "CASE_ASSIGNED", "REVIEW_STARTED", "RECOMMENDATION_SIGNED", "DISPUTE_REVIEWED", "DISPUTE_RESOLVED"):
            assert a in actions, a
        assert actions.index("DISPUTE_FILED") < actions.index("DISPUTE_REVIEWED") < actions.index("DISPUTE_RESOLVED")
        reviews = list(db.scalars(select(Review).where(Review.claim_id == claim_id).order_by(Review.started_at)))
        assert [r.doctor_id for r in reviews] == [users["spesialis"], doctors] and reviews[1].agrees_with_ai is None
        recs = list(db.scalars(select(Recommendation).where(Recommendation.claim_id == claim_id).order_by(Recommendation.version)))
        assert [(r.state, r.recommendation, r.is_current) for r in recs][-2:] == [("DRAFT", "NOT_COVERED", False), ("SIGNED", "PAY_FULL", True)]

    # dashboard dan daftar sengketa
    m = client.get("/dashboard", headers=staf).json()["disputes"]
    assert m["total"] == 1 and m["resolved"] == 1 and m["overturn_rate"] == 100.0 and m["resolved_on_time"] == 1
    assert {c["key"]: c["count"] for c in m["by_outcome"]} == {"UPHELD": 0, "MODIFIED": 0, "OVERTURNED": 1}
    rows = client.get("/disputes", headers=staf).json()
    assert [x["claim_number"] for x in rows] == ["SYN-TIF-06"]
    assert client.get("/disputes", headers=login("staf_b")).json() == []
    assert client.get("/disputes", headers=faskes).status_code == 403


def test_withdraw_refile_and_upheld(client, login, decided, doctors, session_factory):
    staf, faskes, peserta, sp2 = login("staf"), login("faskes"), login("peserta"), login("spesialis_banding")
    claim_id = decided()
    assert _file(client, faskes, claim_id).status_code == 201
    # hanya pengaju yang bisa menarik
    assert client.post(f"/portal/claims/{claim_id}/disputes/withdraw", headers=peserta).status_code == 404
    r = client.post(f"/portal/claims/{claim_id}/disputes/withdraw", headers=faskes)
    assert r.status_code == 200 and r.json()["status"] == "WITHDRAWN"
    detail = client.get(f"/claims/{claim_id}", headers=staf).json()
    assert detail["status"] == "COMPLETED" and detail["decision"] == "AGREE"
    assert client.get(f"/claims/{claim_id}/recommendation", headers=staf).json()["recommendation"] == "NOT_COVERED"
    assert client.get("/review/queue", headers=sp2).json() == []

    # boleh diajukan lagi; kali ini dokter kedua menguatkan putusan awal
    assert _file(client, faskes, claim_id, data={"category": "COVERAGE"}).status_code == 201
    assert client.post(f"/review/{claim_id}/start", headers=sp2).status_code == 201
    r = client.post(f"/review/{claim_id}/sign", json={"recommendation": "NOT_COVERED", "pin": PIN}, headers=sp2)
    assert r.status_code == 200, r.text  # sama dengan putusan awal: tidak perlu kode alasan
    # setelah ditandatangani, banding tidak bisa ditarik
    assert client.post(f"/portal/claims/{claim_id}/disputes/withdraw", headers=faskes).status_code == 409
    r = client.post(f"/claims/{claim_id}/decision", json={"decision": "DIFFER", "reason": "Kebijakan polis tetap."}, headers=staf)
    assert r.status_code == 201
    ds = client.get(f"/claims/{claim_id}/disputes", headers=staf).json()
    assert [d["status"] for d in ds] == ["WITHDRAWN", "RESOLVED"] and ds[1]["outcome"] == "UPHELD"
    # keputusan baru sudah dibanding sekali -> tidak bisa dibanding lagi
    assert _file(client, faskes, claim_id).status_code == 409
    m = client.get("/dashboard", headers=staf).json()["disputes"]
    assert m["withdrawn"] == 1 and m["resolved"] == 1 and m["overturn_rate"] == 0.0


def test_dispute_eligibility(client, login, decided, doctors, session_factory, storage, mock_llm, ruleset):  # noqa: F811
    staf, faskes = login("staf"), login("faskes")
    # klaim yang belum diputuskan tidak bisa dibanding
    pending = _create_and_upload(client, staf, "SYN-GEA-02", number="GEA-PENDING")
    assert _file(client, faskes, pending["id"]).status_code == 409
    # klaim hijau yang dibayar penuh tidak bisa dibanding
    process_claim(pending["id"], session_factory=session_factory, storage=storage, llm=mock_llm, ocr=NullOCREngine(), ruleset=ruleset)
    assert client.post(f"/claims/{pending['id']}/decision", json={"decision": "AGREE"}, headers=staf).status_code == 201
    r = _file(client, faskes, pending["id"])
    assert r.status_code == 409 and r.json()["detail"] == "Klaim sudah dibayar penuh"
    # alasan terlalu pendek, kategori tidak dikenal, peran tanpa izin
    claim_id = decided()
    assert _file(client, faskes, claim_id, data={"reason": "salah"}).status_code == 422
    assert _file(client, faskes, claim_id, data={"category": "LAIN"}).status_code == 422
    assert _file(client, staf, claim_id).status_code == 403
    # lewat batas waktu banding
    with session_factory() as db:
        dec = db.scalar(select(InsurerDecision).where(InsurerDecision.claim_id == claim_id))
        dec.decided_at = dec.decided_at - timedelta(days=31)
        db.commit()
    r = _file(client, faskes, claim_id)
    assert r.status_code == 409 and "Batas waktu banding" in r.json()["detail"]
    with session_factory() as db:
        assert db.scalar(select(Dispute)) is None
