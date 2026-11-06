# Naskah demo lengkap

> **Data rekaan untuk demonstrasi.** Semua pasien, dokter, rumah sakit, asuransi, dan klaim di demo ini fiktif.

Naskah ini memuat **semua skenario demo** platform, dari alur klaim inti sampai modul U1–U8. Tidak ada batas
durasi: pilih skenario yang relevan untuk audiens (lihat [Urutan yang disarankan](#urutan-yang-disarankan)),
atau jalankan semuanya berurutan. Setiap skenario ditulis langkah demi langkah dengan akun, tombol, dan hasil
yang harus terlihat. Kalimat bercetak miring dalam kutipan adalah contoh yang bisa diucapkan ke audiens.

Penjelasan teknis tiap modul ada di dokumen `docs/u1-…` sampai `docs/u8-…`. Rincian proses di balik layar untuk
skenario klaim ada di [skenario-unggah.md](skenario-unggah.md).

---

## Persiapan

### 1. Nyalakan aplikasi dengan data bersih

PowerShell (Windows), dari folder repo:

```powershell
git pull origin dev
docker compose down -v
docker compose up -d --build
docker compose run --rm --build synthetic
docker compose exec -T api python infra/scripts/seed_demo.py
```

Git Bash / Linux / macOS bisa memakai `make reset`.

Seed selesai bila muncul pesan "Klaim SYN-DEN-09 sengaja belum diunggah". Setelah seed:

- Dua asuransi: **Asuransi Sehat Demo** (`DEMO`, logo "SD" hijau) dan **Asuransi Pelita Demo** (`PELITA`, logo "PD" oranye).
- 29 klaim DEMO dan 6 klaim Pelita. Sebagian sudah ditelaah dan diputuskan.
- SYN-TIF-10 sudah ditunda, dan rincian tagihannya sudah diminta ke RS (untuk Skenario 13).
- SYN-GEA-06 sudah diputus "tidak dijamin", siap dibanding (untuk Skenario 14).
- 10 kasus underwriting. UW-24 sengaja belum diunggah (untuk Skenario 16).
- Riwayat klaim untuk Fraud Monitor, laporan bulanan bulan berjalan, dan API key Pelita di `data\demo_upload\api_key_PELITA.txt`.

### 2. Buka browser

Buka http://localhost:3000 dan login `staf@demo.test`. Password semua akun `demo12345`, PIN tanda tangan dokter `123456`.

Pakai pemilih **Ganti peran (demo)** di kanan atas untuk berpindah akun tanpa logout. Bila sedang membuka sebuah
klaim, ganti peran tetap membuka klaim yang sama. Ganti peran bukan akun super: setiap langkah tetap dijalankan
akun dengan peran yang benar, jadi pemisahan peran dan log audit tetap utuh. Bila lebih suka, pakai dua jendela
(biasa + incognito) untuk staf dan dokter.

| No di Ganti peran | Akun | Dipakai untuk |
|---|---|---|
| 1 | `staf@demo.test` | Unggah klaim, keputusan asuransi DEMO |
| 2 | `dokter.umum@mab.test` | Telaah kasus kuning, tanda tangan underwriting |
| 3 | `dokter.spesialis@mab.test` | Telaah kasus merah dan eskalasi |
| 4 | `manajer@demo.test` | Dashboard, Fraud Monitor, buat laporan |
| 5 | `admin@mab.test` | Aturan, tenant, API key, semua data |
| 6 | `staf@pelita.test` | Staf tenant kedua, halaman Polis |
| 7 | `tpa@mab.test` | Operator TPA untuk dua asuransi |
| 8 | `auditor@demo.test` | Auditor internal, hanya-baca |
| 9 | `faskes@demo.test` | Petugas faskes RSU Harapan Bunda |
| 10 | `peserta@demo.test` | Peserta pemilik klaim SYN-TIF-10 |
| 11 | `underwriter@demo.test` | Underwriting medis |
| 12 | `dokter.spesialis2@mab.test` | Telaah banding |

Akun lain yang hanya bisa dipakai lewat login biasa: `manajer@pelita.test` dan `auditor@ojk.test` (auditor regulator, semua tenant).

### 3. Siapkan file di File Explorer

| Untuk skenario | File |
|---|---|
| 1 (unggah satu klaim) | `data\synthetic_output\SYN-DEN-09\` (4 PDF) dan `case.json`-nya |
| 2 (unggah ZIP) | `data\demo_upload\unggah_massal_demo.zip`, dibuat dengan `docker compose exec api python infra/scripts/make_demo_zip.py` |
| 13 (dokumen susulan) | `data\synthetic_output\SYN-TIF-10\susulan\rincian_tagihan.pdf` |
| 16 (underwriting) | `data\synthetic_output\underwriting\UW-24\` (semua PDF) |

Isian formulir SYN-DEN-09 (dari `case.json`; generator memakai seed tetap, jadi nilainya sama di setiap mesin):

| Kolom | Nilai |
|---|---|
| Nomor klaim | `SYN-DEN-09` (wajib persis di mode mock) |
| Nomor polis | `POL-DEMO-8181` |
| ID peserta | `PST-15720019` |
| Nama peserta | `Fajar Rahayu` |
| Rumah sakit | `RS Mitra Medika Nusantara` |
| Nilai tagihan | `4127000` |
| Tanggal masuk / keluar | `2026-03-26` / `2026-03-30` |

Bila nilainya berbeda dari `case.json` di mesin Anda, ikuti `case.json`.

### 4. Hal yang perlu diingat soal data

Sebagian skenario mengubah data dan hanya bisa dijalankan sekali per seed:

| Skenario | Yang berubah |
|---|---|
| 1 atau 2 | SYN-DEN-09 hanya bisa diunggah sekali di DEMO. Pilih salah satu. |
| 3, 6, 8, 9 | Klaim berpindah ke status Selesai setelah diputuskan |
| 13 | SYN-TIF-10 selesai setelah dokumen susulan diterima |
| 14 | SYN-GEA-06 hanya bisa dibanding sekali |
| 16 | UW-24 hanya bisa diunggah sekali |
| 18 | Akun yang dipakai uji kunci login terkunci 15 menit |

Untuk mengulang semuanya dari awal, jalankan lagi perintah di langkah 1.

---

## Peta skenario

| No | Skenario | Modul | Akun utama | Data |
|---|---|---|---|---|
| 1 | Alur lengkap: unggah klaim DBD sampai dashboard | Inti | Staf, dokter umum, manajer | SYN-DEN-09 |
| 2 | Unggah massal ZIP | Inti | Staf | ZIP demo |
| 3 | Klaim wajar dibayar penuh, setujui massal, CSV | Inti | Staf | SYN-DEN-01..03 |
| 4 | Data pindaian meragukan | Inti | Dokter umum | SYN-DEN-06 |
| 5 | Klaim tumpang tindih | Inti | Dokter spesialis, staf | SYN-GEA-10 |
| 6 | Eskalasi dokter umum ke spesialis | Inti | Dokter umum, spesialis | SYN-DEN-08 |
| 7 | Komplikasi ditagih tanpa bukti | Inti | Dokter spesialis, staf | SYN-TIF-08 |
| 8 | Asuransi berbeda dari rekomendasi | Inti | Staf, manajer | SYN-DEN-07 |
| 9 | Aturan klinis berversi | Inti | Admin | Halaman Aturan |
| 10 | Dua asuransi, peran, dan API key | U1 | Admin, staf Pelita, TPA, auditor | Tenant DEMO & PELITA |
| 11 | Polis, benefit, dan integrasi | U2 | Staf Pelita, spesialis | SYN-GEA-02, SYN-DEN-02 Pelita |
| 12 | Fraud Monitor | U3 | Manajer | Riwayat klaim |
| 13 | Dokumen susulan: peserta, faskes, dokter | U4 | Peserta, faskes, dokter umum, staf, TPA | SYN-TIF-10 |
| 14 | Banding oleh faskes | U5 | Faskes, spesialis kedua, staf, manajer | SYN-GEA-06 |
| 15 | Audit dan laporan bulanan | U6 | Auditor, manajer, auditor OJK | SYN-GEA-06 |
| 16 | Underwriting medis calon peserta | U7 | Underwriter, dokter umum | UW-24, UW-21 |
| 17 | Dashboard dan metrik | Inti, U5 | Manajer | Semua |
| 18 | Kesiapan produksi | U8 | Terminal + browser | Health, backup, kunci login |

## Urutan yang disarankan

Semua urutan berjalan dari satu seed tanpa reset.

- **Asuransi (manajemen klaim):** 1 → 3 → 5 → 8 → 13 → 14 → 17 → 12.
- **Dokter panel MAB:** 1 → 4 → 6 → 7 → 14 → 16.
- **Regulator / kepatuhan / audit:** 10 (bagian peran) → 14 → 15 → 18 (bagian checklist).
- **TI / integrasi:** 2 → 10 (bagian API key) → 11 → 18.
- **Rumah sakit / faskes:** 13 → 14.
- **Underwriting asuransi jiwa/kesehatan:** 16.
- **Demo lengkap:** jalankan 1 sampai 18 berurutan. Skenario 15 paling menarik setelah 14, karena jejak bandingnya ikut tampil.

---

# Bagian A · Alur klaim inti

## Skenario 1 · Alur lengkap: unggah klaim DBD sampai dashboard

Alur cerita: **unggah klaim bermasalah → temuan dan bukti → dokter menelaah dan menandatangani → asuransi memutuskan → dashboard.**

### 1a. Pembuka (Staf klaim, Daftar klaim)

Tunjukkan banner kuning "Data rekaan untuk demonstrasi" dan daftar klaim yang sudah berisi.

> *"Ini portal untuk staf klaim asuransi. Setiap klaim rawat inap yang masuk dibaca sistem, dicek dengan aturan
> klinis dan AI, lalu diberi triase: hijau, kuning, atau merah. Yang hijau bisa langsung dibayar penuh; yang
> kuning dan merah harus ditelaah dokter MAB dulu. Prinsipnya: AI tidak pernah menolak klaim."*

Tunjuk kolom Triase dan Rekomendasi. Klaim kuning/merah yang belum ditandatangani dokter tampil tanpa triase,
karena asuransi belum boleh melihatnya.

### 1b. Unggah (Staf klaim)

1. Klik **Unggah klaim**, isi formulir **Satu klaim** dengan tabel di Persiapan, lampirkan 4 PDF SYN-DEN-09, klik **Kirim klaim**.
2. Halaman detail menampilkan progres: *Diterima & antre → Membaca dokumen & menilai → Rekomendasi siap*.

> *"Dokumen bisa PDF digital atau hasil pindai. Halaman pindaian di-OCR, lalu data seperti trombosit,
> hematokrit, dan jumlah pemeriksaan darah per hari diekstraksi. Setiap angka menyimpan lokasinya di dokumen."*

3. Setelah selesai, status menjadi **Menunggu dokter**. Kotak ungu menjelaskan bahwa rekomendasi baru tampil setelah ditandatangani dokter.

> *"Asuransi belum melihat temuan apa pun. Ini disengaja: selain bayar penuh, keputusan klinis harus lewat dokter."*

### 1c. Dokter umum menelaah (Ganti peran → 2. Dokter umum)

1. Buka **Antrean telaah**. SYN-DEN-09 ada di antrean dengan badge **Kuning**, diagnosis A90 Demam dengue.

> *"Kasus kuning masuk ke dokter umum, kasus merah langsung ke spesialis sebidang. Antrean diurutkan dari skor risiko tertinggi, dan kolom SLA menunjukkan sisa waktu telaah."*

2. Buka SYN-DEN-09. Tunjukkan **layar dua panel**: kiri dokumen asli, kanan temuan dan draf.
3. Pada temuan **Pemeriksaan melebihi kebutuhan (OVER_SERVICE)**, klik salah satu kutipan bukti. Panel kiri membuka halaman hasil lab dan **menyorot baris** yang dikutip.

> *"Setiap temuan wajib punya bukti. Kalau AI menyebut sesuatu tapi kutipannya tidak ditemukan di dokumen, temuan itu dibuang dan klaim tidak boleh hijau."*

4. Tunjukkan temuan **Rawat inap tanpa indikasi tercatat (ADMISSION_NOT_INDICATED)** dan rujukan pedomannya (PNPK Dengue 2021).
5. Klik **Mulai telaah**. Banner biru menunjukkan waktu telaah mulai dihitung dan kasus terkunci untuk dokter ini.
6. Buka tab **Data ekstraksi**. Tunjukkan nilai yang diekstraksi beserta kutipannya. Klik **Koreksi** pada satu field, ubah nilainya, isi catatan, simpan: nilai lama tercoret dan muncul di **Riwayat koreksi**.
7. Di kotak bawah, tunjukkan **Usulan dari draf AI** dan tiga pilihannya:
   - **Setujui draf & tanda tangan**
   - **Ubah rekomendasi** (bayar penuh / sebagian / tunda / tidak dijamin; kode alasan wajib bila berbeda dari draf)
   - **Eskalasi ke spesialis** (catatan wajib)
8. Klik **Ubah rekomendasi** → **Bayar sebagian**, nilai dibayar `3500000`, kode alasan `OVER_SERVICE`, klik **Tanda tangan**. Masukkan PIN salah sekali (`000000`) untuk menunjukkan penolakan, lalu PIN `123456`.

> *"Dokter yang memutuskan. Sistem mencatat apakah dokter setuju dengan draf AI, berapa lama telaahnya, dan alasan bila berbeda. Draf AI tetap tersimpan sebagai versi lama, jadi jejaknya bisa diaudit."*

9. Banner hijau: rekomendasi sudah ditandatangani dan terlihat di portal asuransi. Buka tab **Riwayat telaah**: catatan "Mengubah draf", alasan, dan durasi.

### 1d. Asuransi memutuskan (Ganti peran → 1. Staf klaim)

1. Halaman detail SYN-DEN-09 kini menampilkan rekomendasi **Bayar sebagian**: nilai tagihan, nilai rekomendasi, koreksi, nama dokter dan waktu tanda tangan, temuan dengan bukti, draf penjelasan untuk nasabah/RS, serta versi model, prompt, dan aturan.
2. Klik kutipan bukti: pratinjau dokumen terbuka dengan sorotan, sama seperti yang dilihat dokter.
3. Klik **Unduh PDF** untuk rekomendasi versi PDF.
4. Di **Catat keputusan perusahaan**, pilih **Setuju dengan rekomendasi** lalu **Simpan**. (Penolakan "Berbeda" tanpa alasan ditunjukkan di Skenario 8.)

> *"Keputusan akhir tetap di tangan asuransi. Kalau berbeda dari rekomendasi, alasannya wajib dicatat."*

Lanjutkan ke Skenario 17 untuk dashboard, atau ke skenario lain.

## Skenario 2 · Unggah massal ZIP

Alternatif Skenario 1 (SYN-DEN-09 hanya bisa diunggah sekali).

1. Di terminal, sekali saja: `docker compose exec api python infra/scripts/make_demo_zip.py`. Hasilnya `data\demo_upload\unggah_massal_demo.zip` berisi `manifest.xlsx`, folder `SYN-DEN-09/`, dan folder `SYN-DEN-01/`.
2. **Staf klaim** → **Unggah klaim** → **Banyak klaim (ZIP)** → pilih file → **Unggah ZIP**.
3. Hasil: "**1** klaim dibuat dan masuk antrean proses, **1** baris gagal".
   - SYN-DEN-09: **Berhasil**.
   - SYN-DEN-01: "Nomor klaim SYN-DEN-01 sudah ada". Sistem menolak unggahan ganda, dan baris yang gagal tidak menggagalkan baris lain.
4. Lanjutkan seperti Skenario 1 bagian 1c.

## Skenario 3 · Klaim wajar dibayar penuh (hijau)

1. **Staf klaim** → **Daftar klaim**. SYN-DEN-01, 02, dan 03 berstatus **Menunggu keputusan asuransi**, triase **Hijau**, rekomendasi **Bayar penuh**.
2. Buka SYN-DEN-01. Tidak ada temuan; rekomendasi bayar penuh Rp5.285.000; versi aturan dan model tercatat. Tidak ada nama dokter karena klaim hijau tidak wajib ditelaah dokter.
3. Kembali ke **Daftar klaim** → **Pilih semua hijau** → **Setujui N klaim hijau**. Ketiganya menjadi **Selesai** dengan keputusan **Setuju**.
4. Klik **Ekspor CSV**. Baris SYN-DEN-01..03 berisi `status_triase=GREEN`, `rekomendasi=PAY_FULL`, `keputusan_asuransi=AGREE`. File kolom tetap ini bisa diimpor ke sistem klaim.

> *"Klaim yang wajar dipercepat. Waktu dokter dipusatkan pada klaim yang memang bermasalah."*

## Skenario 4 · Data pindaian meragukan (SYN-DEN-06)

1. **Dokter umum** → **Antrean telaah** → SYN-DEN-06 (dengue anak dengan muntah persisten, berkas pindaian), triase **Kuning**.
2. Tidak ada temuan aturan, tetapi ada **catatan kualitas data**: nilai dari AI yang kutipannya tidak ditemukan di dokumen, dan aturan yang tidak bisa dinilai karena datanya kosong.
3. Jelaskan: nilai yang kutipannya tidak cocok dianggap "tidak diketahui", bukan "tidak ada". Karena itu klaim tidak diloloskan hijau walaupun klinisnya wajar.
4. **Mulai telaah** → tab **Data ekstraksi**. Bandingkan nilai dengan pindaian di panel kiri. Bila ada yang salah baca, **Koreksi** dan simpan.
5. **Setujui draf & tanda tangan** (PIN `123456`). Draf: **Tunda: minta dokumen / klarifikasi**.

> *"AI tidak boleh menebak. Kalau datanya meragukan, klaim naik ke dokter."*

## Skenario 5 · Klaim tumpang tindih (SYN-GEA-10)

1. **Dokter spesialis** → **Antrean telaah** → SYN-GEA-10, triase **Merah**.
2. Temuan **Klaim duplikat / tumpang tindih** (GEN-01, keparahan Tinggi): peserta yang sama punya klaim **KLM-RIWAYAT-0001** dengan tanggal rawat beririsan. Klinisnya sendiri wajar.
3. **Mulai telaah** → **Ubah rekomendasi** → **Tidak dijamin**, kode alasan `DUP_CLAIM`, catatan "Periode rawat sudah ditagihkan pada KLM-RIWAYAT-0001" → **Tanda tangan** (PIN `123456`).
4. **Ganti peran → 1. Staf klaim** → buka SYN-GEA-10. Rekomendasi **Tidak dijamin**, nilai Rp0, koreksi Rp2.568.000, alasan dan nama dokter tercatat. Catat keputusan **Setuju**.

> *"AI tidak menolak klaim. Penolakan ini keputusan dokter yang tercatat alasannya."*

## Skenario 6 · Eskalasi dokter umum ke spesialis (SYN-DEN-08)

1. **Dokter spesialis** → **Antrean telaah**. SYN-DEN-08 berlabel **eskalasi**: kasusnya kuning, tetapi dokter umum meminta pendapat spesialis (dilakukan seed).
2. Tab **Riwayat telaah**: catatan eskalasi dokter umum ("Mohon pendapat spesialis sebelum tanda tangan…") dan waktunya.
3. Temuan **Diagnosis dengue tanpa konfirmasi laboratorium** (DEN-02): NS1 dan IgM negatif, trombosit normal. Klik kutipan untuk melihat hasil lab yang disorot.
4. **Mulai telaah** → **Setujui draf & tanda tangan**. Draf: **Tunda**, untuk klarifikasi dasar diagnosis ke DPJP.
5. Riwayat telaah kini mencatat dua langkah: eskalasi oleh dokter umum dan tanda tangan oleh spesialis.

Untuk menunjukkan eskalasi secara langsung: **Dokter umum** → buka klaim kuning lain di antrean → **Mulai telaah** → **Eskalasi ke spesialis** (catatan wajib). Klaim pindah ke antrean spesialis.

## Skenario 7 · Komplikasi ditagih tanpa bukti (SYN-TIF-08)

1. **Dokter spesialis** → **Antrean telaah** → SYN-TIF-08, triase **Merah**.
2. Temuan **Komplikasi tifoid ditagihkan tanpa bukti** (TIF-05, Tinggi): diagnosis sekunder K75.9 (hepatitis tifosa) ditagihkan, tetapi resume, CPPT, dan lab tidak memuat tanda klinis atau enzim hati yang mendukung. Rujukan KMK 364/2006 tampil di temuan.
3. **Mulai telaah** → **Ubah rekomendasi** → **Bayar sebagian**, nilai `4500000`, kode alasan `COMPLICATION_UNSUPPORTED` → **Tanda tangan**.
4. **Ganti peran → 1. Staf klaim**: tagihan Rp5.050.000, rekomendasi Rp4.500.000, koreksi Rp550.000, temuan berbukti, dan draf penjelasan untuk RS. Klik **Unduh PDF**.

## Skenario 8 · Asuransi berbeda dari rekomendasi (SYN-DEN-07)

1. **Staf klaim** → buka SYN-DEN-07, status **Menunggu keputusan asuransi**.
2. Rekomendasi **Bayar sebagian** ditandatangani dokter spesialis (seed mengubah draf AI menjadi 80% tagihan). Temuan DEN-01 (ditagih sebagai DBD tanpa penurunan trombosit dan perembesan plasma) dan DEN-03 (rawat inap tanpa indikasi).
3. Di **Catat keputusan perusahaan**, pilih **Berbeda**, lalu **Simpan** tanpa alasan → muncul pesan alasan wajib diisi.
4. Isi alasan, mis. "Dibayar sesuai negosiasi dengan RS", lalu **Simpan**. Status **Selesai**, keputusan **Berbeda**.
5. **Ganti peran → 4. Manajer klaim** → **Dashboard**: jumlah keputusan "berbeda" bertambah.

> *"MAB memberi rekomendasi; keputusan akhir milik asuransi dan tercatat lengkap."*

## Skenario 9 · Aturan klinis berversi

1. **Ganti peran → 5. Admin MAB** → **Aturan & pengguna**.
2. Tunjukkan aturan klinis per penyakit (dengue, tifoid, gastroenteritis), aturan benefit, dan versinya (mis. `rules-2026.11-demo`).

> *"Aturan klinis adalah file konfigurasi berversi. Dokter MAB bisa mengubah ambang tanpa mengubah kode, dan setiap rekomendasi mencatat versi aturan yang dipakai."*

---

# Bagian B · Modul U1–U8

## Skenario 10 · Dua asuransi, peran, dan API key (U1)

1. **Admin MAB** → **Tenant & API key**. Tunjukkan dua tenant: logo, ambang merah Pelita 20 (DEMO 40), SLA dokter umum/spesialis Pelita 8/24 jam (DEMO 24/48), daftar aturan aktif.
2. Buat API key untuk Pelita: isi nama akun layanan → **Buat API key**. Salin kuncinya; kunci hanya tampil sekali.
3. **Ganti peran → 6. Staf Asuransi Pelita**. Header berganti logo dan warna oranye Pelita; hanya 6 klaim Pelita yang terlihat.
4. **Ganti peran → 3. Dokter spesialis**. Antrean berisi kasus dari dua asuransi. SYN-DEN-08, SYN-GEA-07, dan SYN-TIF-07 milik Pelita ada di sini sebagai **merah** (karena ambang Pelita 20), padahal di DEMO kuning. Kolom SLA menunjukkan sisa waktu 24 jam.
5. Bila Skenario 1 sudah dijalankan: buka rekomendasi SYN-DEN-09 DEMO (kuning) dan bandingkan dengan SYN-DEN-09 Pelita (merah). Versi aturan Pelita tercatat `rules-2026.11-demo+PELITA.v1`.
6. **Ganti peran → 7. Operator TPA**: daftar klaim berisi kedua asuransi, dan di **Unggah klaim** ada pilihan asuransi.
7. **Ganti peran → 8. Auditor**, lalu **9. Petugas faskes**, lalu **10. Peserta**: masing-masing hanya melihat cakupannya. Auditor tidak bisa memutuskan; faskes dan peserta hanya melihat status.
8. PowerShell, dengan kunci dari langkah 2:
   ```powershell
   $KEY = "mab_xxxxxxxx_...."
   curl.exe -H "X-API-Key: $KEY" http://localhost:8000/integrations/v1/whoami
   curl.exe -H "X-API-Key: $KEY" "http://localhost:8000/integrations/v1/claims?status=AWAITING_DECISION"
   ```
   Hanya klaim Pelita yang kembali. Draf yang masih menunggu dokter tidak ikut terkirim.

> *"Satu platform untuk banyak asuransi dan TPA. Setiap asuransi punya ambang, SLA, dan aturannya sendiri, dan datanya terpisah."*

## Skenario 11 · Polis, benefit, dan integrasi (U2)

1. **Staf Asuransi Pelita** → **Polis**: dua plan benefit, polis peserta, **Riwayat integrasi** (impor polis, FHIR, API, SFTP) dan webhook terkirim.
2. **Daftar klaim**: SYN-DEN-01 berlabel *via FHIR*, SYN-GEA-01 *via API*, SYN-TIF-01 *via SFTP*.
3. **Ganti peran → 3. Dokter spesialis** → buka SYN-GEA-02 milik Pelita: temuan **BEN-04** (melebihi sisa limit) dengan kutipan data polis dan usulan koreksi. Buka SYN-DEN-02 Pelita: temuan **BEN-05** (kelas kamar di atas hak) dengan baris kamar di rincian tagihan.
4. Tanda tangani salah satunya (PIN `123456`). **Ganti peran → 6. Staf Asuransi Pelita** → **Polis → Riwayat integrasi**: muncul webhook `claim.recommendation_released` dan isi yang diterima penerima demo.
5. Di laptop, buka `data\sftp\PELITA\keluar\status_klaim.csv`: status SYN-TIF-01/02 untuk sistem asuransi.
6. PowerShell:
   ```powershell
   $KEY = Get-Content data\demo_upload\api_key_PELITA.txt
   curl.exe -H "X-API-Key: $KEY" http://localhost:8000/integrations/v1/fhir/ClaimResponse/SYN-DEN-01
   ```
   Hasilnya rekomendasi dalam format FHIR R4 `ClaimResponse`.

Untuk audiens TI: SFTP demo ada di port `2222` (login `demo` atau `pelita`, password `demo12345`). Contoh kirim klaim lewat API dan FHIR ada di [u2-integrasi-benefit.md](u2-integrasi-benefit.md).

> *"Klaim bisa masuk dari portal, API, FHIR, atau SFTP, dan dicek terhadap benefit polis peserta. Hasilnya dikirim balik lewat webhook, API, atau file."*

## Skenario 12 · Fraud Monitor (U3)

1. **Ganti peran → 4. Manajer klaim** → **Fraud Monitor**.
2. **Provider berisiko**: RS Cempaka Rekaan (lama rawat), dr. Prita Pratama (biaya per hari), dr. Miftah Halim (pemeriksaan lab). Klik satu baris untuk menyaring sinyalnya.
3. Klik sinyal **FRD-01**: angka pembanding, sebaran indeks semua RS, graf RS–dokter, dan klaim dengan lama rawat tertinggi.
4. Klik sinyal **FRD-05**: graf rekening bersama, yaitu enam peserta dengan alamat masing-masing dan RS tempat mereka dirawat.
5. Klik sinyal **FRD-07**: dua panah rujukan yang saling berbalas. Isi telaah "Pola terkonfirmasi" lalu simpan. Klaimnya tidak berubah.
6. Buka detail klaim mana pun: kartu **Analitik fraud** menampilkan skor fraud klaim, terpisah dari rekomendasi klinis.
7. (Opsional) Unggah klaim apa pun dengan ID peserta `PST-H-9002`, lalu jalankan analisis. Kartu fraud klaim itu menampilkan **FRD-09** (rawat inap tumpang tindih).

> *"Analitik fraud melihat pola lintas klaim: RS, dokter, rekening, alamat, dan rujukan. Hasilnya sinyal untuk diselidiki tim investigasi, bukan keputusan atas klaim."*

Laporan evaluasi dibuat ulang dengan `docker compose exec api python -m evaluation.fraud_eval`.

## Skenario 13 · Dokumen susulan: peserta, faskes, dokter (U4)

Seed sudah membuat SYN-TIF-10 ditunda dokter (rincian tagihan tidak dilampirkan, temuan GEN-03 `DOC_MISSING`) dan asuransi sudah meminta dokumennya ke RS.

1. **Ganti peran → 10. Peserta**. SYN-TIF-10 berstatus "Menunggu dokumen dari rumah sakit". **Kotak masuk** berisi email pemberitahuannya.
2. **Ganti peran → 9. Petugas faskes**. Portal Faskes menaruh SYN-TIF-10 paling atas. Buka klaimnya, pilih `data\synthetic_output\SYN-TIF-10\susulan\rincian_tagihan.pdf` pada "Rincian tagihan", lalu kirim.
3. Tunggu worker memproses ulang (beberapa detik sampai satu menit).
4. **Ganti peran → 2. Dokter umum**. SYN-TIF-10 muncul lagi di antrean, ditugaskan ke dokter yang sama. GEN-03 hilang dan tagihan kini dinilai aturan. **Mulai telaah** → tanda tangan (PIN `123456`).
5. **Ganti peran → 1. Staf klaim**. Kotak masuk berisi email "dokumen susulan sudah diterima". Detail klaim menampilkan riwayat permintaan. Catat keputusan.
6. **Ganti peran → 10. Peserta**. Status "Selesai", ada penjelasan keputusan, nama dokter penelaah, dan linimasa lengkap.
7. **Ganti peran → 7. Operator TPA** → **Ringkasan TPA** untuk kedua asuransi. "Lihat klaim" menyaring daftar klaim per asuransi.

> *"Rumah sakit dan peserta melihat status yang sama dengan asuransi. Kekurangan dokumen tidak lagi lewat telepon atau email terpisah."*

## Skenario 14 · Banding oleh faskes (U5)

Seed sudah membuat SYN-GEA-06 (Asuransi Sehat Demo, RSU Harapan Bunda) diputus "tidak dijamin" oleh spesialis dan disetujui asuransi.

1. **Ganti peran → 9. Petugas faskes** → buka SYN-GEA-06. Di kartu **Banding**, klik "Ajukan banding", pilih "Penilaian medis", tulis alasan (mis. "Pasien muntah terus dan tidak bisa minum, tercatat di CPPT hari pertama"), lalu kirim.
2. **Ganti peran → 3. Dokter spesialis**. SYN-GEA-06 tidak ada di antreannya karena dia penelaah awal.
3. **Ganti peran → 12. Dokter spesialis kedua**. Kasus sudah ditugaskan kepadanya, dan banner banding menampilkan alasan faskes. Pilih "Ubah", ganti menjadi **bayar penuh**, tulis pertimbangan telaah ulang, lalu tanda tangan dengan PIN `123456`.
4. **Ganti peran → 1. Staf klaim**. Kartu Banding di detail klaim menunjukkan hasil telaah ulang. Catat keputusan.
5. **Ganti peran → 9. Petugas faskes**: status "Selesai", hasil "keputusan awal dibatalkan", linimasa banding lengkap. Banding kedua tidak bisa diajukan.
6. **Ganti peran → 4. Manajer klaim** → **Dashboard**: bagian **Banding (sengketa)**: jumlah terbuka dan selesai, keputusan berubah, lewat SLA, dan hasil banding.

> *"Banding selalu ditelaah dokter yang berbeda dari penelaah awal, dan seluruh prosesnya tercatat."*

## Skenario 15 · Audit dan laporan bulanan (U6)

Paling baik setelah Skenario 14.

1. **Ganti peran → 8. Auditor** → **Laporan & Audit**. Ketik `SYN-GEA-06` di "Telusuri keputusan klaim".
2. Baca mata rantai keputusannya, lalu ikuti linimasa dari unggah, telaah, keputusan, banding, sampai putusan ulang. Klik **Unduh PDF** jejak.
3. Tab **Log audit**: saring dengan kelompok "Telaah dokter" atau pengguna `dokter.spesialis`, lalu ekspor ke Excel.
4. Tab **Laporan bulanan**: buka laporan bulan berjalan, unduh PDF dan Excel. Auditor tidak melihat tombol "Buat laporan".
5. **Ganti peran → 4. Manajer klaim** → **Laporan & Audit** → **Laporan bulanan** → buat ulang laporan: nomor revisi naik.
6. Logout, login `auditor@ojk.test`: laporan kedua tenant dan laporan seluruh platform terlihat.

> *"Setiap keputusan bisa ditelusuri sampai dokumen, temuan, dokter, dan waktu. Log audit tidak bisa diubah."*

## Skenario 16 · Underwriting medis calon peserta (U7)

1. **Ganti peran → 11. Underwriter** → **Underwriting**. Tunjukkan UW-01 (terima standar, sudah diputus), UW-02 (menunggu underwriter), dan kasus yang menunggu dokter.
2. Klik "Ajukan calon peserta", unggah semua PDF di `data\synthetic_output\underwriting\UW-24\`. Hasilnya: IMT di atas 40 dan HbA1c 8–9,9 memberi total debit 200, sehingga draf menjadi **usulan tolak** dan kasus masuk antrean dokter. Underwriter tidak bisa memutus kasus ini sendiri.
3. **Ganti peran → 2. Dokter umum** → **Underwriting**, tab "Menunggu dokter".
   - Buka **UW-21**: HbA1c 8,4% padahal kuesioner menjawab tidak diabetes. Ada catatan dugaan tidak diungkap.
   - Buka **UW-24**: lihat temuan debit dengan buktinya, setujui draf, lalu tanda tangan dengan PIN `123456`.
4. **Ganti peran → 11. Underwriter** → buka UW-24 → putuskan "Tolak", lalu unduh PDF rekomendasinya.

> *"Prinsip yang sama dengan klaim: usulan tolak atau bersyarat selalu ditandatangani dokter. Debit dan loading di demo memakai tabel contoh; pada pemakaian sungguhan nilainya dari tabel aktuaria klien."*

## Skenario 17 · Dashboard dan metrik

**Ganti peran → 4. Manajer klaim** → **Dashboard**:

- Jumlah klaim per triase dan per status, berapa yang masih menunggu dokter.
- **Nilai koreksi** dibanding total tagihan.
- **Temuan terbanyak** dan **rumah sakit dengan temuan terbanyak**.
- Waktu proses rata-rata (unggah sampai rekomendasi awal).
- **Persetujuan dokter atas draf AI** dan rata-rata waktu telaah. Ini metrik utama untuk menilai apakah AI benar-benar membantu dokter.
- Keputusan asuransi "berbeda" (Skenario 8) dan metrik banding (Skenario 14).

> *"Untuk asuransi, hanya rekomendasi yang sudah dirilis yang dihitung. Tim MAB melihat semuanya dari akun admin."*

Bandingkan dengan **Ganti peran → 5. Admin MAB** → **Dashboard** untuk tampilan seluruh platform.

## Skenario 18 · Kesiapan produksi (U8)

Untuk audiens TI, keamanan, dan kepatuhan.

1. Buka http://localhost:8000/health/ready: `database`, `redis`, dan `storage` semuanya `ok`.
2. Buka http://localhost:8000/metrics: jumlah dan latensi permintaan per pola rute, panjang antrean, job gagal.
3. Di terminal:
   ```powershell
   docker compose run --rm ops backup
   docker compose run --rm ops list
   ```
   Backup berisi database dan semua dokumen dengan checksum, dan sudah diuji dipulihkan. Lihat [runbook-operasi.md](runbook-operasi.md).
4. Penguncian login: logout, login `peserta@demo.test` dengan password salah 5 kali. Percobaan berikutnya ditolak meski password benar ("Terlalu banyak percobaan login gagal"). Jalankan skenario ini terakhir, karena akunnya terkunci 15 menit (cara membuka ada di tabel di bawah). PIN tanda tangan dokter juga terkunci setelah 5 kali salah.
5. Tunjukkan [checklist UU PDP](u8-checklist-uu-pdp.md): aplikasi menolak start di staging/produksi dengan rahasia bawaan, dan menolak `REAL_DATA_ENABLED=true` sebelum syarat teknis terpenuhi. Deploy staging di cloud tinggal menunggu pilihan penyedia.

> *"Data sungguhan baru boleh masuk setelah checklist ini ditandatangani. Sebagian syaratnya dipaksa langsung oleh kode."*

---

## Penutup

Poin yang bisa disampaikan di akhir demo:

- AI tidak pernah menolak klaim atau calon peserta. Semua hasil selain bayar penuh/terima standar ditandatangani dokter.
- Setiap temuan punya bukti di dokumen, dan setiap aksi tercatat di log audit yang tidak bisa diubah.
- Aturan klinis, benefit, fraud, dan underwriting adalah file berversi.
- Laporan evaluasi ada di `evaluation/reports/`. Sampaikan dengan jujur: angkanya dari data sintetis dan LLM mock, jadi menguji alur dan aturan, bukan kualitas model AI.
- Tahap berikutnya: validasi aturan oleh dokter panel, uji dengan LLM sungguhan, staging di cloud, uji penetrasi pihak ketiga, dan data pilot yang disamarkan setelah checklist UU PDP disetujui.

## Bila ada yang tidak berjalan

| Masalah saat demo | Tindakan cepat |
|---|---|
| SYN-DEN-09 sudah ada di daftar DEMO | Sudah diunggah sebelumnya. Pakai SYN-DEN-08 (antrean spesialis) untuk alur dokter, atau reset (Persiapan langkah 1). |
| Klaim lama di "Diproses" | Worker sedang OCR; tunggu beberapa detik. Cek `docker compose logs -f worker`. |
| Klaim "Gagal diproses" | Pastikan nomor klaim persis `SYN-DEN-09` (mode mock mencari jawaban berdasarkan nomor klaim). |
| Antrean dokter kosong | Pastikan akunnya tepat: kuning ke dokter umum, merah ke spesialis, banding ke spesialis kedua. |
| Klaim tidak ada di antrean yang disebut | Hasil OCR bisa sedikit berbeda di mesin lain. Cari di **Daftar klaim** sebagai Admin MAB. |
| SYN-TIF-10 tidak muncul lagi setelah dokumen susulan | Tunggu worker sampai satu menit, lalu muat ulang. Cek `docker compose logs -f worker`. |
| Tombol "Ajukan banding" tidak ada | SYN-GEA-06 sudah pernah dibanding. Reset untuk mengulang. |
| UW-24 ditolak saat diunggah | Sudah diunggah sebelumnya. Reset untuk mengulang. |
| File `api_key_PELITA.txt` atau ZIP demo tidak ada | Jalankan ulang seed, atau `make_demo_zip.py` untuk ZIP. |
| "Terlalu banyak percobaan login gagal" | Akun dikunci 15 menit setelah 5 password salah (PIN dokter juga). Buka kuncinya: `docker compose exec redis sh -c "redis-cli --scan --pattern 'mab:fail:*' \| xargs -r redis-cli del"`. |
