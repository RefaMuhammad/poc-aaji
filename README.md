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
evaluation/              skrip evaluasi (akurasi ekstraksi M4; lengkap di M8)
tests/                   tes otomatis
infra/docker/            Dockerfile api, worker, web
data/                    (diabaikan git) data referensi dan output sintetis
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
| Dokter umum | dokter.umum@mab.test | demo12345 (PIN tanda tangan 123456) |
| Dokter spesialis | dokter.spesialis@mab.test | demo12345 (PIN tanda tangan 123456) |
| Admin MAB | admin@mab.test | demo12345 |

Dokumentasi interaktif: http://localhost:8000/docs (klik **Authorize**, tempel token dari `POST /auth/login`).

Endpoint utama: `POST /claims`, `POST /claims/{id}/documents` (PDF/JPG/PNG maks. 20 MB), `POST /claims/batch` (ZIP berisi `manifest.xlsx` + satu folder per klaim), `GET /claims`, `GET /claims/{id}`, `GET /claims/{id}/status`, `GET /claims/{id}/recommendation`, `POST /claims/{id}/decision`, `POST /claims/decisions/bulk-agree`, `GET /claims/export.csv`, `GET /documents/{id}/download`, `GET /users` (admin).

Kolom `manifest.xlsx`: `folder, nomor_klaim, nomor_polis, id_peserta, nama_peserta, nama_rs, tanggal_masuk, tanggal_keluar, nilai_tagihan`.

Aturan akses: staf/manajer hanya melihat klaim asuransinya; dokter melihat klaim yang ditugaskan kepadanya atau yang menunggu dokter; rekomendasi selain bayar penuh baru terlihat oleh asuransi setelah ditandatangani dokter. Semua aksi tulis, login, dan akses dokumen tercatat di `audit_logs`, yang di PostgreSQL tidak bisa diubah atau dihapus (trigger).

## Pipeline baca dokumen (M4)

Setelah dokumen klaim diunggah, worker menjalankan:

1. **Ingest** (`ingest/pdf_loader.py`): halaman PDF yang punya lapisan teks dibaca pdfplumber (teks + koordinat, watermark miring dibuang). Halaman tanpa teks dirender 200 DPI.
2. **Pra-pemrosesan dan OCR** (`ingest/image_preprocess.py`, `ocr/engine.py`): kontras, denoise, koreksi miring, lalu PaddleOCR. Hasilnya baris teks dengan bbox dan skor keyakinan.
3. **Klasifikasi** (`ingest/doc_classifier.py`): judul dokumen dicocokkan dengan kata kunci; bila gagal, LLM; bila tetap gagal, tebakan dari nama file.
4. **Ekstraksi** (`extraction/llm_extractor.py`): teks bernomor + prompt berversi (`extraction/prompts/`, versi `extract_v1`) dikirim ke LLM. Setiap nilai wajib membawa `source_line_ids`. Jawaban divalidasi Pydantic, diulang sekali bila tidak valid, lalu ditandai gagal.
5. **Field turunan** (`extraction/derived_fields.py`): lama rawat, trombosit terendah, kenaikan hematokrit, darah lengkap per hari, Widal, lama seftriakson, hari infus, item tagihan ganda, dokumen yang kurang. Klaim tumpang tindih dihitung dari database.

Field disimpan di tabel `extracted_fields` beserta bukti `{doc, page, bbox, quote, line_ids}` dan bisa dilihat di `GET /claims/{id}/fields`.

## Penalaran klinis dan rekomendasi (M5)

Masih di job yang sama, setelah dokumen terbaca:

1. **Penalaran klinis** (`reasoning/clinical_reasoner.py`, prompt `clinical_v1`): LLM membaca resume, CPPT, lab, dan tagihan, lalu mengisi field `sumber: ai` di kamus data yang dipakai aturan diagnosis tersebut. Setiap nilai yang menyatakan sesuatu ada wajib membawa kutipan persis.
2. **Cek bukti** (`reasoning/evidence_check.py`): kutipan dicocokkan ke teks dokumen (fuzzy, skor >= 0,9, boleh melintasi 2-3 baris). Kutipan yang tidak ditemukan dibuang dan nilainya menjadi null (tidak diketahui), bukan "tidak ada".
3. **Aturan** M1 dijalankan; setiap temuan diberi bukti dari field yang dipakai aturannya (dokumen, halaman, bbox, kutipan). Temuan yang butuh bukti AI tetapi tidak punya bukti dibuang.
4. **Rekomendasi** (`triage/recommender.py`): status, skor, rekomendasi awal (`PAY_FULL`, `DOCTOR_REVIEW`, `PEND`), usulan koreksi tagihan (item ganda, item tanpa catatan klinis, hari rawat berlebih), draf penjelasan, rujukan pedoman, serta versi model, prompt, dan aturan.

Pengaman kualitas data: bila ada dokumen tidak terbaca, diagnosis tidak terbaca, kutipan AI tidak terbukti, aturan tidak bisa dinilai, atau temuan dibuang, klaim tidak pernah hijau (dinaikkan ke kuning, dengan catatan di `quality_flags`). AI tidak pernah menolak klaim.

Klaim bayar penuh langsung berstatus `AWAITING_DECISION` dan terlihat oleh asuransi. Selain itu berstatus `AWAITING_DOCTOR` dan baru terlihat oleh asuransi setelah ditandatangani dokter (M7). Semua versi dicatat di `audit_logs` (`PIPELINE_COMPLETED`).

```bash
make eval-triage        # tanpa make: docker compose run --rm --no-deps worker python -m evaluation.triage_accuracy
```

Target M5: >= 90% status triase sesuai kunci jawaban, 0 klaim bermasalah menjadi hijau, setiap temuan punya bukti.

## Portal asuransi (M6)

Buka http://localhost:3000 lalu masuk dengan akun demo (mis. `staf@demo.test` / `demo12345`).

- **Daftar klaim**: filter status dan triase, badge triase, status proses (diperbarui otomatis selama klaim diproses), setujui massal klaim hijau, ekspor CSV.
- **Unggah klaim**: formulir satu klaim + dokumen (PDF/JPG/PNG), atau ZIP berisi `manifest.xlsx` dan satu folder per klaim. Setelah unggah, halaman detail menampilkan progres proses.
- **Detail klaim**: rekomendasi sesuai format PRD (triase, skor risiko, nilai rekomendasi, koreksi per item, temuan, rujukan, versi model/prompt/aturan). Klik kutipan bukti untuk membuka halaman dokumen dengan lokasi kutipan disorot.
- **Keputusan**: setuju / berbeda (alasan wajib bila berbeda). Rekomendasi bisa diunduh sebagai PDF.
- Rekomendasi selain bayar penuh tidak tampil ke asuransi sebelum ditandatangani dokter; portal menampilkan "perlu telaah dokter". Ruang kerja dokter dibuat di M7.

Browser hanya memanggil `/api/*` di server web; server web meneruskannya ke API (`API_INTERNAL_URL`, di compose `http://api:8000`). Jadi cukup port 3000 yang perlu dibuka.

Endpoint baru: `GET /documents/{id}/pages/{n}.png` (pratinjau halaman), `GET /claims/{id}/recommendation.pdf`, filter `?triage=` di `GET /claims`.

Pengembangan frontend tanpa Docker: `cd apps/web && npm ci && npm run dev` (API harus jalan di http://localhost:8000).

## Ruang kerja dokter (M7)

Masuk sebagai dokter (mis. `dokter.spesialis@mab.test`), lalu buka **Antrean telaah**.

- **Antrean**: kasus kuning untuk dokter umum; kasus merah dan hasil eskalasi untuk dokter spesialis sebidang (bidang per diagnosis diatur di `spesialisasi` pada file aturan). Urut skor risiko tertinggi, filter diagnosis, plus tab "Sudah saya tanda tangani".
- **Layar telaah dua panel**: kiri dokumen asli (klik kutipan bukti untuk menyorot lokasinya), kanan temuan, draf rekomendasi, data ekstraksi, dan riwayat telaah.
- **Mulai telaah** mengunci kasus untuk dokter itu dan mulai menghitung waktu telaah. **Lepas kasus** mengembalikannya ke antrean.
- **Koreksi field**: nilai asli tetap disimpan; setiap koreksi tercatat (nilai lama, nilai baru, catatan, siapa, kapan).
- **Aksi**: setujui draf, ubah rekomendasi (kode alasan wajib bila berbeda dari draf), eskalasi ke spesialis (dokter umum, catatan wajib), lalu tanda tangan dengan PIN.
- Tanda tangan membuat versi rekomendasi baru berstatus SIGNED (draf AI tetap tersimpan sebagai versi lama) dan klaim langsung muncul di portal asuransi untuk diputuskan.
- Untuk metrik, setiap telaah menyimpan waktu mulai/selesai dan apakah dokter setuju dengan draf AI (`reviews.agrees_with_ai`).
- Usulan dari draf AI tidak pernah "tidak dijamin": tanpa koreksi nilai, usulannya "tunda/klarifikasi".
- Koreksi field belum menjalankan ulang aturan secara otomatis; dokter memutuskan rekomendasi final berdasarkan koreksinya.
- **Admin** (`admin@mab.test`): halaman **Aturan & pengguna** menampilkan versi aturan aktif, aturan triase, daftar aturan per diagnosis, dan daftar pengguna (baca saja).

Endpoint: `GET /review/queue`, `GET /review/{id}`, `POST /review/{id}/start`, `POST /review/{id}/release`, `PATCH /review/{id}/fields/{field_id}`, `POST /review/{id}/escalate`, `POST /review/{id}/sign`, `GET /admin/ruleset`.

### Memakai DeepSeek

Isi di `.env` (jangan di-commit):

```
LLM_PROVIDER=deepseek
LLM_API_KEY=<kunci API Anda>
```

Lalu `docker compose up -d --build worker`. `LLM_BASE_URL` dan `LLM_MODEL` boleh kosong (bawaan `https://api.deepseek.com`, `deepseek-chat`). Untuk server lain yang kompatibel OpenAI pakai `LLM_PROVIDER=openai_compatible` dengan `LLM_BASE_URL` dan `LLM_MODEL`. Sebelum memakai data nyata, cek ulang lokasi pemrosesan data penyedia LLM.

### Mengukur akurasi ekstraksi

```bash
make synthetic          # sekali, membuat 30 klaim + ground_truth.json
make eval-extraction    # tanpa make: docker compose run --rm --no-deps worker python -m evaluation.extraction_accuracy
```

Laporan (Markdown + JSON) ditulis ke `evaluation/reports/`, dipisah per PDF digital dan pindaian. Target M4: akurasi field kunci >= 90% dengan LLM sungguhan. Mode mock hanya menguji alur (nilainya diambil dari data sintetis), jadi angkanya bukan ukuran kualitas LLM.

Image worker memasang PaddleOCR dan mengunduh modelnya saat build, jadi build pertama lebih lama dan butuh internet.

## Catatan

- `LLM_PROVIDER=mock` adalah default, jadi tidak perlu API key untuk pengembangan.
- Image MinIO memakai `bitnamilegacy/minio` karena `minio/minio` sudah tidak tersedia di Docker Hub dan tag di quay.io butuh login. Image ini tidak menyertakan web console; isi bucket bisa dicek lewat `docker compose exec minio mc ls local`.
