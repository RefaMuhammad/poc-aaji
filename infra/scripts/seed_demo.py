"""Isi aplikasi dengan data demo (DATA REKAAN) lewat API, supaya portal dan dashboard berisi.

Langkah:
1. Buat akun demo (seed_users).
2. Buat klaim riwayat KLM-RIWAYAT-0001 (untuk contoh klaim tumpang tindih SYN-GEA-10).
3. Unggah 29 dari 30 klaim sintetis di data/synthetic_output lalu tunggu worker selesai.
   SYN-DEN-09 sengaja tidak diunggah: klaim ini diunggah langsung saat demo (lihat docs/demo-script.md).
4. Sebagian kasus ditelaah dokter (setujui draf, satu diubah, satu dieskalasi), sebagian dibiarkan di antrean.
5. Sebagian klaim diputuskan asuransi (setuju massal klaim hijau, satu "berbeda"), sebagian dibiarkan.
6. Tenant kedua (Asuransi Pelita, ambang merah 20): 6 klaim yang sama diunggah supaya terlihat
   perbedaan triase antar tenant. Termasuk SYN-DEN-09 (kuning di DEMO, merah di PELITA).
7. (U2) Plan benefit + polis rekaan untuk semua peserta sintetis di kedua tenant, webhook ke penerima
   demo, API key Pelita, lalu satu klaim per kanal integrasi ke Pelita: SYN-DEN-01 lewat FHIR Bundle,
   SYN-GEA-01 lewat API multipart, SYN-TIF-01 dan SYN-TIF-02 lewat folder SFTP (butuh layanan sftp-watcher).
   Di Pelita, SYN-DEN-02 memakai plan kelas 2 (kamar melebihi hak) dan SYN-GEA-02 hampir habis limitnya.
8. (U3) Riwayat klaim sintetis dengan pola fraud tertanam (data/synthetic_output/fraud/riwayat_klaim.csv,
   dibuat otomatis bila belum ada) diimpor ke kedua tenant, lalu analisis fraud dijalankan. Klaim yang
   sudah diproses di langkah sebelumnya ikut dianalisis. Fraud Monitor langsung berisi 8 sinyal.
9. (U4) SYN-TIF-10 (rincian tagihan tidak dikirim): dokter umum menunda, asuransi setuju menunda dan
   meminta rincian tagihan ke RS. Klaim berhenti di "menunggu dokumen susulan" supaya saat demo akun
   faskes mengunggah data/synthetic_output/SYN-TIF-10/susulan/rincian_tagihan.pdf lewat Portal Faskes.
10. (U5) SYN-GEA-06 (RSU Harapan Bunda, rawat inap dehidrasi ringan-sedang): spesialis menandatangani
   "tidak dijamin" dan asuransi setuju. Saat demo akun faskes mengajukan banding, lalu
   dokter.spesialis2@mab.test (bukan penelaah awal) menelaah ulang dan asuransi memutus ulang.
11. (U6) Penjadwal laporan dijalankan sekali (laporan bulan lalu untuk tiap tenant + seluruh platform), lalu
   manajer DEMO membuat laporan bulan berjalan supaya halaman Laporan & Audit langsung berisi.
12. (U7) underwriter@demo.test mengajukan 10 calon peserta sintetis (data/synthetic_output/underwriting).
   Dokter umum menandatangani 3 draf, underwriter memutus 3 pengajuan, sisanya di antrean dokter/underwriter.
   UW-24 sengaja belum diunggah untuk demo langsung.

Butuh: `make up` dan `make synthetic` sudah dijalankan. Jalankan di container api:
    docker compose exec api python infra/scripts/seed_demo.py
Jalankan pada database kosong (`make reset`); bila klaim SYN-* sudah ada, skrip berhenti.
"""
from __future__ import annotations

import io
import json
import os
import sys
import time
import zipfile
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api"))
sys.path.insert(0, "/app")

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from seed_users import link_portal_accounts  # noqa: E402
from seed_users import seed as seed_users  # noqa: E402

API = os.environ.get("SEED_API_URL", "http://localhost:8000")
PASSWORD = os.environ.get("DEMO_PASSWORD", "demo12345")
PIN = os.environ.get("DEMO_PIN", "123456")
DATA = Path(os.environ.get("SEED_DATA_DIR", Path(__file__).resolve().parents[2] / "data" / "synthetic_output"))
LIVE_DEMO_CLAIM = os.environ.get("SEED_SKIP", "SYN-DEN-09")
TIMEOUT = int(os.environ.get("SEED_TIMEOUT", "1800"))
DOC_ORDER = ["resume_medis", "hasil_laboratorium", "cppt", "rincian_tagihan"]
HISTORY_FOR = "SYN-GEA-10"
SECOND_TENANT_STAFF = "staf@pelita.test"
SECOND_TENANT_CLAIMS = ["SYN-DEN-02", "SYN-GEA-02", "SYN-DEN-08", "SYN-DEN-09", "SYN-GEA-07", "SYN-TIF-07"]
LATE_DOCS_CLAIM = "SYN-TIF-10"  # U4: alur "tunda: minta dokumen" (rincian tagihan menyusul)
FACILITY_FROM = LATE_DOCS_CLAIM  # akun faskes = RS klaim ini
MEMBER_FROM = LATE_DOCS_CLAIM    # akun peserta = peserta klaim ini (U4: ikut memantau klaim yang ditunda)
DISPUTE_CLAIM = "SYN-GEA-06"     # U5: "tidak dijamin" di RS akun faskes, siap dibanding saat demo
SECOND_SPECIALIST = "dokter.spesialis2@mab.test"

# --- U2: polis, webhook, kanal integrasi ---
ADMIN = "admin@mab.test"
WEBHOOK_BASE = os.environ.get("SEED_WEBHOOK_BASE", "http://api:8000")   # alamat API dari sisi worker
SFTP_ROOT = Path(os.environ.get("SFTP_ROOT", DATA.parent / "sftp"))
OUT_DIR = DATA.parent / "demo_upload"
POLICY_START, POLICY_END = "2025-07-01", "2026-12-31"
PLANS = {
    "DEMO": [
        {"code": "SEHAT-K1", "name": "Sehat Rawat Inap Kelas 1", "room_class": "Kelas 1", "room_rate_limit": 500_000,
         "annual_limit": 150_000_000, "waiting_period_days": 30, "excluded_icd10": ["O", "Z30"]},
    ],
    "PELITA": [
        {"code": "PELITA-K1", "name": "Pelita Prima Kelas 1", "room_class": "Kelas 1", "room_rate_limit": 500_000,
         "annual_limit": 50_000_000, "waiting_period_days": 30, "excluded_icd10": ["O"]},
        {"code": "PELITA-K2", "name": "Pelita Hemat Kelas 2", "room_class": "Kelas 2", "room_rate_limit": 300_000,
         "annual_limit": 50_000_000, "waiting_period_days": 30, "excluded_icd10": ["O"]},
    ],
}
PELITA_PLAN_K2 = {"SYN-DEN-02"}                    # kamar kelas 1 ditagihkan, hak kelas 2
PELITA_LIMIT_USED = {"SYN-GEA-02": 48_000_000}      # sisa limit Rp2 jt < tagihan
CHANNEL_FHIR, CHANNEL_API, CHANNEL_SFTP = "SYN-DEN-01", "SYN-GEA-01", ["SYN-TIF-01", "SYN-TIF-02"]


class Api:
    def __init__(self, email: str):
        self.http = httpx.Client(base_url=API, timeout=120)
        r = self.http.post("/auth/login", json={"email": email, "password": PASSWORD})
        r.raise_for_status()
        self.http.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        self.email = email

    def get(self, path: str, **kw):
        r = self.http.get(path, **kw)
        r.raise_for_status()
        return r.json()

    def post(self, path: str, expect: tuple[int, ...] = (200, 201, 204), **kw):
        r = self.http.post(path, **kw)
        if r.status_code not in expect:
            raise RuntimeError(f"{self.email} POST {path}: HTTP {r.status_code} {r.text[:300]}")
        return r.json() if r.content else None


def claim_body(case: dict, number: str | None = None) -> dict:
    p = case["patient"]
    return {
        "claim_number": number or case["claim_id"],
        "policy_number": p["policy_no"],
        "member_id": p["member_id"],
        "patient_name": p["name"],
        "hospital_name": case["hospital"]["name"],
        "admission_date": case["admission_date"],
        "discharge_date": case["discharge_date"],
        "billed_amount": int(case["billing_total"]),
    }


def _upload_one(staf: Api, folder: Path) -> str:
    case = json.loads((folder / "case.json").read_text(encoding="utf-8"))
    claim = staf.post("/claims", json=claim_body(case))
    files = []
    for name in DOC_ORDER:
        pdf = folder / f"{name}.pdf"
        if pdf.exists():
            files.append(("files", (pdf.name, pdf.read_bytes(), "application/pdf")))
    staf.post(f"/claims/{claim['id']}/documents", files=files)
    print(f"  {folder.name}: {len(files)} dokumen diunggah")
    return claim["id"]


def upload_claims(staf: Api) -> list[str]:
    folders = sorted(p for p in DATA.iterdir() if p.is_dir() and p.name.startswith("SYN-"))
    if not folders:
        sys.exit(f"Tidak ada data sintetis di {DATA}. Jalankan `make synthetic` dulu.")

    # klaim riwayat untuk contoh klaim tumpang tindih
    hist_case = json.loads((DATA / HISTORY_FOR / "case.json").read_text(encoding="utf-8"))
    for number in hist_case.get("overlapping_claims", []):
        body = claim_body(hist_case, number) | {"patient_name": f"{hist_case['patient']['name']} (klaim lama)",
                                                 "billed_amount": int(hist_case["billing_total"] * 0.8)}
        staf.post("/claims", json=body)
        print(f"  klaim riwayat {number} dibuat")

    return [_upload_one(staf, folder) for folder in folders if folder.name != LIVE_DEMO_CLAIM]


def upload_second_tenant() -> tuple[Api, list[str]]:
    staf = Api(SECOND_TENANT_STAFF)
    return staf, [_upload_one(staf, DATA / name) for name in SECOND_TENANT_CLAIMS if (DATA / name).is_dir()]


# ----------------------------------------------------------------------------- U2


def _cases() -> list[dict]:
    return [json.loads((p / "case.json").read_text(encoding="utf-8"))
            for p in sorted(DATA.iterdir()) if p.is_dir() and (p / "case.json").exists()]


def setup_policies_and_webhooks() -> dict[str, str]:
    """Plan + polis rekaan untuk semua peserta sintetis, dan webhook ke penerima demo. Kembalikan kode -> insurer_id."""
    admin = Api(ADMIN)
    tenants = {t["code"]: t for t in admin.get("/tenants")}
    cases = _cases()
    for code, plans in PLANS.items():
        t = tenants[code]
        for plan in plans:
            r = admin.http.put("/policies/plans", json={"insurer_id": t["insurer_id"], **plan})
            r.raise_for_status()
        lines = ["nomor_polis,id_peserta,nama_peserta,kode_plan,tanggal_mulai,tanggal_akhir,status,limit_terpakai"]
        for c in cases:
            p = c["patient"]
            plan = plans[0]["code"]
            used = 0
            if code == "PELITA":
                plan = "PELITA-K2" if c["claim_id"] in PELITA_PLAN_K2 else "PELITA-K1"
                used = PELITA_LIMIT_USED.get(c["claim_id"], 0)
            lines.append(f"{p['policy_no']},{p['member_id']},{p['name']},{plan},{POLICY_START},{POLICY_END},ACTIVE,{used}")
        res = admin.post("/policies/import", data={"insurer_id": t["insurer_id"]},
                         files={"file": (f"polis_{code}.csv", "\n".join(lines).encode(), "text/csv")})
        print(f"  {code}: {len(plans)} plan, {res['created']} polis baru, {res['updated']} diperbarui")

        keys = ("display_name", "logo_data_url", "primary_color", "triage_red_min_score", "triage_yellow_min_score",
                "disabled_rules", "sla_gp_hours", "sla_specialist_hours", "auto_assign")
        body = {k: t[k] for k in keys} | {"webhook_url": f"{WEBHOOK_BASE}/integrations/demo-sink/{code}",
                                          "webhook_secret": f"rahasia-webhook-demo-{code.lower()}"}
        r = admin.http.put(f"/tenants/{t['insurer_id']}/settings", json=body)
        r.raise_for_status()
        print(f"  {code}: webhook -> {body['webhook_url']}")
    return {code: t["insurer_id"] for code, t in tenants.items()}


def _sftp_zip(claims: list[str]) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["folder", "nomor_klaim", "nomor_polis", "id_peserta", "nama_peserta", "nama_rs", "tanggal_masuk",
               "tanggal_keluar", "nilai_tagihan"])
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in claims:
            body = claim_body(json.loads((DATA / name / "case.json").read_text(encoding="utf-8")))
            ws.append([name, body["claim_number"], body["policy_number"], body["member_id"], body["patient_name"],
                       body["hospital_name"], body["admission_date"], body["discharge_date"], body["billed_amount"]])
            for doc in DOC_ORDER:
                pdf = DATA / name / f"{doc}.pdf"
                if pdf.exists():
                    zf.write(pdf, f"{name}/{pdf.name}")
        xbuf = io.BytesIO()
        wb.save(xbuf)
        zf.writestr("manifest.xlsx", xbuf.getvalue())
    return zbuf.getvalue()


def channel_demos(tenant_ids: dict[str, str], staf_pelita: Api) -> list[str]:
    """API key Pelita, lalu satu klaim per kanal: FHIR, API multipart, SFTP."""
    from make_fhir_bundle import build_bundle

    admin = Api(ADMIN)
    created = admin.post(f"/tenants/{tenant_ids['PELITA']}/api-clients",
                         json={"name": "Sistem inti Pelita (demo)", "scopes": ["claims:read", "claims:write", "policies:write"]})
    key = created["api_key"]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "api_key_PELITA.txt").write_text(key + "\n", encoding="utf-8")
    print(f"  API key Pelita disimpan di {OUT_DIR / 'api_key_PELITA.txt'} (hanya untuk demo, data rekaan)")
    integ = httpx.Client(base_url=API, timeout=120, headers={"X-API-Key": key})
    ids: list[str] = []

    r = integ.post("/integrations/v1/fhir", json=build_bundle(DATA / CHANNEL_FHIR))
    r.raise_for_status()
    ids.append(r.json()["claim_id"])
    print(f"  FHIR Bundle: {CHANNEL_FHIR} diterima ({r.json()['documents']} dokumen)")

    case = json.loads((DATA / CHANNEL_API / "case.json").read_text(encoding="utf-8"))
    files = [("files", (f"{d}.pdf", (DATA / CHANNEL_API / f"{d}.pdf").read_bytes(), "application/pdf"))
             for d in DOC_ORDER if (DATA / CHANNEL_API / f"{d}.pdf").exists()]
    r = integ.post("/integrations/v1/claims", data={"metadata": json.dumps(claim_body(case))}, files=files)
    r.raise_for_status()
    ids.append(r.json()["claim_id"])
    print(f"  API multipart: {CHANNEL_API} diterima ({len(files)} dokumen)")

    inbox = SFTP_ROOT / "PELITA" / "masuk"
    inbox.mkdir(parents=True, exist_ok=True)
    tmp = inbox / "kiriman_demo.zip.part"
    tmp.write_bytes(_sftp_zip(CHANNEL_SFTP))
    tmp.rename(inbox / "kiriman_demo.zip")
    print(f"  SFTP: {inbox / 'kiriman_demo.zip'} ditaruh, menunggu sftp-watcher…")
    deadline = time.monotonic() + int(os.environ.get("SEED_SFTP_TIMEOUT", "90"))
    while time.monotonic() < deadline:
        found = {c["claim_number"]: c["id"] for c in staf_pelita.get("/claims", params={"limit": 500})
                 if c["claim_number"] in CHANNEL_SFTP}
        if len(found) == len(CHANNEL_SFTP):
            ids += list(found.values())
            print(f"  SFTP: {', '.join(CHANNEL_SFTP)} diterima")
            break
        time.sleep(3)
    else:
        print("  PERINGATAN: ZIP SFTP belum diproses. Pastikan layanan sftp-watcher jalan (`docker compose up -d sftp-watcher`).")
    return ids


def link_accounts() -> None:
    facility = json.loads((DATA / FACILITY_FROM / "case.json").read_text(encoding="utf-8"))["hospital"]["name"]
    member = json.loads((DATA / MEMBER_FROM / "case.json").read_text(encoding="utf-8"))["patient"]["member_id"]
    link_portal_accounts(facility, member)
    print(f"  akun faskes -> {facility}; akun peserta -> {member} (klaim {MEMBER_FROM})")


def wait_processing(staf: Api, ids: list[str]) -> None:
    start = time.monotonic()
    while True:
        statuses = {c["id"]: c["status"] for c in staf.get("/claims", params={"limit": 500})}
        busy = [i for i in ids if statuses.get(i) in ("RECEIVED", "QUEUED", "PROCESSING")]
        done = len(ids) - len(busy)
        print(f"  diproses worker: {done}/{len(ids)}", end="\r", flush=True)
        if not busy:
            print()
            failed = [i for i in ids if statuses.get(i) == "FAILED"]
            if failed:
                print(f"  PERINGATAN: {len(failed)} klaim gagal diproses (lihat `make logs`).")
            return
        if time.monotonic() - start > TIMEOUT:
            sys.exit(f"\nWorker belum selesai setelah {TIMEOUT} detik. Cek `docker compose logs worker`.")
        time.sleep(3)


def sign(doctor: Api, claim_id: str, body: dict) -> None:
    doctor.post(f"/review/{claim_id}/start")
    doctor.post(f"/review/{claim_id}/sign", json={**body, "pin": PIN})


def doctor_reviews() -> None:
    gp = Api("dokter.umum@mab.test")
    sp = Api("dokter.spesialis@mab.test")

    # Hanya klaim tenant DEMO yang ditelaah; klaim PELITA dibiarkan di antrean untuk demo SLA.
    # Dokter umum: eskalasi satu kasus, setujui draf sisanya kecuali dua kasus terakhir (tetap di antrean).
    # SYN-TIF-10 ditangani tersendiri di langkah U4 (late_documents_demo).
    gp_queue = [i for i in gp.get("/review/queue")
                if i["insurer_name"] == "Asuransi Sehat Demo" and i["claim_number"] not in (LATE_DOCS_CLAIM, DISPUTE_CLAIM)]
    for i, item in enumerate(gp_queue[:-2] if len(gp_queue) > 2 else []):
        if i == 0:
            gp.post(f"/review/{item['id']}/start")
            gp.post(f"/review/{item['id']}/escalate", json={"notes": "Mohon pendapat spesialis sebelum tanda tangan (contoh eskalasi demo)."})
            print(f"  dokter umum mengeskalasi {item['claim_number']}")
            continue
        ws = gp.get(f"/review/{item['id']}")
        sign(gp, item["id"], dict(ws["suggestion"]))
        print(f"  dokter umum menyetujui draf {item['claim_number']}")

    # Spesialis: kasus merah selain eskalasi; satu diubah, dua terakhir dibiarkan di antrean.
    sp_queue = [i for i in sp.get("/review/queue") if not i["escalated"] and i["insurer_name"] == "Asuransi Sehat Demo"
                and i["claim_number"] != DISPUTE_CLAIM]
    for i, item in enumerate(sp_queue[:-2] if len(sp_queue) > 2 else []):
        ws = sp.get(f"/review/{item['id']}")
        sugg = dict(ws["suggestion"])
        if i == 0 and sugg["recommendation"] == "PEND" and ws["draft"]["findings"]:
            amount = int(ws["draft"]["billed_amount"] * 0.8)
            body = {"recommendation": "PAY_PARTIAL", "recommended_amount": amount,
                    "reason_code": ws["draft"]["findings"][0]["code"],
                    "notes": "Contoh demo: dokter memilih bayar sebagian, bukan menunda."}
            sign(sp, item["id"], body)
            print(f"  spesialis mengubah draf {item['claim_number']} menjadi bayar sebagian")
        else:
            sign(sp, item["id"], sugg)
            print(f"  spesialis menyetujui draf {item['claim_number']}")


def insurer_decisions(staf: Api) -> None:
    ready = [c for c in staf.get("/claims", params={"limit": 500, "status": "AWAITING_DECISION"})
             if c["claim_number"] not in (LATE_DOCS_CLAIM, DISPUTE_CLAIM)]
    greens = [c for c in ready if c["triage_status"] == "GREEN" and c["recommendation"] == "PAY_FULL"]
    others = [c for c in ready if c not in greens]
    to_agree = [c["id"] for c in greens[:-3]] if len(greens) > 3 else []
    if to_agree:
        r = staf.post("/claims/decisions/bulk-agree", json={"claim_ids": to_agree})
        print(f"  asuransi menyetujui massal {len(r['agreed'])} klaim hijau ({len(greens) - len(to_agree)} dibiarkan)")
    for i, c in enumerate(others[:-1] if len(others) > 1 else []):
        if i == 0:
            body = {"decision": "DIFFER", "reason": "Contoh demo: perusahaan meminta klarifikasi tambahan sesuai kebijakan polis."}
        else:
            body = {"decision": "AGREE"}
        staf.post(f"/claims/{c['id']}/decision", json=body)
        print(f"  asuransi {'berbeda' if body['decision'] == 'DIFFER' else 'setuju'}: {c['claim_number']}")


def fraud_history() -> None:
    """U3: impor riwayat klaim berpola fraud ke kedua tenant; impor otomatis menjalankan analisis."""
    from synthetic.generate_fraud import HISTORY_FILE, write_outputs

    history = DATA / "fraud" / HISTORY_FILE
    if not history.exists():
        history, _ = write_outputs(DATA / "fraud")
        print(f"  riwayat klaim sintetis dibuat: {history}")
    admin = Api(ADMIN)
    for t in admin.get("/tenants"):
        if t["code"] not in PLANS:
            continue
        res = admin.post("/fraud/records/import", data={"insurer_id": t["insurer_id"]},
                         files={"file": (history.name, history.read_bytes(), "text/csv")})
        run = res.get("run") or {}
        print(f"  {t['code']}: {res['created']} klaim riwayat, {run.get('record_count', 0)} klaim dianalisis, "
              f"{run.get('signal_count', 0)} sinyal fraud")


def late_documents_demo(staf: Api) -> None:
    """U4: SYN-TIF-10 ditunda dokter, asuransi meminta rincian tagihan ke RS. Faskes mengunggahnya saat demo."""
    claim = next((c for c in staf.get("/claims", params={"limit": 500}) if c["claim_number"] == LATE_DOCS_CLAIM), None)
    if claim is None:
        print(f"  {LATE_DOCS_CLAIM} tidak ditemukan; langkah U4 dilewati")
        return
    if claim["status"] == "AWAITING_DOCTOR":
        gp = Api("dokter.umum@mab.test")
        ws = gp.get(f"/review/{claim['id']}")
        if not ws.get("can_start"):
            print(f"  PERINGATAN: {LATE_DOCS_CLAIM} tidak bisa ditelaah dokter umum ({ws.get('blocked_reason')})")
            return
        sign(gp, claim["id"], {"recommendation": "PEND",
                               "notes": "Rincian tagihan tidak ada; nilai klaim belum bisa dinilai."})
        print(f"  dokter umum menunda {LATE_DOCS_CLAIM} (rincian tagihan tidak ada)")
    detail = staf.get(f"/claims/{claim['id']}")
    if detail["status"] == "AWAITING_DECISION" and not detail["decision"]:
        staf.post(f"/claims/{claim['id']}/decision", json={
            "decision": "AGREE", "doc_types": ["rincian_tagihan"],
            "message": "Mohon kirimkan rincian tagihan perawatan supaya klaim bisa dinilai."})
        print(f"  asuransi setuju menunda {LATE_DOCS_CLAIM} dan meminta rincian tagihan ke RS")
    late = DATA / LATE_DOCS_CLAIM / "susulan" / "rincian_tagihan.pdf"
    if late.exists():
        print(f"  dokumen susulan untuk demo: {late}")
    else:
        print("  PERINGATAN: dokumen susulan belum ada. Jalankan ulang `docker compose run --rm --build synthetic`.")


def dispute_demo(staf: Api) -> None:
    """U5: SYN-GEA-06 diputus "tidak dijamin" (spesialis + asuransi setuju). Faskes membandingnya saat demo."""
    claim = next((c for c in staf.get("/claims", params={"limit": 500}) if c["claim_number"] == DISPUTE_CLAIM), None)
    if claim is None:
        print(f"  {DISPUTE_CLAIM} tidak ditemukan; langkah U5 dilewati")
        return
    sp = Api("dokter.spesialis@mab.test")
    if claim["status"] == "AWAITING_DOCTOR":
        ws = sp.get(f"/review/{claim['id']}")
        if not ws.get("can_start") and ws.get("level") == "GP":
            gp = Api("dokter.umum@mab.test")
            gp.post(f"/review/{claim['id']}/start")
            gp.post(f"/review/{claim['id']}/escalate", json={"notes": "Indikasi rawat inap perlu dinilai spesialis."})
            ws = sp.get(f"/review/{claim['id']}")
        if not ws.get("can_start"):
            print(f"  PERINGATAN: {DISPUTE_CLAIM} tidak bisa ditelaah spesialis ({ws.get('blocked_reason')})")
            return
        sign(sp, claim["id"], {
            "recommendation": "NOT_COVERED",
            "reason_code": "ADMISSION_NOT_INDICATED",
            "notes": "Dehidrasi ringan-sedang tanpa tanda bahaya; rawat inap tidak diindikasikan, perawatan tidak dijamin.",
        })
        print(f"  spesialis menandatangani {DISPUTE_CLAIM}: tidak dijamin")
    detail = staf.get(f"/claims/{claim['id']}")
    if detail["status"] == "AWAITING_DECISION" and not detail["decision"]:
        staf.post(f"/claims/{claim['id']}/decision", json={"decision": "AGREE"})
        print(f"  asuransi setuju: {DISPUTE_CLAIM} tidak dijamin. Siap dibanding faskes saat demo")
    if seed_users():
        print(f"  akun {SECOND_SPECIALIST} dibuat (spesialis kedua untuk telaah banding)")


def reports_demo() -> None:
    """U6: penjadwal (bulan lalu) + laporan bulan berjalan untuk tenant DEMO."""
    from datetime import datetime, timezone

    made = Api(ADMIN).post("/reports/run-schedule")["created"]
    print(f"  penjadwal: {len(made)} laporan bulan lalu dibuat (tiap tenant + seluruh platform)")
    now = datetime.now(timezone.utc)
    rep = Api("manajer@demo.test").post("/reports", json={"period": f"{now.year:04d}-{now.month:02d}"})
    print(f"  laporan {rep['period']} {rep['insurer_name']} dibuat (periode berjalan, revisi {rep['revision']})")


UW_DATA = DATA / "underwriting"
UW_UPLOAD = ["UW-01", "UW-02", "UW-09", "UW-14", "UW-21", "UW-22", "UW-25", "UW-26", "UW-28", "UW-33"]
UW_LIVE = "UW-24"   # IMT >= 40 + HbA1c tinggi: diunggah langsung saat demo
UW_SIGN = ["UW-09", "UW-22", "UW-28"]           # dokter umum menyetujui draf
UW_DECIDE = {"UW-01": "ACCEPT_STANDARD", "UW-09": "ACCEPT_CONDITIONAL", "UW-22": "DECLINE"}


def underwriting_demo() -> None:
    """U7: underwriter mengajukan 10 calon peserta sintetis; sebagian ditandatangani dokter dan diputuskan."""
    if not UW_DATA.exists():
        print(f"  {UW_DATA} tidak ada; jalankan ulang `docker compose run --rm --build synthetic`. Langkah U7 dilewati")
        return
    uw = Api("underwriter@demo.test")
    ids: dict[str, str] = {}
    for case in UW_UPLOAD:
        folder = UW_DATA / case
        files = [("files", (p.name, p.read_bytes(), "application/pdf")) for p in sorted(folder.glob("*.pdf"))]
        ids[case] = uw.post("/underwriting/applications", files=files)["id"]
    print(f"  {len(ids)} pengajuan diunggah ({UW_LIVE} sengaja belum, untuk demo langsung)")
    deadline = time.time() + TIMEOUT
    while True:
        items = {a["id"]: a for a in uw.get("/underwriting/applications")["items"]}
        pending = [i for i in ids.values() if items[i]["status"] in ("QUEUED", "PROCESSING")]
        if not pending:
            break
        if time.time() > deadline:
            sys.exit(f"Pengajuan underwriting belum selesai diproses: {len(pending)}")
        time.sleep(2)
    for case, app_id in ids.items():
        a = items[app_id]
        print(f"  {case}: {a['recommendation']} ({a['risk_class']}, loading {a['loading_pct']}%) -> {a['status']}")
    doctor = Api("dokter.umum@mab.test")
    for case in UW_SIGN:
        doctor.post(f"/underwriting/applications/{ids[case]}/sign", json={"action": "AGREE", "pin": PIN})
    print(f"  dokter umum menandatangani {', '.join(UW_SIGN)}")
    for case, decision in UW_DECIDE.items():
        uw.post(f"/underwriting/applications/{ids[case]}/decision", json={"decision": decision})
    print(f"  underwriter memutuskan {', '.join(f'{c} ({d})' for c, d in UW_DECIDE.items())}")


def main() -> None:
    print("1. Akun demo")
    # Spesialis kedua baru dibuat di langkah U5, supaya penugasan otomatis kasus merah di langkah awal
    # tetap ke satu spesialis (seperti seed sebelumnya).
    created = seed_users(skip=frozenset({SECOND_SPECIALIST}))
    print(f"  {len(created)} akun baru" if created else "  akun sudah ada")

    staf = Api("staf@demo.test")
    existing = [c for c in staf.get("/claims", params={"limit": 500}) if c["claim_number"].startswith("SYN-")]
    if existing:
        sys.exit("Klaim demo sudah ada. Jalankan `make reset` untuk mengosongkan data lalu seed ulang.")

    print("2. Polis, plan benefit, dan webhook (U2)")
    tenant_ids = setup_policies_and_webhooks()

    print("3. Unggah klaim sintetis")
    ids = upload_claims(staf)
    print("   Tenant kedua (Asuransi Pelita)")
    staf_pelita, pelita_ids = upload_second_tenant()
    print("   Kanal integrasi ke Asuransi Pelita (FHIR, API, SFTP)")
    pelita_ids += channel_demos(tenant_ids, staf_pelita)
    link_accounts()
    print("4. Menunggu worker memproses")
    wait_processing(staf, ids)
    wait_processing(staf_pelita, pelita_ids)
    print("5. Telaah dokter")
    doctor_reviews()
    print("6. Keputusan asuransi")
    insurer_decisions(staf)
    print("7. Riwayat klaim dan analisis fraud (U3)")
    fraud_history()
    print("8. Portal faskes & peserta: minta dokumen susulan (U4)")
    late_documents_demo(staf)
    print("9. Banding atas keputusan (U5)")
    dispute_demo(staf)
    print("10. Laporan bulanan dan audit (U6)")
    reports_demo()
    print("11. Underwriting medis (U7)")
    underwriting_demo()
    print(f"\nSelesai. Buka http://localhost:3000 (staf@demo.test / {PASSWORD}).")
    print(f"Klaim {LIVE_DEMO_CLAIM} sengaja belum diunggah ke tenant DEMO untuk diunggah langsung saat demo.")
    print(f"Tenant kedua: {SECOND_TENANT_STAFF} melihat {len(pelita_ids)} klaim Asuransi Pelita (ambang merah 20).")


if __name__ == "__main__":
    main()
