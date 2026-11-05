# MAB Indonesia POC (Tahap 0)

> **Data rekaan untuk demonstrasi.** Repo ini hanya memakai data sintetis. Aturan klinis masih draf dan belum divalidasi dokter. Jangan unggah data pasien sungguhan.

Platform yang membantu Dewan Penasihat Medis (MAB) menelaah klaim asuransi kesehatan rawat inap:

```
unggah berkas klaim → baca dokumen (PDF/OCR) → ekstraksi data → aturan klinis + penalaran AI
→ triase hijau/kuning/merah → telaah dokter + tanda tangan → rekomendasi → keputusan asuransi → dashboard
```

Prinsip yang dijaga di seluruh kode:

1. AI tidak pernah menolak klaim. Rekomendasi selain "bayar penuh" wajib ditandatangani dokter sebelum terlihat oleh asuransi.
2. Setiap temuan AI wajib membawa kutipan bukti dari dokumen; temuan tanpa bukti dibuang.
3. Aturan klinis adalah konfigurasi (`rules/aturan_klinis_demo.yaml`), bukan kode.
4. Hanya data sintetis. Setiap layar diberi label "Data rekaan untuk demonstrasi".
5. Setiap rekomendasi mencatat versi model, versi prompt, dan versi aturan.

Penjelasan teknis lengkap (komponen, alur data, model data, keamanan, keputusan desain) ada di **[docs/ARSITEKTUR.md](docs/ARSITEKTUR.md)**. Naskah demo ada di **[docs/demo-script.md](docs/demo-script.md)**. Apa yang terjadi di web untuk setiap file yang diunggah, dan output tiap klaim sintetis, ada di **[docs/skenario-unggah.md](docs/skenario-unggah.md)**.

Frontend memakai **React** lewat Next.js (App Router, TypeScript, Tailwind) di `apps/web`.

---

## 1. Prasyarat

| Kebutuhan | Keterangan |
|---|---|
| Docker Desktop | Dengan Docker Compose v2 (`docker compose version`). Alokasikan minimal 4 GB RAM untuk Docker. |
| Ruang disk | Sekitar 6 GB (image worker berisi PaddleOCR + model). |
| Internet | Saat build pertama: unduh image, paket Python/Node, dan model PaddleOCR. |
| `make` (opsional) | Di Windows bisa tanpa `make`; setiap perintah di bawah ada versi tanpa `make`. |
| Git Bash (opsional, Windows) | Hanya untuk `make reset` / `infra/scripts/reset_demo.sh`. Ada alternatif PowerShell. |

Tidak perlu API key: bawaan `LLM_PROVIDER=mock`.

## 2. Menjalankan pertama kali

Jalankan dari folder repo (mis. `D:\Kerjaan\Asuransi\poc-aaji`).

**Dengan `make`:**

```bash
make up            # salin .env.example -> .env (bila belum ada), build, nyalakan semua service
make synthetic     # buat 30 klaim sintetis di data/synthetic_output/ (sekali saja)
make seed          # isi akun demo + 29 klaim + sebagian telaah dan keputusan
```

**Tanpa `make` (PowerShell / CMD):**

```powershell
copy .env.example .env
docker compose up -d --build
docker compose run --rm --build synthetic
docker compose exec api python infra/scripts/seed_demo.py
```

Build pertama bisa 10–20 menit (terutama image worker). `seed` mengunggah 29 klaim lalu menunggu worker memprosesnya; dengan OCR di CPU biasanya beberapa menit. Progresnya tampil di terminal.

Setelah selesai, buka **http://localhost:3000**.

| Service | Alamat |
|---|---|
| Web (portal asuransi + ruang kerja dokter + admin) | http://localhost:3000 |
| API (FastAPI) | http://localhost:8000/health · dokumentasi interaktif http://localhost:8000/docs |
| MinIO (penyimpanan dokumen, API S3) | http://localhost:9000 |
| PostgreSQL | localhost:5432 |
| Redis | localhost:6379 |
| SFTP klaim batch (U2) | `sftp -P 2222 pelita@localhost` (password `demo12345`), folder di laptop `data/sftp/<KODE>/` |

### Akun demo

Password semua akun: `demo12345`. PIN tanda tangan dokter: `123456`.

| Peran | Email | Halaman awal |
|---|---|---|
| Staf klaim asuransi | `staf@demo.test` | Daftar klaim |
| Manajer klaim asuransi | `manajer@demo.test` | Daftar klaim, Dashboard |
| Dokter umum | `dokter.umum@mab.test` | Antrean telaah (kasus kuning) |
| Dokter spesialis (Penyakit Dalam) | `dokter.spesialis@mab.test` | Antrean telaah (kasus merah + eskalasi) |
| Admin MAB | `admin@mab.test` | Aturan & pengguna, Tenant & API key, Dashboard |
| Staf klaim tenant kedua (Asuransi Pelita) | `staf@pelita.test` | Daftar klaim Pelita |
| Operator TPA (DEMO + Pelita) | `tpa@mab.test` | Daftar klaim dua asuransi |
| Auditor internal / regulator | `auditor@demo.test` / `auditor@ojk.test` | Daftar klaim (hanya-baca), Dashboard |
| Petugas faskes | `faskes@demo.test` | Status klaim RS-nya |
| Peserta | `peserta@demo.test` | Status klaimnya |
| Underwriter | `underwriter@demo.test` | Penanda modul U7 |

Peran baru dan dua tenant demo dijelaskan di [docs/u1-fondasi-platform.md](docs/u1-fondasi-platform.md). Polis, aturan benefit, API klaim masuk, FHIR, SFTP (port 2222, login `demo`/`pelita` + `demo12345`), dan webhook dijelaskan di [docs/u2-integrasi-benefit.md](docs/u2-integrasi-benefit.md). Fraud analytics dan Fraud Monitor dijelaskan di [docs/u3-fraud-analytics.md](docs/u3-fraud-analytics.md).

**Ganti peran (demo).** Setelah login dengan akun demo mana saja, pemilih kuning **Ganti peran (demo)** di kanan atas memindahkan Anda ke akun demo lain tanpa logout. Dengan begitu seluruh alur, dari unggah, telaah dokter, keputusan, sampai dashboard, bisa dijalankan dari satu jendela browser. Setiap aksi tetap tercatat atas nama peran yang benar, jadi aturan "hanya dokter yang menandatangani" tetap berlaku. Matikan dengan `DEMO_MODE=false` di `.env`. Penjelasan lengkap ada di [docs/skenario-unggah.md](docs/skenario-unggah.md).

## 3. Isi data demo setelah `make seed`

| Kondisi | Klaim | Untuk ditunjukkan |
|---|---|---|
| Hijau, sudah disetujui massal | 12 klaim (SYN-DEN-04/05, SYN-GEA-01..05, SYN-TIF-01..05) | Daftar klaim, ekspor CSV |
| Hijau, belum diputuskan | SYN-DEN-01, SYN-DEN-02, SYN-DEN-03 | Setujui massal |
| Kuning di antrean dokter umum | SYN-DEN-06, SYN-TIF-10 (dokumen tidak lengkap) | Ruang kerja dokter umum |
| Merah / eskalasi di antrean spesialis | SYN-GEA-10 (tumpang tindih dengan KLM-RIWAYAT-0001), SYN-TIF-08, SYN-DEN-08 (hasil eskalasi dokter umum) | Ruang kerja spesialis |
| Sudah ditandatangani, menunggu keputusan asuransi | SYN-DEN-07 (spesialis mengubah draf jadi bayar sebagian) | Rekomendasi final, PDF, keputusan |
| Sudah ditandatangani dan diputuskan | SYN-DEN-10, SYN-GEA-06..09, SYN-TIF-06, SYN-TIF-07, SYN-TIF-09 ("berbeda") | Dashboard |
| **Belum diunggah** | **SYN-DEN-09** | **Diunggah langsung saat demo** |
| Tenant kedua (Asuransi Pelita, ambang merah 20) | SYN-DEN-08, SYN-DEN-09, SYN-GEA-07, SYN-TIF-07 (merah, di antrean spesialis) | Perbedaan triase dan SLA antar tenant |
| Pelita, temuan benefit polis (U2) | SYN-DEN-02 (kuning, BEN-05 kamar kelas 1 padahal hak kelas 2), SYN-GEA-02 (merah, BEN-04 melebihi sisa limit) | Aturan benefit, bukti dari data polis |
| Pelita, masuk lewat integrasi (U2) | SYN-DEN-01 (FHIR), SYN-GEA-01 (API), SYN-TIF-01 dan SYN-TIF-02 (SFTP); semua hijau, webhook terkirim | Kanal integrasi, webhook, `data/sftp/PELITA/keluar/` |
| Fraud Monitor, kedua tenant (U3) | 805 klaim riwayat rekaan + klaim platform; 8 sinyal: RS lama rawat, dokter biaya per hari, dokter lab, rekening bersama, alamat bersama, rujukan berputar, klaim beruntun, rawat tumpang tindih | Skor fraud terpisah dari triase, bukti sejawat dan graf, telaah investigator (login `manajer@demo.test`) |

Tabel ini dari uji seed kami. SYN-DEN-06 sebenarnya klaim wajar, tetapi naik ke kuning karena ada catatan kualitas data pada dokumen pindaiannya (kalau ragu, klaim tidak boleh hijau). Hasil OCR di mesin lain bisa sedikit berbeda, sehingga isi antrean juga bisa sedikit berbeda.

## 4. Skenario demo (ringkas)

Naskah lengkap 10 menit, dengan kalimat yang bisa diucapkan dan nilai yang perlu diisi, ada di [docs/demo-script.md](docs/demo-script.md). Sembilan skenario langkah demi langkah (unggah satu klaim, unggah massal ZIP, klaim hijau, data meragukan, dokumen tidak lengkap, klaim tumpang tindih, eskalasi, komplikasi tanpa bukti, asuransi berbeda) ada di [docs/skenario-unggah.md](docs/skenario-unggah.md). Ringkasnya:

1. **Staf asuransi** (`staf@demo.test`) mengunggah klaim DBD bermasalah **SYN-DEN-09** lewat **Unggah klaim**. Isi formulir dengan data dari `data/synthetic_output/SYN-DEN-09/case.json` (nomor klaim harus persis `SYN-DEN-09` di mode mock) dan lampirkan 4 PDF-nya. Halaman detail menampilkan progres, lalu status **Menunggu dokter**. Asuransi belum bisa melihat temuan.
2. **Dokter umum** (`dokter.umum@mab.test`) membuka **Antrean telaah**. SYN-DEN-09 masuk antrean dengan triase kuning. Di layar dua panel, klik kutipan bukti: halaman dokumen terbuka dan lokasinya disorot (darah lengkap 4x sehari, tidak ada warning sign).
3. Dokter klik **Mulai telaah**, melihat **Data ekstraksi** (bisa dikoreksi, tercatat riwayatnya), lalu **Setujui draf & tanda tangan** dengan PIN `123456`. Alternatif: **Ubah rekomendasi** (kode alasan wajib) atau **Eskalasi ke spesialis**.
4. **Staf asuransi** membuka klaim yang sama: rekomendasi final kini terlihat, lengkap dengan nama dokter dan waktu tanda tangan. Catat keputusan **Setuju** atau **Berbeda** (alasan wajib), unduh **PDF**.
5. **Manajer** membuka **Dashboard**: jumlah per triase, nilai koreksi, temuan terbanyak, RS dengan temuan terbanyak, waktu proses, dan persentase persetujuan dokter terhadap draf AI. Tutup dengan **Ekspor CSV** di Daftar klaim.

## 5. Perintah sehari-hari

| Tujuan | Dengan `make` | Tanpa `make` |
|---|---|---|
| Nyalakan | `make up` | `docker compose up -d --build` |
| Matikan (data tetap ada) | `make down` | `docker compose down` |
| Lihat log | `make logs` | `docker compose logs -f --tail=100` |
| Tes otomatis | `make test` | `docker compose run --rm --no-deps api pytest -q tests` |
| Isi data demo | `make seed` | `docker compose exec api python infra/scripts/seed_demo.py` |
| **Reset demo** (hapus semua data, isi ulang) | `make reset` | lihat di bawah |
| Evaluasi lengkap | `make eval` | `docker compose run --rm --no-deps worker python -m evaluation.run_eval` |

**Reset demo** menghapus database dan file dokumen lokal lalu mengisi ulang data demo. Dengan Git Bash: `bash infra/scripts/reset_demo.sh` (minta konfirmasi). Di PowerShell:

```powershell
docker compose down -v
docker compose up -d --build
# tunggu sampai http://localhost:8000/health menjawab {"status":"ok"}, lalu:
docker compose exec api python infra/scripts/seed_demo.py
```

Lakukan reset sebelum setiap sesi demo supaya SYN-DEN-09 belum ada dan antrean dokter berisi.

## 6. Evaluasi

```bash
make eval
```

Menjalankan 30 klaim sintetis lewat pipeline lengkap dan menulis laporan ke `evaluation/reports/eval_<llm>_<ocr>.md` (+ `.json`): akurasi ekstraksi per field dan per mode (digital/pindaian), kecocokan triase dengan kunci jawaban, jumlah klaim bermasalah yang keliru jadi hijau, temuan berbukti, dan waktu proses per klaim.

Cara membaca angkanya dengan jujur:

- Semua angka berasal dari data sintetis buatan repo ini, bukan klaim sungguhan.
- Dengan `LLM_PROVIDER=mock`, "LLM" menjawab dari skenario sintetis. Angkanya menguji pembacaan dokumen, OCR, cek bukti, aturan, dan triase, **bukan** kualitas model AI. Laporan menuliskan peringatan ini.
- Hasil terakhir (mock LLM, OCR RapidOCR model PP-OCR karena model PaddleOCR tidak bisa diunduh di lingkungan pengembangan): ekstraksi field kunci 100%, status triase sesuai 96,7% (29/30), 0 klaim bermasalah jadi hijau, 22/22 temuan berbukti. Laporan acuannya ikut di repo: `evaluation/reports/eval_mock-llm-1_rapidocr-ppocr.md`. Di Docker, worker memakai PaddleOCR, jadi `make eval` akan menulis laporan baru `eval_mock-llm-1_paddleocr.md`.

Skrip lama per milestone masih ada: `make eval-extraction` (M4) dan `make eval-triage` (M5).

## 7. Memakai LLM sungguhan (DeepSeek)

Isi di `.env` (file ini diabaikan git; jangan pernah commit API key):

```
LLM_PROVIDER=deepseek
LLM_API_KEY=<kunci API Anda>
```

Lalu `docker compose up -d --build worker`. `LLM_BASE_URL` dan `LLM_MODEL` boleh kosong (bawaan `https://api.deepseek.com`, `deepseek-chat`). Untuk server lain yang kompatibel OpenAI: `LLM_PROVIDER=openai_compatible` + `LLM_BASE_URL` + `LLM_MODEL`.

Catatan: di mode sungguhan nomor klaim bebas (tidak harus `SYN-...`). Sebelum memakai data nyata di tahap berikutnya, cek ulang lokasi pemrosesan data penyedia LLM.

## 8. Mengatasi masalah

| Gejala | Penyebab umum dan solusi |
|---|---|
| `make seed`: "Tidak ada data sintetis" | Jalankan `make synthetic` dulu. |
| `make seed`: "Klaim demo sudah ada" | Data lama masih ada. Jalankan `make reset`. |
| Klaim lama di status "Diproses" | Worker belum jalan atau sedang OCR. Cek `docker compose logs -f worker`. |
| Klaim "Gagal diproses" | Lihat pesan di halaman detail dan `docker compose logs worker`. Mode mock butuh nomor klaim `SYN-xxx-nn` yang ada di `data/synthetic_output`. |
| Login gagal | Akun belum dibuat: `make seed` (atau `make seed-users`). |
| Port 3000/8000/5432 dipakai | Matikan aplikasi lain yang memakai port itu, atau ubah pemetaan port di `docker-compose.yml`. |
| Build worker gagal mengunduh model OCR | Butuh internet saat build. Coba ulang `docker compose build worker`. |
| Halaman web kosong setelah update kode | `docker compose up -d --build web`. |

## 9. Batasan Tahap 0

- Hanya data sintetis (30 skenario: 16 wajar, 14 bermasalah) untuk tiga diagnosis: dengue, demam tifoid, gastroenteritis akut.
- Aturan klinis (19 aturan) masih draf dan belum divalidasi dokter; rujukan pedoman hanya ringkasan.
- Koreksi field oleh dokter tidak otomatis menjalankan ulang aturan; dokter menetapkan rekomendasi final.
- Tanda tangan digital sederhana (login + PIN), belum tanda tangan elektronik tersertifikasi.
- Tidak ada integrasi ke sistem klaim asuransi; pertukaran data lewat unggah manual dan ekspor CSV.
- Modul red flag (`pipeline/mab_pipeline/redflags/`) belum diisi; pola penipuan baru sebatas aturan umum (klaim tumpang tindih, item ganda, item tanpa catatan klinis).
- Rahasia di `.env.example` hanya untuk lokal. Ganti `JWT_SECRET` dan password bila dipasang di server mana pun.

## 10. Struktur repo

```
apps/web/                Next.js 14: portal asuransi, ruang kerja dokter, admin, dashboard
apps/api/                FastAPI: auth, klaim, dokumen, telaah, keputusan, dashboard, audit; migrasi Alembic
pipeline/mab_pipeline/   ingest, ocr, extraction, reasoning, rules, triage, llm, worker RQ
rules/                   aturan_klinis_demo.yaml (konfigurasi aturan) + CHANGELOG.md
synthetic/               generator 30 klaim sintetis (PDF digital + pindaian)
evaluation/              skrip evaluasi + laporan (evaluation/reports/)
infra/docker/            Dockerfile api, worker, web, synthetic
infra/scripts/           seed_users.py, seed_demo.py, reset_demo.sh
docs/                    ARSITEKTUR.md, demo-script.md, kamus-data.md
tests/                   tes otomatis (pytest)
data/                    (diabaikan git) output data sintetis
```

## Status milestone

- [x] M0 Kerangka repo & infrastruktur
- [x] M1 Mesin aturan & triase
- [x] M2 Generator data sintetis
- [x] M3 API, database, unggah dokumen
- [x] M4 Pipeline baca dokumen
- [x] M5 Penalaran klinis, cek bukti, rekomendasi
- [x] M6 Portal asuransi
- [x] M7 Ruang kerja dokter
- [x] M8 Evaluasi, seed demo, naskah demo

### Upgrade menuju MAB-as-a-Service

- [x] U1 Fondasi platform: tenant, peran baru, API key, penugasan dokter + SLA ([docs/u1-fondasi-platform.md](docs/u1-fondasi-platform.md))
- [x] U2 Integrasi data (REST, SFTP, FHIR) dan benefit polis ([docs/u2-integrasi-benefit.md](docs/u2-integrasi-benefit.md))
- [x] U3 Fraud analytics: statistik sejawat, graf relasi, Fraud Monitor ([docs/u3-fraud-analytics.md](docs/u3-fraud-analytics.md))
- [ ] U4 Portal faskes, peserta, TPA
- [ ] U5 Manajemen sengketa
- [ ] U6 Audit dan pelaporan OJK
- [ ] U7 Medical underwriting
- [ ] U8 Infrastruktur cloud dan kesiapan data sungguhan
