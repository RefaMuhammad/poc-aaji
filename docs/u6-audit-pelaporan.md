# U6 · Audit dan pelaporan OJK

Data rekaan untuk demonstrasi.

U6 menambahkan halaman **Laporan & Audit**. Halaman ini berisi tiga bagian:

- **Jejak keputusan** per klaim, untuk menelusuri satu keputusan dari unggah sampai keputusan akhir.
- **Log audit** dengan filter per klaim, pengguna, aksi, dan tanggal.
- **Laporan bulanan kepatuhan POJK 36/2025**. Laporan dibuat otomatis oleh penjadwal dan bisa diekspor ke PDF atau Excel.

| Peran | Laporan & Audit |
|---|---|
| Auditor internal (`auditor@demo.test`) | Hanya-baca, tenant sendiri: jejak, log audit, laporan, unduh PDF/Excel |
| Auditor regulator (`auditor@ojk.test`) | Hanya-baca, semua tenant, termasuk laporan seluruh platform |
| Manajer klaim (`manajer@demo.test`) | Seperti auditor tenant, ditambah membuat atau membuat ulang laporan |
| Admin MAB | Semua tenant, laporan seluruh platform, menjalankan penjadwal manual |

Staf klaim, TPA, dokter, faskes, dan peserta tidak punya akses. Auditor tetap tidak bisa menulis apa pun:
tidak bisa memutuskan klaim, membuat laporan, atau mengubah data.

## POJK 36/2025 dan isi templat

Templat dicocokkan dengan teks POJK 36/2025 (Penguatan Ekosistem Asuransi Kesehatan, diundangkan
22 Desember 2025, berlaku 3 bulan kemudian). Dari teks yang bisa dibaca di
[pasal.id](https://pasal.id/peraturan/pojk/peraturan-ojk-no-36-tahun-2025) dan
[halaman regulasi OJK](https://ojk.go.id/id/regulasi/Pages/POJK-36-Tahun-2025-Penguatan-Ekosistem-Asuransi-Kesehatan.aspx):

- **Tidak ada pasal yang menetapkan laporan berkala ke OJK** (bulanan, triwulanan, atau tahunan), dan
  tidak ada format laporannya. PDF resmi tidak bisa diunduh saat pengecekan. Teks Pasal 7, 10, dan 27
  di pasal.id terpotong, jadi kesimpulan ini perlu dicek ulang dengan PDF resmi.
- Karena itu laporan ini **bukan formulir OJK**. Isinya adalah **laporan kepatuhan internal** yang
  membuktikan kewajiban POJK yang dijalankan platform. Templatnya diberi versi `pojk36-draf-1` dan
  setiap laporan memuat catatan bahwa isinya wajib dicocokkan dengan format yang diminta OJK atau klien.

| Bagian | Isi | Dasar |
|---|---|---|
| A. Identitas | Perusahaan, periode, versi templat, sumber data | |
| B. Layanan klaim | Klaim diterima dan diputus, waktu proses, nilai tagihan dan koreksi, kanal masuk, hasil rekomendasi | Indikator umum |
| C. Telaah Utilisasi | Klaim dinilai sistem, ditandatangani dokter, kesesuaian dengan draf AI, eskalasi, telaah dalam SLA, temuan dan kode alasan | Pasal 29 dan 30 |
| D. Dewan Penasihat Medis | Dokter panel aktif, bidang, aktivitas per dokter, telaah ulang banding | Pasal 8 dan 9 |
| E. Pengendalian fraud | Analisis terakhir, sinyal per aturan, status telaah investigator | Tata kelola (U3) |
| F. Sengketa dan banding | Banding diajukan dan diputus, SLA, keputusan berubah, hasil, kategori | Perlindungan konsumen (Pasal 47) |
| G. Kapabilitas digital dan data | Klaim lewat integrasi, permintaan dokumen lewat sistem, entri log audit, akses dokumen, log tak dapat diubah, retensi | Pasal 5 ayat (1) huruf b dan Pasal 7 |
| H. Diisi asuransi | Pembagian risiko (Pasal 24), peninjauan premi (Pasal 21–23), koordinasi BPJS (Pasal 42–43), kerja sama DPM/TPA | Di luar data platform |

Batas waktu penyesuaian produk dan izin asuransi kesehatan yang sudah ada adalah 1 tahun sejak diundangkan
(Pasal 50), yaitu sekitar 22 Desember 2026.

## Jejak keputusan (syarat selesai U6)

Auditor membuka **Laporan & Audit**, mengetik nomor klaim di "Telusuri keputusan klaim", lalu membuka
halaman jejak. Tombol **Jejak audit** di detail klaim membuka halaman yang sama. Halaman jejak berisi:

1. **Mata rantai keputusan**: keputusan akhir dan siapa yang mencatatnya, rekomendasi dan versinya, dokter
   penanda tangan dan kode alasannya, draf sistem (triase, skor, temuan, versi model, prompt, dan aturan),
   banding bila ada, dan dokumen sumber.
2. **Linimasa** per tahap: penerimaan, pemrosesan sistem, telaah dokter, keputusan asuransi, dokumen
   susulan, banding, dan akses dokumen. Tiap tahap bisa disaring.
3. **Dokumen sumber** dengan sidik SHA-256.
4. **Entri log audit mentah** untuk klaim itu.

Semuanya bisa diunduh sebagai PDF. Ekspor jejak juga tercatat di log audit (`AUDIT_TRACE_EXPORTED`).

## Log audit

- **Filter:** nomor klaim, pengguna (nama atau email), kelompok aksi (telaah dokter, keputusan, banding,
  dan lainnya), kode aksi, dan rentang tanggal (inklusif).
- **Tampilan:** aksi ditampilkan dengan label yang terbaca. Klik satu baris untuk melihat rinciannya
  (metode, path, IP, detail JSON).
- **Ekspor:** Excel sampai 5.000 baris sesuai filter (`AUDIT_LOG_EXPORTED`).
- **Cakupan:** auditor dan manajer tenant melihat log klaim tenantnya dan aktivitas pengguna tenantnya.
  Auditor regulator dan admin melihat semuanya.
- **Tidak dapat diubah:** di PostgreSQL, log audit tetap ditolak untuk diubah atau dihapus oleh trigger
  `audit_logs_no_change`.

## Penjadwal laporan

Layanan docker compose `report-scheduler` (`python -m mab_api.report_scheduler`) memeriksa setiap jam
(`REPORT_CHECK_SECONDS`). Bila laporan bulan lalu belum ada, ia membuat satu laporan per tenant dan satu
untuk seluruh platform (`trigger=SCHEDULED`). Laporan yang sudah ada tidak dibuat ulang, jadi layanan aman
dimulai ulang kapan saja. Untuk cron, pakai `python -m mab_api.report_scheduler --once`.

Laporan juga bisa dibuat manual oleh manajer atau admin, termasuk untuk periode berjalan. Laporan periode
berjalan ditandai **sementara**. Membuat ulang periode yang sama menaikkan nomor **revisi**. Isi laporan
dibekukan di tabel `reports`, jadi laporan yang sudah diunduh tidak berubah walau data berubah.

## API

| Endpoint | Peran |
|---|---|
| `GET /audit/logs?claim_id=&claim_number=&user=&action=&group=&date_from=&date_to=&limit=&offset=` | auditor, manajer, admin |
| `GET /audit/logs/xlsx` (filter sama) | auditor, manajer, admin |
| `GET /audit/claims/{id}/trace`, `GET /audit/claims/{id}/trace/pdf` | auditor, manajer, admin (sesuai akses klaim) |
| `GET /reports`, `GET /reports/{id}`, `GET /reports/{id}/pdf`, `GET /reports/{id}/xlsx` | auditor, manajer, admin |
| `POST /reports` (`period` YYYY-MM, `insurer_id` opsional) | manajer, admin |
| `POST /reports/run-schedule` | admin |

Izin baru di `rbac.py`: `AUDIT_VIEW` dan `REPORT_VIEW` (auditor, manajer, admin), serta
`REPORT_GENERATE` (manajer, admin). Peristiwa audit baru: `REPORT_GENERATED`, `REPORT_DOWNLOADED`,
`AUDIT_TRACE_EXPORTED`, `AUDIT_LOG_EXPORTED`.

## Database (migrasi `0008`)

| Tabel / indeks | Isi |
|---|---|
| `reports` | `kind` (POJK36_MONTHLY), `period`, `insurer_id` (kosong = seluruh platform), `scope_key`, `template_version`, `revision`, `trigger` (SCHEDULED/MANUAL), `partial`, `data` (isi beku), `generated_by_id`, `generated_at`; unik per jenis + periode + cakupan |
| `ix_audit_logs_action` | Indeks untuk filter aksi |

## Demo

1. Ambil kode terbaru dan buat ulang data:
   ```powershell
   git pull origin dev
   docker compose down -v
   docker compose up -d --build
   docker compose run --rm --build synthetic
   docker compose exec -T api python infra/scripts/seed_demo.py
   ```
   Di akhir seed, penjadwal sudah dijalankan sekali dan laporan bulan berjalan tenant DEMO sudah dibuat.
2. Masuk sebagai `auditor@demo.test` dan buka **Laporan & Audit**. Ketik `SYN-GEA-06` di "Telusuri keputusan
   klaim". Baca mata rantai keputusannya, lalu ikuti linimasa dari unggah sampai keputusan. Bila banding
   U5 sudah didemokan, linimasa juga memuat banding dan putusan ulangnya. Unduh PDF jejak.
3. Di tab **Log audit**, saring dengan kelompok "Telaah dokter" atau pengguna `dokter.spesialis`, lalu ekspor
   ke Excel.
4. Di tab **Laporan bulanan**, buka laporan bulan berjalan, lalu unduh PDF dan Excel. Auditor tidak melihat
   tombol "Buat laporan".
5. Masuk sebagai `manajer@demo.test` untuk membuat ulang laporan (revisi naik). Masuk sebagai
   `auditor@ojk.test` untuk melihat laporan kedua tenant dan laporan seluruh platform.

## Batasan POC

- Templat masih draf. Belum ada format resmi dari OJK atau klien. Setelah format ada, templat diberi versi
  baru dan laporan lama tetap dengan versinya.
- Laporan berupa PDF dan Excel untuk diunduh. Belum ada pengiriman otomatis (email atau portal OJK).
- Periode laporan memakai bulan kalender UTC, belum WIB.
- Retensi data 10 tahun (Pasal 7) belum diterapkan.
- Penampil log memuat log ke memori sebelum menyaring per kelompok. Untuk data sungguhan dibutuhkan paginasi
  di database dan arsip log.
