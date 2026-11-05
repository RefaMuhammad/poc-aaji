"""Tes U6: auditor menelusuri satu keputusan dari unggah sampai keputusan akhir, laporan bulanan
dibuat otomatis oleh penjadwal, ekspor PDF/Excel, dan cakupan data per tenant."""
from __future__ import annotations

import io
from datetime import datetime, timezone

from openpyxl import load_workbook
from sqlalchemy import select

from mab_api import reporting
from mab_api.models import AuditLog, Report
from tests.test_reasoning import mock_llm, ruleset  # noqa: F401  (fixture)
from tests.test_u5_sengketa import _file, decided, doctors  # noqa: F401  (fixture)


def _period(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return f"{now.year:04d}-{now.month:02d}"


def test_auditor_traces_decision_from_upload_to_final_decision(client, login, decided, doctors):  # noqa: F811
    claim_id = decided()
    aud, aud_ojk = login("auditor"), login("auditor_ojk")
    assert _file(client, login("peserta"), claim_id).status_code == 201  # banding ikut tercatat di jejak

    t = client.get(f"/audit/claims/{claim_id}/trace", headers=aud).json()
    titles = [s["title"] for s in t["steps"]]
    stages = {s["stage"] for s in t["steps"]}
    assert titles[0] == "Klaim diterima"
    assert any(x.startswith("Dokumen diunggah") for x in titles)
    assert any(x.startswith("Draf rekomendasi v1") for x in titles)
    assert any(x.startswith("Rekomendasi v2 ditandatangani: Tidak dijamin") for x in titles)
    assert any(x.startswith("Keputusan asuransi: setuju") for x in titles)
    assert any(x.startswith("Banding diajukan") for x in titles)
    assert {"Penerimaan", "Pemrosesan sistem", "Telaah dokter", "Keputusan asuransi", "Banding"} <= stages
    chain = " | ".join(t["chain"])
    assert "Keputusan akhir: setuju oleh Pengguna staf" in chain and "Ditandatangani Pengguna spesialis" in chain
    assert "kode alasan DX_NOT_SUPPORTED" in chain and "model " in chain and "SHA-256" in chain
    assert all(len(d["sha256"]) == 64 for d in t["documents"])
    actions = {a["action"] for a in t["audit"]}
    assert {"PIPELINE_COMPLETED", "RECOMMENDATION_SIGNED"} <= actions
    assert any(a["label"] == "Asuransi mencatat keputusan" for a in t["audit"])

    # PDF jejak, dan ekspornya tercatat di audit
    r = client.get(f"/audit/claims/{claim_id}/trace/pdf", headers=aud)
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    # auditor platform juga bisa; staf tidak punya akses audit; tenant lain tidak melihat klaimnya
    assert client.get(f"/audit/claims/{claim_id}/trace", headers=aud_ojk).status_code == 200
    assert client.get(f"/audit/claims/{claim_id}/trace", headers=login("staf")).status_code == 403
    assert client.get(f"/audit/claims/{claim_id}/trace", headers=login("staf_b")).status_code == 403

    # penampil log: filter per klaim, pengguna, aksi, kelompok, tanggal
    logs = client.get("/audit/logs", params={"claim_id": claim_id}, headers=aud).json()
    assert logs["total"] >= 5 and all(i["claim_id"] == claim_id for i in logs["items"])
    assert any(i["action"] == "AUDIT_TRACE_EXPORTED" for i in logs["items"])
    by_user = client.get("/audit/logs", params={"user": "spesialis@uji"}, headers=aud).json()
    assert by_user["total"] >= 1 and all(i["user_email"] == "spesialis@uji.test" for i in by_user["items"])
    signed = client.get("/audit/logs", params={"action": "RECOMMENDATION_SIGNED"}, headers=aud).json()
    assert signed["total"] == 1 and signed["items"][0]["claim_number"]
    review = client.get("/audit/logs", params={"group": "REVIEW", "claim_id": claim_id}, headers=aud).json()
    assert review["total"] >= 1 and all(i["group"] == "REVIEW" for i in review["items"])
    today = datetime.now(timezone.utc).date().isoformat()
    assert client.get("/audit/logs", params={"date_from": today, "date_to": today}, headers=aud).json()["total"] >= 5
    assert client.get("/audit/logs", params={"date_to": "2000-01-01"}, headers=aud).json()["total"] == 0
    by_number = client.get("/audit/logs", params={"claim_number": "SYN-TIF-06"}, headers=aud).json()
    assert by_number["total"] == logs["total"]


def test_audit_log_scope_and_read_only_auditor(client, login, decided, doctors, users, session_factory):  # noqa: F811
    claim_id = decided()
    # auditor tenant A tidak melihat log milik tenant B; auditor platform melihat semua
    login("staf_b")  # LOGIN staf B tercatat dengan user tenant B
    a_items = client.get("/audit/logs", params={"limit": 500}, headers=login("auditor")).json()["items"]
    assert all(i["user_email"] != "staf_b@uji.test" for i in a_items)
    all_items = client.get("/audit/logs", params={"limit": 500}, headers=login("auditor_ojk")).json()["items"]
    assert any(i["user_email"] == "staf_b@uji.test" for i in all_items)
    # ekspor Excel log audit
    r = client.get("/audit/logs/xlsx", params={"claim_id": claim_id}, headers=login("auditor"))
    assert r.status_code == 200
    ws = load_workbook(io.BytesIO(r.content)).active
    assert ws.cell(2, 1).value == "Waktu (UTC)" and ws.max_row > 3
    # auditor hanya-baca: tidak bisa memutuskan, membuat laporan, atau menulis apa pun
    aud = login("auditor")
    assert client.post(f"/claims/{claim_id}/decision", json={"decision": "AGREE"}, headers=aud).status_code == 403
    assert client.post("/reports", json={"period": _period()}, headers=aud).status_code == 403
    for role in ("staf", "dokter_umum", "faskes", "peserta", "tpa"):
        assert client.get("/audit/logs", headers=login(role)).status_code == 403, role


def test_monthly_report_generated_by_scheduler_and_exported(client, login, decided, doctors, session_factory, users):  # noqa: F811
    claim_id = decided()
    peserta = login("peserta")
    assert _file(client, peserta, claim_id).status_code == 201  # banding masuk ke bagian sengketa

    # penjadwal pada awal bulan berikutnya membuat laporan bulan ini untuk tiap tenant + platform
    now = datetime.now(timezone.utc)
    nxt = datetime(now.year + (now.month == 12), 1 if now.month == 12 else now.month + 1, 1, 1, tzinfo=timezone.utc)
    with session_factory() as db:
        made = reporting.run_schedule(db, now=nxt)
        db.commit()
        assert {r.scope_key for r in made} == {users["insurer_a"], users["insurer_b"], "ALL"}
        assert all(r.period == _period(now) and r.trigger == "SCHEDULED" and not r.partial for r in made)
        assert reporting.run_schedule(db, now=nxt) == []  # tidak dobel
        assert db.scalar(select(AuditLog).where(AuditLog.action == "REPORT_GENERATED")) is not None

    # manajer A hanya melihat laporan tenant A
    mgr = login("manajer")
    lst = client.get("/reports", headers=mgr).json()
    assert [r["insurer_id"] for r in lst["items"]] == [users["insurer_a"]] and not lst["can_platform"] and lst["can_generate"]
    rep = client.get(f"/reports/{lst['items'][0]['id']}", headers=mgr).json()
    sections = {s["id"]: s for s in rep["data"]["sections"]}
    assert set(sections) == set("ABCDEFGH")
    rows = {r["label"]: r["value"] for r in sections["B"]["rows"]}
    assert rows["Klaim diterima"] == 1 and rows["Klaim diputus asuransi"] == 1
    ur = {r["label"]: r["value"] for r in sections["C"]["rows"]}
    assert ur["Rekomendasi ditandatangani dokter"] == 1
    assert "Pasal 29" in sections["C"]["basis"] and "Pasal 8" in sections["D"]["basis"]
    assert sections["D"]["tables"][0]["rows"][0][0] == "Pengguna spesialis"
    assert {r["label"]: r["value"] for r in sections["F"]["rows"]}["Banding diajukan"] == 1
    assert "draf" in rep["data"]["template_note"].lower() and rep["data"]["label"] == "Data rekaan untuk demonstrasi"
    # tenant lain dan laporan platform tidak terlihat
    others = client.get("/reports", headers=login("auditor_ojk")).json()["items"]
    other_ids = {r["id"] for r in others if r["insurer_id"] != users["insurer_a"]}
    for rid in other_ids:
        assert client.get(f"/reports/{rid}", headers=mgr).status_code == 404

    # ekspor PDF dan Excel oleh auditor (hanya-baca boleh mengunduh)
    aud = login("auditor")
    rid = lst["items"][0]["id"]
    pdf = client.get(f"/reports/{rid}/pdf", headers=aud)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF") and "laporan_pojk36_a_" in pdf.headers["content-disposition"]
    xl = client.get(f"/reports/{rid}/xlsx", headers=aud)
    wb = load_workbook(io.BytesIO(xl.content))
    values = [c.value for row in wb.active.iter_rows() for c in row if c.value]
    assert "C. Telaah Utilisasi" in values and "DATA REKAAN UNTUK DEMONSTRASI" in values
    with session_factory() as db:
        assert len(db.scalars(select(AuditLog).where(AuditLog.action == "REPORT_DOWNLOADED")).all()) == 2

    # buat ulang manual: revisi naik; periode berjalan ditandai sementara; periode depan ditolak
    r = client.post("/reports", json={"period": _period(now)}, headers=mgr)
    assert r.status_code == 201 and r.json()["revision"] == 2 and r.json()["trigger"] == "MANUAL" and r.json()["partial"]
    assert client.post("/reports", json={"period": "2999-01"}, headers=mgr).status_code == 422
    assert client.post("/reports", json={"period": "2026-13"}, headers=mgr).status_code == 422
    assert client.post("/reports", json={"period": _period(now), "insurer_id": users["insurer_b"]}, headers=mgr).status_code == 404
    # admin bisa laporan seluruh platform dan menjalankan penjadwal manual
    adm = login("admin")
    assert client.post("/reports", json={"period": _period(now)}, headers=adm).json()["insurer_id"] is None
    assert client.post("/reports/run-schedule", headers=adm).status_code == 200
    with session_factory() as db:
        assert db.scalar(select(Report).where(Report.scope_key == "ALL", Report.period == _period(now))).revision == 2
