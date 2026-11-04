# MAB Indonesia POC (Tahap 0)

> **Data rekaan untuk demonstrasi.** Repo ini hanya memakai data sintetis. Aturan klinis masih draf dan belum divalidasi dokter.

Platform yang membantu Dewan Penasihat Medis menelaah klaim asuransi kesehatan rawat inap:
unggah berkas klaim → ekstraksi data → aturan klinis + penalaran AI → triase hijau/kuning/merah → telaah dokter → rekomendasi → keputusan asuransi.

## Menjalankan

Prasyarat: Docker Desktop (dengan Docker Compose v2) dan `make`.

```bash
make up        # salin .env.example ke .env (bila belum ada), build, dan nyalakan semua service
make test      # jalankan tes otomatis di container api
make logs      # lihat log
make down      # matikan
```

Tanpa `make` (misalnya di Windows tanpa make):

```bash
cp .env.example .env
docker compose up -d --build
docker compose run --rm --no-deps api pytest -q tests
```

| Service | Alamat |
|---|---|
| Web (Next.js) | http://localhost:3000 |
| API (FastAPI) | http://localhost:8000/health, dokumentasi di http://localhost:8000/docs |
| MinIO (API S3) | http://localhost:9000 |
| PostgreSQL | localhost:5432 |
| Redis | localhost:6379 |

## Struktur

```
apps/web/                Next.js: portal asuransi + ruang kerja dokter + admin
apps/api/                FastAPI: klaim, dokumen, telaah, keputusan, audit
pipeline/mab_pipeline/   ingest, ocr, extraction, reasoning, rules, redflags, triage, llm, worker RQ
rules/                   aturan_klinis_demo.yaml (konfigurasi aturan), CHANGELOG.md
synthetic/               generator data sintetis (M2)
evaluation/              skrip evaluasi (M8)
tests/                   tes otomatis
infra/docker/            Dockerfile api, worker, web
data/                    (diabaikan git) data referensi dan output sintetis
```

## Status milestone

- [x] M0 Kerangka repo & infrastruktur
- [x] M1 Mesin aturan & triase
- [x] M2 Generator data sintetis
- [x] M3 API, database, unggah dokumen
- [ ] M4 Pipeline baca dokumen
- [ ] M5 Penalaran klinis, cek bukti, rekomendasi
- [ ] M6 Portal asuransi
- [ ] M7 Ruang kerja dokter
- [ ] M8 Evaluasi, seed demo, naskah demo

## Mesin aturan (M1)

Aturan klinis ada di `rules/aturan_klinis_demo.yaml` dan dibaca oleh `pipeline/mab_pipeline/rules/`. Untuk mencoba pada contoh klaim:

```bash
docker compose run --rm --no-deps api python -m mab_pipeline.rules rules/aturan_klinis_demo.yaml tests/fixtures/contoh_klaim_uji.json
```

Ekspresi `kondisi` dievaluasi tanpa `eval`: hanya field `kelompok.field`, konstanta, `and/or/not`, perbandingan, dan `len()` yang diizinkan. Ambang triase (bobot keparahan dan `skor_min`) diatur di bagian `triase` YAML.

## Data sintetis (M2)

```bash
make synthetic
# tanpa make:
docker compose run --rm --build synthetic
```

Hasilnya di `data/synthetic_output/` (tidak masuk git):

- `<claim_id>/` berisi `resume_medis.pdf`, `hasil_laboratorium.pdf`, `cppt.pdf`, `rincian_tagihan.pdf`, dan `case.json` (isi lengkap klaim). 12 dari 30 klaim dibuat versi pindaian (gambar miring, blur, noise, stempel).
- `kunci_jawaban.csv`: status triase, rekomendasi, dan aturan yang diharapkan per klaim.
- `ground_truth.json`: nilai field kamus data yang benar per klaim, untuk mengukur akurasi ekstraksi di M4.

Skenario ada di `synthetic/scenarios.yaml` (16 wajar, 14 bermasalah termasuk 2 dokumen tidak lengkap dan 1 klaim duplikat). Semua nama pasien, dokter, dan rumah sakit fiktif, dan setiap halaman diberi tanda "DATA REKAAN".

## API (M3)

Migrasi database berjalan otomatis saat container `api` menyala. Buat akun demo sekali:

```bash
make seed-users
# tanpa make:
docker compose exec api python infra/scripts/seed_users.py
```

| Peran | Email | Password |
|---|---|---|
| Staf klaim asuransi | staf@demo.test | demo12345 |
| Manajer klaim | manajer@demo.test | demo12345 |
| Dokter umum | dokter.umum@mab.test | demo12345 |
| Dokter spesialis | dokter.spesialis@mab.test | demo12345 |
| Admin MAB | admin@mab.test | demo12345 |

Dokumentasi interaktif: http://localhost:8000/docs (klik **Authorize**, tempel token dari `POST /auth/login`).

Endpoint utama: `POST /claims`, `POST /claims/{id}/documents` (PDF/JPG/PNG maks. 20 MB), `POST /claims/batch` (ZIP berisi `manifest.xlsx` + satu folder per klaim), `GET /claims`, `GET /claims/{id}`, `GET /claims/{id}/status`, `GET /claims/{id}/recommendation`, `POST /claims/{id}/decision`, `POST /claims/decisions/bulk-agree`, `GET /claims/export.csv`, `GET /documents/{id}/download`, `GET /users` (admin).

Kolom `manifest.xlsx`: `folder, nomor_klaim, nomor_polis, id_peserta, nama_peserta, nama_rs, tanggal_masuk, tanggal_keluar, nilai_tagihan`.

Aturan akses: staf/manajer hanya melihat klaim asuransinya; dokter melihat klaim yang ditugaskan kepadanya atau yang menunggu dokter; rekomendasi selain bayar penuh baru terlihat oleh asuransi setelah ditandatangani dokter. Semua aksi tulis, login, dan akses dokumen tercatat di `audit_logs`, yang di PostgreSQL tidak bisa diubah atau dihapus (trigger).

## Catatan

- `LLM_PROVIDER=mock` adalah default, jadi tidak perlu API key untuk pengembangan.
- Image MinIO memakai `bitnamilegacy/minio` karena `minio/minio` sudah tidak tersedia di Docker Hub dan tag di quay.io butuh login. Image ini tidak menyertakan web console; isi bucket bisa dicek lewat `docker compose exec minio mc ls local`.
