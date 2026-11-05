# U2 · Integrasi & benefit

Fase kedua upgrade POC menuju MAB-as-a-Service. U2 membuka tiga jalur klaim masuk dari sistem inti
asuransi/TPA (**REST API**, **SFTP batch**, **FHIR R4**), mengirim hasil balik lewat **webhook** dan
**CSV di folder SFTP**, dan menambah **aturan benefit polis** (polis aktif, masa tunggu, pengecualian,
limit, kelas kamar). Semua data tetap **rekaan untuk demonstrasi**.

Kriteria selesai dari plan:

- [x] Satu klaim sintetis bisa masuk lewat API, SFTP, dan FHIR Bundle
  (`make seed`: SYN-GEA-01 lewat API, SYN-TIF-01/02 lewat SFTP, SYN-DEN-01 lewat FHIR, semua ke Asuransi Pelita).
- [x] Hasil kembali lewat webhook (bertanda tangan HMAC) dan CSV di folder SFTP `keluar/`.
- [x] Temuan benefit baru tampil di rekomendasi dengan bukti dari data polis (`tests/test_u2_integrasi.py`).

## 1. Aturan benefit polis

File: `rules/aturan_benefit_demo.yaml` (versi `benefit-2026.11-demo`). Formatnya sama dengan aturan klinis
dan dinilai oleh evaluator yang sama, tetapi hanya boleh memakai field `policy.*` dan `benefit.*`.

| Aturan | Kondisi | Kode alasan | Keparahan | Koreksi tagihan |
|---|---|---|---|---|
| BEN-00 | Peserta tidak ada di data polis tenant | POLICY_NOT_FOUND | Sedang | |
| BEN-01 | Polis tidak aktif / di luar masa berlaku saat masuk rawat | POLICY_INACTIVE | Berat | |
| BEN-02 | Masuk rawat masih dalam masa tunggu plan | WAITING_PERIOD | Sedang | |
| BEN-03 | Diagnosis utama/sekunder diawali kode pengecualian plan | EXCLUDED_CONDITION | Berat | |
| BEN-04 | Tagihan melebihi sisa limit tahunan | LIMIT_EXCEEDED | Sedang | bagian di atas sisa limit |
| BEN-05 | Tarif kamar per hari melebihi hak plan | ROOM_CLASS_EXCEEDED | Ringan | (tarif − batas) × hari |

- Aturan benefit **hanya dijalankan bila tenant sudah punya data polis**. Tenant tanpa polis tidak berubah perilakunya.
- Temuan benefit digabung dengan temuan klinis sebelum triase, jadi ikut menentukan skor dan status
  (dan tetap tunduk pada ambang triase tenant). AI tetap tidak pernah menolak klaim: selain bayar penuh,
  rekomendasi wajib ditandatangani dokter.
- Bukti temuan benefit adalah kutipan data polis (mis. "Polis POL-… (plan …): status ACTIVE, berlaku …")
  dan, untuk kelas kamar, baris kamar di rincian tagihan yang bisa diklik.
- Setiap rekomendasi mencatat `benefit_ruleset_version`. Aturan BEN-xx bisa dimatikan per tenant seperti aturan klinis.
- Fakta `policy.*` dan `benefit.*` disimpan bersama field hasil baca (sumber `polis`), jadi terlihat di ruang kerja dokter.

## 2. Polis dan plan benefit

Halaman **Polis** (`/polis`; staf, manajer, TPA, auditor baca saja, admin):

- **Plan benefit**: kode, hak kelas kamar, batas tarif kamar per hari, limit tahunan, masa tunggu, awalan ICD-10 yang dikecualikan.
- **Impor polis** CSV/XLSX, kolom `nomor_polis, id_peserta, nama_peserta, kode_plan, tanggal_mulai, tanggal_akhir, status, limit_terpakai`.
  Baris yang salah dilewati dan dilaporkan; polis yang sama (nomor polis + peserta) diperbarui. Templat: **Unduh templat CSV**.
- Sistem inti juga bisa mengirim polis lewat API: `PUT /integrations/v1/policies` (cakupan `policies:write`).
- Polis yang dipakai sebuah klaim tampil di detail klaim (kartu **Polis dan benefit**).

Pencocokan polis: nomor polis + id peserta sama; bila tidak ada, polis peserta yang masa berlakunya mencakup tanggal masuk; bila tidak ada, polis terbaru peserta itu.

## 3. Klaim masuk lewat API (REST)

Kunci API dengan cakupan `claims:write` (halaman **Tenant & API key**, centang cakupannya).

```powershell
$KEY = Get-Content data\demo_upload\api_key_PELITA.txt   # dibuat oleh make seed
$META = '{"claim_number":"API-001","policy_number":"POL-DEMO-1","member_id":"PST-23439350","hospital_name":"RS rekaan","admission_date":"2026-05-01","discharge_date":"2026-05-04","billed_amount":2568000}'
curl.exe -H "X-API-Key: $KEY" -F "metadata=$META" `
  -F "files=@data/synthetic_output/SYN-GEA-01/resume_medis.pdf" `
  -F "files=@data/synthetic_output/SYN-GEA-01/rincian_tagihan.pdf" `
  http://localhost:8000/integrations/v1/claims
```

Respons `202` berisi `claim_id`, `status: QUEUED`, `source: API`. Nomor klaim ganda → `409`. Hasilnya dibaca dengan
`GET /integrations/v1/claims/{nomor}` atau diterima lewat webhook. Dokumentasi OpenAPI lengkap: http://localhost:8000/docs (tag *integrasi*).

## 4. Klaim masuk lewat FHIR R4

`POST /integrations/v1/fhir` (cakupan `claims:write`) menerima `Bundle` berisi:

| Resource | Dipetakan ke |
|---|---|
| Patient | `identifier` = id peserta, `name` = nama |
| Coverage | `subscriberId` / `identifier` = nomor polis |
| Encounter | `period.start/end` = tanggal masuk/keluar, `serviceProvider.display` = nama RS |
| Claim | `identifier` = nomor klaim, `total.value` = nilai tagihan, `diagnosis` ICD-10 = petunjuk diagnosis awal |
| Observation | diterima dan dihitung; nilai lab tetap dibaca dari dokumen supaya setiap temuan punya kutipan |
| DocumentReference | `content.attachment.data` (base64 PDF/JPG/PNG) = dokumen klaim |

Bundle divalidasi dengan pustaka `fhir.resources` sebelum dipetakan; Bundle tidak valid → `422` dan tercatat di riwayat integrasi.
Contoh Bundle sintetis:

```powershell
docker compose exec api python infra/scripts/make_fhir_bundle.py SYN-DEN-01
curl.exe -H "X-API-Key: $KEY" -H "Content-Type: application/fhir+json" --data-binary "@data/demo_upload/fhir_SYN-DEN-01.json" http://localhost:8000/integrations/v1/fhir
```

Hasil dalam format FHIR: `GET /integrations/v1/fhir/ClaimResponse/{nomor}` (`outcome` queued/complete/error,
`total` submitted dan benefit, kode alasan di `processNote`). Rekomendasi hanya terisi bila sudah dirilis ke asuransi.

## 5. Klaim batch lewat SFTP

`docker compose up` kini menjalankan `sftp` (port 2222) dan `sftp-watcher`.

| Tenant | Login SFTP | Folder di laptop |
|---|---|---|
| Asuransi Sehat Demo | `demo` / `demo12345` | `data/sftp/DEMO/` |
| Asuransi Pelita Demo | `pelita` / `demo12345` | `data/sftp/PELITA/` |

```powershell
sftp -P 2222 pelita@localhost
sftp> cd data/masuk
sftp> put data/demo_upload/unggah_massal_demo.zip
```

- `masuk/`: ZIP berisi `manifest.xlsx` + satu folder per klaim (format sama dengan unggah massal di portal; buat dengan `infra/scripts/make_demo_zip.py`).
  Bisa juga langsung menyalin ZIP ke `data/sftp/PELITA/masuk/` di laptop.
- Pengawas memeriksa folder setiap 10 detik, menunggu ukuran file stabil, lalu memproses.
- `keluar/hasil_<nama zip>.csv`: baris diterima/ditolak beserta alasannya.
- `keluar/status_klaim.csv`: status semua klaim SFTP tenant itu, diperbarui terus (rekomendasi hanya bila sudah dirilis).
- `diproses/` berisi ZIP yang selesai; `gagal/` berisi ZIP yang tidak bisa dibaca beserta `.error.txt`.

## 6. Webhook keluar

Atur di **Tenant & API key → Webhook ke sistem asuransi**: URL penerima dan rahasia tanda tangan.

| Peristiwa | Kapan |
|---|---|
| `claim.recommendation_released` | Rekomendasi boleh dilihat asuransi: bayar penuh, atau sudah ditandatangani dokter |
| `claim.decision_recorded` | Asuransi mencatat keputusan (termasuk setuju massal) |
| `claim.processing_failed` | Pipeline gagal memproses klaim |

- Header: `X-MAB-Event`, `X-MAB-Delivery`, `X-MAB-Signature: sha256=<HMAC-SHA256 body mentah dengan rahasia>`.
- Payload: `event`, `delivery_id`, `occurred_at`, `tenant`, `claim` (sama dengan `GET /integrations/v1/claims/{nomor}`), `label`.
- Dikirim worker (RQ) dengan 3 percobaan (jeda 10 dan 60 detik). Riwayat dan tombol **Kirim ulang** ada di halaman tenant dan halaman Polis.
- Draf yang menunggu dokter **tidak pernah** dikirim.
- **Penerima demo**: `POST /integrations/demo-sink/{KODE}` berperan sebagai sistem inti rekaan, memeriksa tanda tangan,
  dan mencatatnya. `make seed` mengarahkan webhook kedua tenant ke sini; isinya tampil di bagian
  "Diterima penerima demo" di riwayat integrasi.

## 7. Data seed U2

`make seed` sekarang juga:

1. Membuat plan dan polis rekaan untuk semua peserta sintetis di kedua tenant (berlaku 1 Jul 2025 s.d. 31 Des 2026).
   - DEMO: satu plan "Sehat Rawat Inap Kelas 1" (kamar maks. Rp500.000/hari); semua klaim DEMO bersih dari temuan benefit.
   - Pelita: SYN-DEN-02 memakai plan **kelas 2** (maks. Rp300.000/hari) sehingga muncul BEN-05 dan koreksi selisih kamar;
     SYN-GEA-02 limit terpakai Rp48 juta dari Rp50 juta sehingga muncul BEN-04 (merah di Pelita karena ambang 20).
2. Mengarahkan webhook DEMO dan Pelita ke penerima demo.
3. Membuat API key Pelita (`claims:read`, `claims:write`, `policies:write`) dan menyimpannya di `data/demo_upload/api_key_PELITA.txt`.
4. Mengirim klaim ke Pelita lewat tiga kanal: SYN-DEN-01 (FHIR), SYN-GEA-01 (API), SYN-TIF-01 dan SYN-TIF-02 (ZIP ke folder SFTP).

## 8. Skenario demo U2 (± 6 menit)

1. Login `staf@pelita.test` → **Polis**: dua plan, polis peserta, riwayat integrasi (impor polis, FHIR, API, SFTP) dan webhook terkirim.
2. **Daftar klaim** → buka SYN-DEN-01: label *via FHIR*. Buka SYN-GEA-01: *via API*. SYN-TIF-01: *via SFTP*.
3. Ganti peran ke dokter spesialis → buka SYN-GEA-02 milik Pelita: temuan **BEN-04** dengan kutipan data polis dan usulan koreksi
   bagian di atas sisa limit. SYN-DEN-02 Pelita: **BEN-05** dengan baris kamar di rincian tagihan.
4. Tanda tangani salah satu → di **Polis → Riwayat integrasi** muncul webhook `claim.recommendation_released` dan isi yang diterima penerima demo.
5. Di laptop, buka `data/sftp/PELITA/keluar/status_klaim.csv`: status SYN-TIF-01/02.
6. PowerShell: `curl.exe -H "X-API-Key: $KEY" http://localhost:8000/integrations/v1/fhir/ClaimResponse/SYN-DEN-01`.

## 9. Perubahan teknis ringkas

- Migrasi `0004`: tabel `benefit_plans`, `policies`, `integration_jobs`, `webhook_deliveries`; kolom `claims.source`,
  `claims.api_client_id`, `claims.policy_id`, `tenant_settings.webhook_url/webhook_secret`, `recommendations.benefit_ruleset_version`;
  `claims.created_by_id` dan `documents.uploaded_by_id` boleh kosong (data dari integrasi).
- Pipeline: modul `mab_pipeline/benefit/` (loader, fakta, penilaian, koreksi); `assess_claim` menerima polis; `sftp_watcher.py`;
  job `deliver_webhook`.
- API: `policies.py`, `batch.py` (ZIP + manifest dipakai portal dan SFTP), `fhir.py`, `webhooks.py`; router `policies`,
  endpoint integrasi baru; izin `policy.view` / `policy.manage`.
- Web: halaman `/polis`, pengaturan webhook dan cakupan API key, riwayat integrasi, kanal & polis di detail klaim, aturan benefit di admin.
- Tes: `tests/test_u2_integrasi.py`.
