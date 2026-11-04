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
- [ ] M1 Mesin aturan & triase
- [ ] M2 Generator data sintetis
- [ ] M3 API, database, unggah dokumen
- [ ] M4 Pipeline baca dokumen
- [ ] M5 Penalaran klinis, cek bukti, rekomendasi
- [ ] M6 Portal asuransi
- [ ] M7 Ruang kerja dokter
- [ ] M8 Evaluasi, seed demo, naskah demo

## Catatan

- `LLM_PROVIDER=mock` adalah default, jadi tidak perlu API key untuk pengembangan.
- Image MinIO memakai `bitnamilegacy/minio` karena `minio/minio` sudah tidak tersedia di Docker Hub dan tag di quay.io butuh login. Image ini tidak menyertakan web console; isi bucket bisa dicek lewat `docker compose exec minio mc ls local`.
