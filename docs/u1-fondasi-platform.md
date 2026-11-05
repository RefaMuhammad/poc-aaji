# U1 · Fondasi platform

Fase pertama upgrade POC menuju MAB-as-a-Service (lihat implementation plan). U1 menyiapkan
fondasi yang dipakai semua modul berikutnya: **tenant**, **peran baru**, **akun layanan + API key**,
dan **penugasan dokter otomatis dengan SLA**. Semua data tetap **rekaan untuk demonstrasi**.

Kriteria selesai dari plan:

- [x] Dua tenant demo berjalan berdampingan dengan logo dan ambang triase berbeda.
- [x] Tes akses membuktikan tidak ada data bocor antar tenant atau antar peran
  (`tests/test_rbac.py`, `tests/test_tenants.py`).

## 1. Dua tenant demo

`make seed` (atau `docker compose exec api python infra/scripts/seed_demo.py`) sekarang membuat dua asuransi:

| | Asuransi Sehat Demo (`DEMO`) | Asuransi Pelita Demo (`PELITA`) |
|---|---|---|
| Logo & warna | "SD", hijau tua | "PD", oranye |
| Ambang merah | bawaan file aturan (skor ≥ 40) | **skor ≥ 20** |
| Ambang kuning | bawaan (skor ≥ 10) | bawaan (skor ≥ 10) |
| SLA dokter umum / spesialis | 24 / 48 jam | 8 / 24 jam |
| Klaim hasil seed | 29 klaim sintetis (seperti sebelumnya) | 6 klaim: SYN-DEN-02, SYN-GEA-02, SYN-DEN-08, SYN-DEN-09, SYN-GEA-07, SYN-TIF-07 |

Karena ambang merah Pelita 20, satu temuan "sedang" (bobot 20) sudah membuat klaim **merah**.
Contoh dari uji seed: SYN-DEN-08, SYN-GEA-07, dan SYN-TIF-07 **kuning** di DEMO tetapi **merah** di Pelita,
sehingga langsung masuk antrean dokter spesialis dengan SLA 24 jam. SYN-DEN-09 (skor 30) merah di Pelita
dan, setelah diunggah langsung saat demo, kuning di DEMO.

Setiap rekomendasi mencatat versi aturan termasuk penyesuaian tenant, mis. `rules-2026.11-demo+PELITA.v1`.
Tenant tanpa penyesuaian tetap tercatat `rules-2026.11-demo`.

## 2. Akun demo baru

Password semua akun `demo12345`. Semua akun ada di pemilih **Ganti peran (demo)**.

| Peran | Email | Bisa apa (U1) |
|---|---|---|
| Staf klaim Pelita | `staf@pelita.test` | Sama seperti staf DEMO, hanya klaim Asuransi Pelita |
| Manajer klaim Pelita | `manajer@pelita.test` | Sama seperti manajer DEMO, hanya Pelita |
| Operator TPA | `tpa@mab.test` | Unggah & keputusan untuk DEMO **dan** Pelita; memilih asuransi saat unggah |
| Auditor internal | `auditor@demo.test` | Hanya-baca klaim DEMO: daftar, detail, rekomendasi yang sudah dirilis, dashboard, ekspor |
| Auditor regulator | `auditor@ojk.test` | Hanya-baca semua tenant |
| Petugas faskes | `faskes@demo.test` | Portal faskes: klaim dari RS-nya (RSU Harapan Bunda) lintas asuransi, unggah dokumen susulan (U4) |
| Peserta | `peserta@demo.test` | Portal peserta: status dan penjelasan klaim atas nomor pesertanya (peserta SYN-TIF-10 di DEMO, U4) |
| Underwriter | `underwriter@demo.test` | Underwriting medis tenant sendiri (U7); tidak melihat data klaim |

Portal faskes dan peserta (dokumen susulan, linimasa, penjelasan keputusan) dijelaskan di
[u4-portal-faskes-peserta.md](u4-portal-faskes-peserta.md).

## 3. Matriks hak akses

Sumber kebenaran: `apps/api/mab_api/rbac.py`. Cakupan data (tenant mana, RS mana, peserta mana) di `access.py`.

| Izin | Staf/manajer | TPA | Dokter | Auditor | Faskes | Peserta | Underwriter | Admin |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| Daftar & status klaim | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | | ✓ |
| Detail (field, dokumen, rekomendasi) | ✓ | ✓ | ✓ | ✓ | | | | ✓ |
| Unggah klaim | ✓ | ✓ | | | | | | |
| Keputusan asuransi | ✓ | ✓ | | | | | | |
| Ekspor CSV | ✓ | ✓ | | ✓ | | | | |
| Dashboard | ✓ | ✓ | | ✓ | | | | ✓ |
| Telaah & tanda tangan | | | ✓ | | | | | |
| Lihat aturan klinis | | | ✓ | ✓ | | | | ✓ |
| Lihat pengaturan tenant sendiri | ✓ | ✓ | | ✓ | | | | ✓ |
| Ubah tenant, API key, pindah penugasan | | | | | | | | ✓ |
| (U2) Lihat polis & plan benefit | ✓ | ✓ | | ✓ | | | | ✓ |
| (U2) Impor polis, ubah plan | ✓ | ✓ | | | | | | ✓ |
| (U3) Fraud Monitor, kartu fraud klaim | ✓ | ✓ | | ✓ | | | | ✓ |
| (U3) Impor riwayat, analisis, telaah sinyal fraud | manajer saja | | | | | | | ✓ |
| (U4) Portal faskes / peserta (status awam, linimasa, penjelasan) | | | | | ✓ | ✓ | | |
| (U4) Minta dokumen susulan, batalkan permintaan | ✓ | ✓ | | | | | | |
| (U4) Unggah dokumen susulan | ✓ | ✓ | | | ✓ | | | |
| (U4) Ringkasan TPA per asuransi | | ✓ | | | | | | ✓ |
| (U4) Kotak masuk notifikasi sendiri | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| (U5) Ajukan / tarik banding | | | | | ✓ | ✓ | | |
| (U5) Daftar sengketa, metrik banding | ✓ | ✓ | | ✓ | | | | ✓ |
| (U5) Telaah ulang banding (bukan penelaah awal) | | | ✓ | | | | | |
| (U6) Log audit, jejak keputusan, lihat & unduh laporan | manajer saja | | | ✓ | | | | ✓ |
| (U6) Buat / buat ulang laporan bulanan | manajer saja | | | | | | | ✓ |
| (U7) Lihat pengajuan underwriting | | | ✓ (antrean dokter) | ✓ | | | ✓ | ✓ |
| (U7) Ajukan dan putuskan underwriting | | | | | | | ✓ | |
| (U7) Telaah dan tanda tangan underwriting | | | ✓ | | | | | |

Prinsip yang tidak berubah:

- **Draf AI hanya untuk dokter dan admin.** Semua peran lain (termasuk TPA dan auditor) hanya melihat
  rekomendasi yang sudah dirilis: bayar penuh, atau sudah ditandatangani dokter.
- **Di luar cakupan = 404**, bukan 403, supaya keberadaan klaim tenant lain tidak bocor.
- Peran yang tidak dikenal tidak melihat klaim apa pun (default tolak).

## 4. Pengaturan per tenant

Halaman **Tenant & API key** (`/admin/tenant`, admin) atau `PUT /tenants/{insurer_id}/settings`.

| Pengaturan | Efek |
|---|---|
| Nama tampilan, logo, warna | Header portal pengguna tenant itu (logo maks. ~200 KB, PNG/JPEG/WEBP/SVG) |
| Ambang merah / kuning | Mengganti `skor_min` baris merah/kuning di bagian triase YAML. Temuan HIGH tetap merah dan dokumen wajib hilang tetap kuning |
| Aturan aktif | Aturan yang tidak dicentang tidak dinilai untuk tenant itu. Isi aturan tetap dari file YAML |
| SLA dokter umum / spesialis (jam) | Batas waktu antrean dokter |
| Penugasan otomatis | Bila mati, kasus masuk antrean bersama dan diambil dokter yang berhak |

- Ambang merah harus lebih besar dari ambang kuning (validasi 422).
- Setiap simpan menaikkan `version` dan tercatat di audit `TENANT_SETTINGS_UPDATED` (nilai sebelum dan sesudah).
- Perubahan berlaku untuk klaim yang **diproses setelah** disimpan; rekomendasi lama tidak dihitung ulang.

## 5. Penugasan dokter dan SLA

- Saat pipeline selesai dan klaim menunggu dokter, kasus langsung ditugaskan ke dokter yang berhak
  (dokter umum untuk kuning; spesialis sebidang untuk merah dan eskalasi) dengan **beban aktif paling sedikit**.
- **Lepas kasus** memindahkan ke dokter lain yang berhak (bila ada); **eskalasi** langsung ditugaskan ke spesialis.
- Admin bisa memindahkan kasus: `POST /admin/claims/{id}/assign` (`{"doctor_id": "..."}`).
- Batas SLA = saat masuk antrean (draf dibuat, atau saat dieskalasi) + jam SLA tenant untuk level itu.
- Antrean dokter menampilkan kolom **SLA**: *Sesuai SLA*, *Hampir lewat* (sisa ≤ 25%), *Lewat SLA*, plus sisa waktu.
  Kasus yang lewat SLA naik ke urutan teratas. Tab "sudah saya tanda tangani" menampilkan *Tepat waktu* / *Terlambat*.
- Riwayat penugasan di tabel `assignments` (AUTO / CLAIMED / MANUAL; ACTIVE, COMPLETED, RELEASED, ESCALATED, CANCELLED)
  dan audit `CASE_ASSIGNED`.

Pengingat SLA otomatis (email/notifikasi) belum ada. Penjadwal laporan U6 (`report-scheduler`) baru membuat laporan bulanan; pengingat SLA belum ditambahkan ke sana.

## 6. Akun layanan dan API key

Untuk sistem inti asuransi atau TPA yang ingin membaca status klaim tanpa login manusia.

1. Admin membuka **Tenant & API key**, memilih tenant, mengisi nama akun layanan, klik **Buat API key**.
2. Kunci (`mab_<prefix>_<rahasia>`) **hanya tampil sekali**. Yang disimpan hanya hash SHA-256-nya.
3. Kunci bisa **dicabut** kapan saja; kunci yang dicabut langsung ditolak (401).

Cakupan U1: `claims:read`. Endpoint (header `X-API-Key`), hanya klaim tenant pemilik kunci:

```powershell
$KEY = "mab_xxxxxxxx_...."   # dari halaman Tenant & API key
curl.exe -H "X-API-Key: $KEY" http://localhost:8000/integrations/v1/whoami
curl.exe -H "X-API-Key: $KEY" "http://localhost:8000/integrations/v1/claims?status=AWAITING_DECISION"
curl.exe -H "X-API-Key: $KEY" http://localhost:8000/integrations/v1/claims/SYN-DEN-02
```

Rekomendasi di respons hanya terisi bila sudah dirilis ke asuransi; draf yang menunggu dokter tidak bocor.
Setiap panggilan tercatat di audit `INTEGRATION_ACCESS`. Mengirim klaim lewat API, webhook keluar,
SFTP, dan FHIR dibangun di U2.

## 7. Skenario demo U1 (± 5 menit)

1. Login `admin@mab.test` → **Tenant & API key**. Tunjukkan dua tenant: logo, ambang merah Pelita 20,
   SLA 8/24 jam, daftar aturan aktif. Buat API key untuk Pelita, salin kuncinya.
2. **Ganti peran** → *6. Staf Asuransi Pelita*. Header berganti logo dan warna Pelita; hanya 6 klaim Pelita yang terlihat.
3. **Ganti peran** → *3. Dokter spesialis*. Antrean berisi kasus dari dua asuransi; SYN-DEN-08, SYN-GEA-07,
   dan SYN-TIF-07 milik Pelita ada di sini (merah karena ambangnya), dengan SLA 24 jam. Kolom SLA menunjukkan sisa waktu.
4. **Ganti peran** → *1. Staf klaim* (DEMO), unggah SYN-DEN-09: hasilnya **kuning** dan masuk ke dokter umum,
   sedangkan klaim yang sama di Pelita **merah**. Buka rekomendasinya: versi aturan menunjukkan tenant.
5. **Ganti peran** → *7. Operator TPA*: daftar klaim berisi kedua asuransi; di **Unggah klaim** ada pilihan asuransi.
6. **Ganti peran** → *8. Auditor*, *9. Petugas faskes*, *10. Peserta*: masing-masing hanya melihat cakupannya;
   auditor tidak bisa memutuskan, faskes dan peserta hanya melihat status.
7. Di PowerShell, panggil `/integrations/v1/claims` dengan API key tadi: hanya klaim Pelita yang kembali.

## 8. Perubahan teknis ringkas

- Migrasi `0003`: kolom `users.facility_name`, `users.member_ref`; tabel `user_tenants`, `tenant_settings`,
  `api_clients`, `assignments`.
- Modul baru: `rbac.py`, `tenancy.py`, `assignment.py`, router `tenants.py`, `integrations.py`.
- Pipeline (`tasks.py`): aturan dasar + penyesuaian tenant; penugasan otomatis setelah draf dibuat;
  penugasan lama dibatalkan saat klaim diproses ulang.
- Web: logo tenant di header, menu per peran, halaman `/admin/tenant`, kolom SLA di antrean, pilihan asuransi untuk TPA,
  halaman `/underwriting` (diisi modul underwriting medis di U7).
- Tes: `tests/test_rbac.py` (matriks peran × endpoint, isolasi tenant/peran), `tests/test_tenants.py`
  (pengaturan tenant, API key, penugasan, SLA).
