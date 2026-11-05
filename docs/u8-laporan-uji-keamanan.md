# Laporan uji keamanan U8

Data rekaan untuk demonstrasi. Tanggal uji: 5 November 2026. Versi: branch U8 (aplikasi 0.8.0).

## Kesimpulan

Uji keamanan otomatis internal **lolos** setelah perbaikan: tidak ada temuan tinggi atau sedang yang tersisa di
pemindaian aplikasi web, API, kode, dan dependensi, dan uji bencana backup berhasil dipulihkan dengan verifikasi penuh.

Laporan ini **bukan** pengganti uji penetrasi oleh pihak ketiga. Uji penetrasi independen terhadap lingkungan staging
di cloud tetap menjadi syarat sebelum data sungguhan (checklist UU PDP, bagian E).

## Lingkup dan lingkungan

- Portal web Next.js (build produksi) dan API FastAPI dari kode branch ini, dengan PostgreSQL 16, Redis 7, dan MinIO
  (SSE-S3) di Docker, berisi data demo rekaan hasil seed.
- Belum di cloud: TLS, ingress, WAF, dan NetworkPolicy diuji lewat validasi manifest, bukan serangan langsung.

## Ringkasan hasil

| Uji | Alat | Sebelum perbaikan | Sesudah |
|---|---|---|---|
| Pemindaian pasif portal web | OWASP ZAP 2.17 baseline | 0 gagal, 2 peringatan (CSP `script-src 'unsafe-inline'`, `style-src 'unsafe-inline'`) | 0 gagal, 1 peringatan diterima (`style-src`) dari 60 aturan |
| Pemindaian aktif API (OpenAPI, 114 aturan: injeksi SQL/perintah, XSS, path traversal, dsb.) | ZAP 2.17 API scan | 0 gagal, 0 peringatan | 0 gagal, 0 peringatan |
| Analisis kode Python (11.955 baris) | bandit 1.8 | 1 tinggi, 1 sedang, 6 rendah | 0 tinggi, 0 sedang, 5 rendah (diterima) |
| Dependensi Python (API, pipeline, sintetis) | pip-audit 2.7 | 9 paket dengan celah publik (PyJWT, Starlette, python-multipart, Pillow, pdfminer, Jinja2, fpdf2, WeasyPrint, pytest) | 0 |
| Dependensi web | npm audit | 1 kritis (Next.js: RCE di Image Optimization API dan 20+ celah lain), 1 tinggi (PostCSS) | 0 |
| Tes keamanan otomatis | pytest (`tests/test_u8_operasi_keamanan.py`) | belum ada | 19 tes lolos; seluruh suite 228 tes lolos |
| Uji bencana backup | `infra/ops/mab_backup.py` | belum ada | Database dan 308 dokumen dihapus, dipulihkan, 32 tabel / 4.182 baris / 308 checksum cocok |
| Enkripsi at rest | inspeksi disk MinIO | objek tersimpan apa adanya | 0 dari 366 berkas di disk memuat teks PDF; objek bertanda `AES256` |
| Manifest Kubernetes | `helm lint`, `kubectl apply --dry-run=server` (K8s 1.30) | belum ada | lolos (22 objek + CRD monitoring) |
| Browser: CSP tidak merusak aplikasi | Playwright, 4 peran, semua menu | | 0 error konsol, gambar dokumen tampil |

Laporan ZAP lengkap: [docs/keamanan/zap_web.html](keamanan/zap_web.html), [docs/keamanan/zap_api.html](keamanan/zap_api.html).

## Temuan dan perbaikan

| No | Temuan | Tingkat | Perbaikan |
|---|---|---|---|
| 1 | Next.js 14.2.35 punya celah kritis (RCE lewat Image Optimization API, SSRF, DoS, XSS pada CSP nonce) | Kritis | Upgrade ke Next.js 15.5.29 + React 19.2; PostCSS dipaksa 8.5.32 lewat `overrides` |
| 2 | Login tanpa batas percobaan: password bisa ditebak beruntun | Tinggi | Kunci 15 menit setelah 5 gagal per akun dan 100 gagal per IP; tercatat `LOGIN_LOCKED` |
| 3 | PIN tanda tangan 6 digit tanpa batas percobaan: tanda tangan dokter bisa dipalsukan oleh pemegang sesi | Tinggi | Kunci setelah 5 PIN salah per dokter (klaim dan underwriting) |
| 4 | Dependensi Python usang dengan celah publik (PyJWT, Starlette, python-multipart, Pillow, pdfminer, Jinja2, fpdf2, WeasyPrint) | Tinggi | Diperbarui; 228 tes dan pembuatan data sintetis tetap lolos |
| 5 | Folder SFTP dibuat `chmod 0777` (bandit B103) | Tinggi | Bawaan `0770` (grup bersama); dev memakai `SFTP_DIR_MODE=0777` hanya di docker compose |
| 6 | CSP web mengizinkan skrip inline (ZAP 10055) | Sedang | CSP dengan nonce per permintaan + `strict-dynamic` (`middleware.ts`) |
| 7 | Nama tabel dirangkai ke SQL di skrip backup (bandit B608) | Sedang | `psycopg.sql.Identifier`; diuji dengan nama tabel berisi injeksi |
| 8 | Respons API tanpa header keamanan; `X-Powered-By` di web | Sedang | Header keamanan di API dan web, HSTS di luar development |
| 9 | Aplikasi bisa jalan di server dengan rahasia bawaan | Sedang | Gerbang konfigurasi: API/worker/migrasi menolak start di staging/produksi |
| 10 | `JWT_SECRET` bawaan 25 byte (di bawah 32 byte RFC 7518) | Rendah | Bawaan dev ≥ 32 karakter; staging wajib ≥ 32 |
| 11 | `assert` untuk validasi event webhook (hilang dengan `python -O`) | Rendah | Diganti `ValueError` |

## Risiko yang diterima

| Hal | Alasan |
|---|---|
| CSP `style-src 'unsafe-inline'` | Atribut `style` React/Tailwind belum bisa memakai nonce. Skrip tetap dikunci nonce; risiko injeksi CSS jauh lebih rendah |
| bandit rendah: `try/except/pass` di batas percobaan, `subprocess` di skrip backup, string "password" di pesan error | Disengaja dan sudah ditinjau: batas percobaan tidak boleh menjatuhkan login saat Redis bermasalah; subprocess memakai daftar argumen tanpa shell dan tanpa password di argumen |
| ZAP info "Sensitive Information in URL" pada `/audit/logs?user=` | Parameter berisi filter nama pengguna untuk auditor, bukan kredensial |
| `pipeline/requirements-ocr.txt` (PaddleOCR) tidak bisa diaudit di sandbox | Paket tidak tersedia untuk Python 3.13; audit di image worker dengan Trivy saat CI dibuat |
| Batas percobaan gagal terbuka (fail-open) bila Redis mati | Login tetap tersedia; hitungan sementara per pod. Alert Redis di monitoring |

## Belum diuji (wajib sebelum data sungguhan)

1. Uji penetrasi pihak ketiga terhadap staging di cloud: autentikasi dan sesi, kontrol akses antar-tenant dan antar-peran
   (IDOR), unggah berkas berbahaya, logika bisnis tanda tangan dan keputusan, API integrasi, konfigurasi cloud.
2. Pemindaian image container (Trivy/Grype) di CI, termasuk paket OS.
3. TLS di staging: SSL Labs minimal A, HSTS, redirect HTTP.
4. Uji beban ringan untuk memastikan HPA dan batas memori worker.
5. Penyimpanan token: token sesi disimpan di `localStorage` browser. CSP nonce mengurangi risiko XSS; pindah ke cookie
   `HttpOnly` + `SameSite` disarankan sebelum produksi (perubahan arsitektur autentikasi, dicatat sebagai pekerjaan lanjutan).

## Cara mengulang

```
# aplikasi berjalan di localhost:3000 (web) dan localhost:8000 (API)
docker run --rm --network host -v $PWD/zap:/zap/wrk zaproxy/zap-stable zap-baseline.py -t http://localhost:3000 -r zap_web.html
docker run --rm --network host -v $PWD/zap:/zap/wrk zaproxy/zap-stable zap-api-scan.py -t http://localhost:8000/openapi.json -f openapi -r zap_api.html
pip install bandit pip-audit
bandit -r apps/api/mab_api pipeline/mab_pipeline infra/ops
pip-audit -r apps/api/requirements.txt -r pipeline/requirements.txt -r synthetic/requirements.txt
cd apps/web && npm audit
docker compose run --rm --no-deps api pytest -q tests
```
