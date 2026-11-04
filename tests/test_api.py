"""Tes API M3: auth, klaim, unggah, antrean, akses per peran, rekomendasi, keputusan, ekspor, audit."""
from __future__ import annotations

import csv
import io
import zipfile

import pytest
from openpyxl import Workbook
from sqlalchemy import select

from mab_api.documents import REQUIRED_INPATIENT_DOCS
from mab_api.models import AuditLog, Claim, Finding, Recommendation
from mab_pipeline.llm.mock import MockLLMClient
from mab_pipeline.ocr.engine import NullOCREngine
from mab_pipeline.tasks import process_claim

PDF = b"%PDF-1.4\n% data rekaan\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20

CLAIM = {
    "claim_number": "KLM-001",
    "policy_number": "POL-1",
    "member_id": "PST-1",
    "patient_name": "Pasien Rekaan",
    "hospital_name": "RS Sehat Sentosa",
    "admission_date": "2026-03-02",
    "discharge_date": "2026-03-07",
    "billed_amount": 5_285_000,
}


def _create_claim(client, headers, **overrides) -> dict:
    r = client.post("/claims", json={**CLAIM, **overrides}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _upload(client, headers, claim_id, files=None, **params):
    files = files or [
        ("files", ("resume_medis.pdf", PDF, "application/pdf")),
        ("files", ("hasil_laboratorium.pdf", PDF, "application/pdf")),
        ("files", ("rincian_tagihan.pdf", PDF, "application/pdf")),
    ]
    return client.post(f"/claims/{claim_id}/documents", files=files, params=params, headers=headers)


def _add_recommendation(session_factory, claim_id, *, triage="GREEN", rec="PAY_FULL", state="DRAFT", status="AWAITING_DECISION"):
    with session_factory() as db:
        claim = db.get(Claim, claim_id)
        claim.status = status
        r = Recommendation(
            claim_id=claim_id, triage_status=triage, risk_score=0 if triage == "GREEN" else 60, recommendation=rec,
            state=state, billed_amount=claim.billed_amount, recommended_amount=claim.billed_amount,
            model_version="mock-0", prompt_version="extract_v1", ruleset_version="rules-2026.11-demo",
        )
        db.add(r)
        db.flush()
        if triage != "GREEN":
            db.add(Finding(claim_id=claim_id, recommendation_id=r.id, rule_id="DEN-01", reason_code="DX_NOT_SUPPORTED",
                           severity="HIGH", source="RULE", text="Trombosit terendah 120.000/uL",
                           evidence=[{"doc": "LAB-01", "page": 1, "quote": "Trombosit 120.000"}]))
        db.commit()
        return r.id


# --- dasar ---------------------------------------------------------------------------------


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_required_docs_match_rules_yaml():
    import yaml
    from tests.test_rules import RULES_FILE

    doc = yaml.safe_load(RULES_FILE.read_text(encoding="utf-8"))
    assert tuple(doc["triase"]["dokumen_wajib_rawat_inap"]) == REQUIRED_INPATIENT_DOCS


# --- auth ----------------------------------------------------------------------------------


def test_login_and_me(client, login):
    r = client.get("/auth/me", headers=login("staf"))
    assert r.status_code == 200 and r.json()["role"] == "insurer_staff"


def test_wrong_password_rejected_and_audited(client, session_factory):
    r = client.post("/auth/login", json={"email": "staf@uji.test", "password": "salah"})
    assert r.status_code == 401
    with session_factory() as db:
        assert db.scalar(select(AuditLog).where(AuditLog.action == "LOGIN_FAILED")) is not None


def test_requests_without_token_are_rejected(client):
    assert client.get("/claims").status_code == 401
    assert client.get("/claims", headers={"Authorization": "Bearer palsu"}).status_code == 401


# --- buat klaim & unggah --------------------------------------------------------------------


def test_create_claim_validates_dates(client, login):
    r = client.post("/claims", json={**CLAIM, "discharge_date": "2026-03-01"}, headers=login("staf"))
    assert r.status_code == 422


def test_duplicate_claim_number_conflict(client, login):
    _create_claim(client, login("staf"))
    r = client.post("/claims", json=CLAIM, headers=login("staf"))
    assert r.status_code == 409


def test_upload_enqueues_job_and_status_changes(client, login, job_queue, session_factory, storage):
    claim = _create_claim(client, login("staf"))
    assert claim["status"] == "RECEIVED"

    r = _upload(client, login("staf"), claim["id"])
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "QUEUED" and body["job_id"]
    assert {d["doc_type"] for d in body["documents"]} == set(REQUIRED_INPATIENT_DOCS)
    assert len(storage.objects) == 3

    # job masuk antrean dengan argumen claim_id
    jobs = job_queue.queue.jobs
    assert len(jobs) == 1 and jobs[0].args == (claim["id"],)
    assert jobs[0].func_name == "mab_pipeline.tasks.process_claim"

    # worker menjalankan job -> status berubah. PDF uji ini bukan PDF utuh, jadi klaim
    # ditandai FAILED dengan pesan yang jelas (tes pipeline lengkap ada di test_pipeline.py).
    process_claim(claim["id"], session_factory=session_factory, storage=storage, llm=MockLLMClient(), ocr=NullOCREngine())
    body = client.get(f"/claims/{claim['id']}/status", headers=login("staf")).json()
    assert body["status"] == "FAILED" and "Tidak ada dokumen yang bisa dibuka" in body["processing_error"]


def test_missing_documents_are_listed(client, login):
    claim = _create_claim(client, login("staf"))
    _upload(client, login("staf"), claim["id"], files=[("files", ("resume_medis.pdf", PDF, "application/pdf"))], submit="false")
    detail = client.get(f"/claims/{claim['id']}", headers=login("staf")).json()
    assert detail["status"] == "RECEIVED"
    assert detail["missing_documents"] == ["rincian_tagihan", "hasil_laboratorium"]


def test_upload_rejects_non_pdf_or_image(client, login, storage):
    claim = _create_claim(client, login("staf"))
    r = _upload(client, login("staf"), claim["id"], files=[("files", ("virus.exe", b"MZ\x90\x00", "application/pdf"))])
    assert r.status_code == 422
    assert storage.objects == {}


def test_upload_accepts_png(client, login):
    claim = _create_claim(client, login("staf"))
    r = _upload(client, login("staf"), claim["id"], files=[("files", ("foto_resume.png", PNG, "image/png"))])
    assert r.status_code == 201 and r.json()["documents"][0]["content_type"] == "image/png"


def test_upload_rejects_oversized_file(client, login, monkeypatch):
    from mab_api.config import get_settings

    monkeypatch.setattr(get_settings(), "max_upload_mb", 0)
    claim = _create_claim(client, login("staf"))
    assert _upload(client, login("staf"), claim["id"]).status_code == 422


def test_download_document(client, login):
    claim = _create_claim(client, login("staf"))
    doc_id = _upload(client, login("staf"), claim["id"]).json()["documents"][0]["id"]
    r = client.get(f"/documents/{doc_id}/download", headers=login("staf"))
    assert r.status_code == 200 and r.content == PDF


# --- unggah ZIP ----------------------------------------------------------------------------


def _zip_with_manifest(rows: list[list], folders: dict[str, dict[str, bytes]]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["folder", "nomor_klaim", "nomor_polis", "id_peserta", "nama_peserta", "nama_rs", "tanggal_masuk", "tanggal_keluar", "nilai_tagihan"])
    for row in rows:
        ws.append(row)
    xbuf = io.BytesIO()
    wb.save(xbuf)
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w") as z:
        z.writestr("batch/manifest.xlsx", xbuf.getvalue())
        for folder, files in folders.items():
            for name, data in files.items():
                z.writestr(f"batch/{folder}/{name}", data)
    return zbuf.getvalue()


def test_batch_zip_upload_reports_success_and_failure(client, login, job_queue):
    docs = {"resume_medis.pdf": PDF, "hasil_laboratorium.pdf": PDF, "rincian_tagihan.pdf": PDF}
    data = _zip_with_manifest(
        [
            ["SYN-1", "Z-001", "POL-1", "PST-1", "Rekaan A", "RS A", "2026-03-02", "2026-03-05", 4_000_000],
            ["SYN-2", "Z-002", "POL-2", "PST-2", "Rekaan B", "RS B", "05/03/2026", "07/03/2026", 3_000_000],
            ["SYN-3", "Z-003", "POL-3", "PST-3", "Rekaan C", "RS C", "2026-03-09", "2026-03-08", 1_000],  # tanggal terbalik
            ["TIDAK-ADA", "Z-004", "POL-4", "PST-4", "Rekaan D", "RS D", "2026-03-02", "2026-03-04", 1_000],
            ["SYN-5", "Z-005", "POL-5", "PST-5", "Rekaan E", "RS E", "2026-03-02", "2026-03-04", 1_000],  # file bukan PDF
        ],
        {"SYN-1": docs, "SYN-2": docs, "SYN-3": docs, "SYN-5": {"catatan.txt": b"bukan pdf"}},
    )
    r = client.post("/claims/batch", files={"file": ("batch.zip", data, "application/zip")}, headers=login("staf"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["created"], body["failed"]) == (2, 3)
    reasons = {row["claim_number"]: row["reason"] for row in body["rows"] if not row["ok"]}
    assert "Tanggal keluar" in reasons["Z-003"]
    assert "tidak ada di ZIP" in reasons["Z-004"]
    assert "PDF, JPG, atau PNG" in reasons["Z-005"]
    assert len(job_queue.queue.jobs) == 2
    claims = client.get("/claims", headers=login("staf")).json()
    assert {c["claim_number"] for c in claims} == {"Z-001", "Z-002"}
    assert all(c["status"] == "QUEUED" for c in claims)


def test_batch_without_manifest_is_rejected(client, login):
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w") as z:
        z.writestr("SYN-1/resume.pdf", PDF)
    r = client.post("/claims/batch", files={"file": ("x.zip", zbuf.getvalue(), "application/zip")}, headers=login("staf"))
    assert r.status_code == 400


# --- akses per peran -----------------------------------------------------------------------


def test_insurer_staff_cannot_see_other_insurers_claims(client, login):
    claim = _create_claim(client, login("staf"))
    other = login("staf_b")
    assert client.get(f"/claims/{claim['id']}", headers=other).status_code == 404
    assert client.get("/claims", headers=other).json() == []
    assert _upload(client, other, claim["id"]).status_code == 404


def test_other_insurer_cannot_download_document(client, login):
    claim = _create_claim(client, login("staf"))
    doc_id = _upload(client, login("staf"), claim["id"]).json()["documents"][0]["id"]
    assert client.get(f"/documents/{doc_id}/download", headers=login("staf_b")).status_code == 404


def test_same_claim_number_allowed_for_different_insurer(client, login):
    _create_claim(client, login("staf"))
    _create_claim(client, login("staf_b"))


@pytest.mark.parametrize("role", ["dokter_umum", "spesialis", "admin"])
def test_non_insurer_roles_cannot_create_claims(client, login, role):
    assert client.post("/claims", json=CLAIM, headers=login(role)).status_code == 403


def test_doctor_cannot_record_insurer_decision(client, login, session_factory):
    claim = _create_claim(client, login("staf"))
    _add_recommendation(session_factory, claim["id"])
    r = client.post(f"/claims/{claim['id']}/decision", json={"decision": "AGREE"}, headers=login("spesialis"))
    assert r.status_code == 403


def test_doctor_sees_only_claims_awaiting_doctor(client, login, session_factory):
    waiting = _create_claim(client, login("staf"), claim_number="KLM-W")
    _create_claim(client, login("staf"), claim_number="KLM-N")
    _add_recommendation(session_factory, waiting["id"], triage="RED", rec="DOCTOR_REVIEW", status="AWAITING_DOCTOR")
    claims = client.get("/claims", headers=login("dokter_umum")).json()
    assert [c["claim_number"] for c in claims] == ["KLM-W"]


def test_admin_can_list_users_others_cannot(client, login):
    assert client.get("/users", headers=login("admin")).status_code == 200
    assert client.get("/users", headers=login("staf")).status_code == 403


# --- rekomendasi & keputusan ----------------------------------------------------------------


def test_green_recommendation_follows_prd_format(client, login, session_factory):
    claim = _create_claim(client, login("staf"))
    _add_recommendation(session_factory, claim["id"])
    r = client.get(f"/claims/{claim['id']}/recommendation", headers=login("staf"))
    assert r.status_code == 200
    body = r.json()
    for key in ("triage_status", "risk_score", "recommendation", "findings", "reviewer", "model_version",
                "prompt_version", "ruleset_version", "insurer_decision", "billed_amount", "recommended_amount"):
        assert key in body
    assert body["recommendation"] == "PAY_FULL" and body["ruleset_version"] == "rules-2026.11-demo"


def test_unsigned_non_pay_full_recommendation_is_hidden_from_insurer(client, login, session_factory):
    claim = _create_claim(client, login("staf"))
    _add_recommendation(session_factory, claim["id"], triage="RED", rec="DOCTOR_REVIEW", status="AWAITING_DOCTOR")
    assert client.get(f"/claims/{claim['id']}/recommendation", headers=login("staf")).status_code == 409
    assert client.post(f"/claims/{claim['id']}/decision", json={"decision": "AGREE"}, headers=login("staf")).status_code == 409
    # dokter melihat draf beserta bukti
    r = client.get(f"/claims/{claim['id']}/recommendation", headers=login("spesialis"))
    assert r.status_code == 200 and r.json()["findings"][0]["evidence"][0]["quote"] == "Trombosit 120.000"


def test_record_decision_and_differ_needs_reason(client, login, session_factory):
    claim = _create_claim(client, login("staf"))
    _add_recommendation(session_factory, claim["id"])
    r = client.post(f"/claims/{claim['id']}/decision", json={"decision": "DIFFER"}, headers=login("staf"))
    assert r.status_code == 422
    r = client.post(f"/claims/{claim['id']}/decision", json={"decision": "DIFFER", "reason": "Plafon kamar terlampaui"}, headers=login("staf"))
    assert r.status_code == 201
    assert r.json()["insurer_decision"]["decision"] == "DIFFER"
    assert client.get(f"/claims/{claim['id']}/status", headers=login("staf")).json()["status"] == "COMPLETED"
    # tidak bisa diputuskan dua kali
    assert client.post(f"/claims/{claim['id']}/decision", json={"decision": "AGREE"}, headers=login("staf")).status_code == 409


def test_bulk_agree_only_green(client, login, session_factory):
    green = _create_claim(client, login("staf"), claim_number="G")
    red = _create_claim(client, login("staf"), claim_number="R")
    _add_recommendation(session_factory, green["id"])
    _add_recommendation(session_factory, red["id"], triage="RED", rec="PAY_PARTIAL", state="SIGNED")
    r = client.post("/claims/decisions/bulk-agree", json={"claim_ids": [green["id"], red["id"], "tidak-ada"]}, headers=login("staf"))
    body = r.json()
    assert body["agreed"] == [green["id"]]
    assert len(body["skipped"]) == 2


def test_export_csv(client, login, session_factory):
    claim = _create_claim(client, login("staf"))
    _add_recommendation(session_factory, claim["id"])
    client.post(f"/claims/{claim['id']}/decision", json={"decision": "AGREE"}, headers=login("staf"))
    r = client.get("/claims/export.csv", headers=login("staf"))
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(r.text.lstrip("﻿"))))
    assert rows[0]["nomor_klaim"] == "KLM-001"
    assert rows[0]["rekomendasi"] == "PAY_FULL" and rows[0]["keputusan_asuransi"] == "AGREE"
    assert client.get("/claims/export.csv", headers=login("staf_b")).text.count("\n") == 1  # hanya header


# --- audit ---------------------------------------------------------------------------------


def test_writes_and_document_access_are_audited(client, login, session_factory, users):
    claim = _create_claim(client, login("staf"))
    doc_id = _upload(client, login("staf"), claim["id"]).json()["documents"][0]["id"]
    client.get(f"/documents/{doc_id}/download", headers=login("staf"))
    client.get("/claims", headers=login("staf"))  # baca daftar: tidak dicatat
    with session_factory() as db:
        logs = list(db.scalars(select(AuditLog).order_by(AuditLog.id)))
    actions = [l.action for l in logs]
    assert "LOGIN" in actions
    assert "POST /claims" in actions
    assert f"POST /claims/{claim['id']}/documents" in actions
    access = next(l for l in logs if l.action == "DOCUMENT_ACCESS")
    assert access.document_id == doc_id and access.user_id == users["staf"]
    assert not any(a == "GET /claims" for a in actions)
