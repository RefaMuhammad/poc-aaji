# U7 · Underwriting medis

Data rekaan untuk demonstrasi.

U7 menambahkan halaman **Underwriting** untuk menilai calon peserta sebelum polis terbit. Alurnya sama
dengan klaim: dokumen dibaca dengan OCR dan LLM, aturan YAML berversi diterapkan, lalu sistem menyusun
**draf** rekomendasi beserta buktinya.

Ada empat rekomendasi: **terima standar**, **terima dengan syarat** (loading premi dan/atau pengecualian),
**tunda**, dan **tolak**.

Jaminannya sama dengan klaim: **sistem tidak pernah menolak sendiri**. Selain "terima standar", semua
rekomendasi wajib ditelaah dan ditandatangani dokter (dengan PIN) sebelum underwriter boleh memutuskannya.

## Alur

1. **Underwriter mengajukan.** Underwriter (`underwriter@demo.test`) mengunggah SPAJ, kuesioner kesehatan,
   hasil MCU, hasil laboratorium, dan surat keterangan dokter bila ada. File boleh PDF, JPG, atau PNG.
2. **Sistem memproses** (worker, job `process_underwriting`):
   - Membaca dokumen. PDF digital dibaca langsung, pindaian dibaca dengan OCR.
   - Mengenali jenis dokumen dari judulnya, dengan cadangan LLM lalu nama file.
   - Mengekstrak fakta dengan LLM (prompt `uw_extract_v1`). Setiap nilai menyimpan id baris dokumen sumbernya.
   - Menghitung field turunan: usia pada tanggal SPAJ dan IMT.
   - Menerapkan `rules/aturan_underwriting_demo.yaml`.
3. **Pengajuan diarahkan:**
   - Ke **underwriter** bila draf "terima standar" dan semua data wajib terbaca.
   - Ke **dokter** bila draf bersyarat, tunda, atau tolak, ada data yang kurang, atau ada catatan, misalnya
     dugaan jawaban kuesioner tidak sesuai.
4. **Dokter panel** membuka antrean "Menunggu dokter" dan membaca temuan beserta kutipan baris dokumennya.
   Dokter lalu **menyetujui draf** atau **mengubahnya**, dan menandatangani dengan PIN. Mengubah draf wajib
   disertai catatan.
5. **Underwriter memutuskan.** Keputusan selain terima standar harus **sama** dengan rekomendasi yang
   ditandatangani dokter. Underwriter boleh memilih terima standar, yang lebih menguntungkan calon peserta,
   asalkan menulis alasannya. Premi akhir dihitung dari premi dasar SPAJ ditambah loading.
6. **PDF rekomendasi** bisa diunduh kapan saja. Isinya rekomendasi, temuan, bukti, versi, dan sidik SHA-256
   dokumen.

## Aturan underwriting (`uw-2026.11-demo`)

Aturan memakai ekspresi kondisi yang sama dengan aturan klinis (aman, tanpa `eval`). Kelompok field-nya
adalah `applicant`, `vital`, `lab`, `history`, dan `doctor`, dan setiap field tercatat di `kamus_data`.

Setiap aturan punya satu atau lebih akibat:

| Akibat | Arti |
|---|---|
| `debit` | Poin risiko (sistem rating numerik). Total debit menentukan kelas dan loading. |
| `pengecualian` | Penyakit yang dikecualikan dari pertanggungan. |
| `keputusan: tunda` | Ditangguhkan sampai syarat terpenuhi. |
| `keputusan: tolak` | Usulan tolak, selalu ke dokter. |
| `catatan` | Temuan informatif, dikirim ke dokter. |

Kelas risiko dan loading **contoh** (1 debit = 1% premi dasar):

| Kelas | Total debit | Rekomendasi |
|---|---|---|
| Standar | 0 | Terima standar, atau bersyarat bila ada pengecualian |
| Substandar 1 | 1–25 | Terima dengan syarat |
| Substandar 2 | 26–50 | Terima dengan syarat |
| Substandar 3 | 51–100 | Terima dengan syarat |
| Substandar 4 | 101–150 | Terima dengan syarat |
| (di atas 150) | > 150 | Usulan tolak |

Aturan yang ada:

- IMT: obesitas I, II, III, dan berat kurang.
- Tekanan darah: derajat 1 dan 2, krisis (tunda), dan hipertensi terkontrol.
- HbA1c: diabetes terkontrol, kontrol sedang, dan tidak terkontrol (tolak).
- Kolesterol dan LDL.
- SGPT: naik ringan, atau di atas 3x batas atas (tunda).
- HBsAg positif: debit ditambah pengecualian penyakit hati.
- Kreatinin (sampai tolak) dan protein urin.
- EKG iskemia (tunda) dan riwayat PJK.
- Kanker dalam 5 tahun (tunda), asma (pengecualian), menunggu operasi (tunda), hamil (tunda), dan perokok.
- Dugaan jawaban kuesioner tidak sesuai, dan riwayat penyakit kronis tanpa surat dokter.

Pengaman tambahan:

- **Data wajib.** Bila dokumen wajib (SPAJ, kuesioner, MCU, lab) tidak ada, atau field wajib tidak terbaca,
  sistem tidak menyimpulkan terima standar atau loading yang mungkin terlalu rendah. Draf menjadi **tunda**
  (`INCOMPLETE_DATA`) dan kasus dikirim ke dokter.
- **Batas debit.** Total debit di atas 150 menambah temuan `UW-DEBIT-MAX` (usulan tolak) dengan bukti dari
  temuan debit yang menyusunnya.
- **Aturan yang tidak bisa dinilai** karena data kosong dicatat dan juga membuat kasus dikirim ke dokter.

Angka debit, kelas, dan loading di file ini adalah contoh. Pada pemakaian sungguhan nilainya diambil dari
tabel underwriting dan aktuaria klien atau reasuradur, lalu ditelaah dokter dan aktuaris klien. Sistem hanya
menerapkan tabel itu. Ini mitigasi risiko "loading premi tidak akurat" di rencana.

## Data sintetis dan evaluasi

`python -m synthetic.generate_underwriting` membuat **35 kasus** di `data/synthetic_output/underwriting/`.
Perintah ini juga ikut dijalankan oleh `docker compose run --rm --build synthetic`. Isinya:

- Satu folder per kasus berisi `case.json`, `ground_truth.json`, dan PDF tiap dokumen.
- `kunci_jawaban_underwriting.csv`.

Skenarionya:

- 8 kasus sehat.
- Perokok, obesitas I/II, hipertensi (terkontrol, derajat 1, derajat 2, krisis).
- Diabetes (terkontrol, tidak diungkap di kuesioner, tidak terkontrol).
- Dua kombinasi, salah satunya total debit di atas batas.
- Asma, hepatitis B, SGPT tinggi, kanker 2 tahun lalu, hamil, menunggu operasi.
- Gangguan ginjal berat, kolesterol tinggi + perokok, EKG iskemia, PJK stabil.
- Hipertensi tanpa surat dokter.

Sebagian surat dokter dan hasil MCU dibuat sebagai **pindaian** (miring, buram, stempel), supaya OCR benar-benar
diuji.

**Kunci jawaban ditulis per skenario oleh penyusun kasus, bukan dihitung dari mesin aturan.** Jadi evaluasi
menguji pipeline dan aturan sekaligus.

```
python -m evaluation.underwriting_eval
```

Laporan ditulis ke `evaluation/reports/underwriting_<llm>_<ocr>.md`. Hasil saat ini (LLM tiruan):

| Ukuran | RapidOCR | Tanpa OCR |
|---|---|---|
| Akurasi kelas risiko | **100% (35/35)** | 88,6% |
| Akurasi rekomendasi | 100% | 88,6% |
| Akurasi ekstraksi field | 100% | 95,1% |
| Usulan selain terima standar tanpa telaah dokter | **0** | **0** |
| Usulan tolak tanpa telaah dokter | **0** | **0** |

Tanpa OCR, MCU hasil pindaian tidak terbaca. Keempat kasus yang meleset menjadi "tunda: data belum lengkap"
dan dikirim ke dokter. Tidak ada yang lolos sebagai terima standar.

Dengan LLM tiruan, angka ini mengukur pembacaan dokumen, OCR, bukti, dan aturan, **bukan kualitas model AI**.
Untuk mengukur model sungguhan, jalankan dengan `LLM_PROVIDER=deepseek`.

## Peran

| Peran | Underwriting |
|---|---|
| Underwriter (`underwriter@demo.test`) | Ajukan, lihat pengajuan tenant sendiri, putuskan. Tidak melihat data klaim. |
| Dokter panel (umum dan spesialis) | Antrean "Menunggu dokter" dan pengajuan yang pernah ditelaahnya. Telaah dan tanda tangan (PIN). |
| Auditor | Hanya-baca: tenant sendiri, atau semua tenant untuk auditor regulator. |
| Admin MAB | Hanya-baca, semua tenant. |

Peran lain (staf/manajer klaim, TPA, faskes, peserta) tidak punya akses. Izin baru di `rbac.py`:

- `UW_VIEW`
- `UW_SUBMIT` dan `UW_DECIDE` (underwriter)
- `UW_SIGN` (dokter)

## API

| Endpoint | Peran |
|---|---|
| `GET /underwriting/applications` | underwriter, dokter, auditor, admin (sesuai cakupan) |
| `POST /underwriting/applications` (multipart `files`, `insurer_id` opsional) | underwriter |
| `GET /underwriting/applications/{id}` | sesuai cakupan |
| `GET /underwriting/applications/{id}/documents/{doc_id}` | sesuai cakupan |
| `POST /underwriting/applications/{id}/sign` (`action` AGREE/MODIFY, `recommendation`, `risk_class`, `loading_pct`, `exclusions`, `notes`, `pin`) | dokter |
| `POST /underwriting/applications/{id}/decision` (`decision`, `notes`) | underwriter |
| `GET /underwriting/applications/{id}/pdf` | sesuai cakupan |
| `GET /underwriting/rules` | sesuai cakupan |

Peristiwa audit baru (kelompok "Underwriting" di Laporan & Audit):

- `UW_SUBMITTED`, `UW_PROCESSED`, `UW_FAILED`
- `UW_SIGNED`, `UW_SIGN_PIN_FAILED`, `UW_DECIDED`
- `UW_PDF_DOWNLOADED`, `UW_DOCUMENT_VIEWED`

`UW_PROCESSED` mencatat versi aturan, model, prompt, dan OCR.

## Database (migrasi `0009`)

| Tabel | Isi |
|---|---|
| `uw_applications` | Nomor pengajuan (`UWA-<tahun>-<urut>`), tenant, status (QUEUED, PROCESSING, AWAITING_DOCTOR, AWAITING_UNDERWRITER, DECIDED, FAILED), data SPAJ hasil ekstraksi (nama, jenis kelamin, tanggal lahir, produk, UP, premi dasar) |
| `uw_documents` | File, jenis, SHA-256, lokasi penyimpanan |
| `uw_assessments` | Draf sistem yang dibekukan per pemrosesan: field + bukti, temuan, aturan yang dilewati, kutipan baris, total debit, kelas, loading, pengecualian, rekomendasi, alasan ke dokter, versi aturan/model/prompt/OCR |
| `uw_reviews` | Tanda tangan dokter: setujui/ubah, rekomendasi final, kelas, loading, pengecualian, catatan |
| `uw_decisions` | Keputusan underwriter, rujukan ke tanda tangan dokter, premi akhir |

## Demo

1. Ambil kode terbaru, buat ulang data sintetis, lalu seed:
   ```powershell
   git pull origin dev
   docker compose down -v
   docker compose up -d --build
   docker compose run --rm --build synthetic
   docker compose exec -T api python infra/scripts/seed_demo.py
   ```
   Seed mengajukan 10 kasus atas nama underwriter, lalu dokter umum menandatangani 3 dan underwriter memutus 3.
   UW-24 sengaja belum diunggah.
2. Masuk sebagai `underwriter@demo.test` dan buka **Underwriting**. Lihat UW-01 (terima standar, sudah
   diputus), UW-02 (menunggu underwriter), dan kasus yang menunggu dokter.
3. Unggah semua PDF di `data/synthetic_output/underwriting/UW-24/` lewat "Ajukan calon peserta". Hasilnya:
   IMT di atas 40 dan HbA1c 8–9,9 memberi total debit 200, sehingga draf menjadi **usulan tolak** dan kasus
   masuk antrean dokter. Underwriter tidak bisa memutus.
4. Masuk sebagai `dokter.umum@mab.test` dan buka **Underwriting**, tab "Menunggu dokter".
   - Buka UW-21: HbA1c 8,4% padahal kuesioner menjawab tidak diabetes. Ada catatan dugaan tidak diungkap.
   - Buka UW-24, setujui draf, lalu tanda tangan dengan PIN `123456`.
5. Kembali sebagai underwriter, putuskan UW-24 "Tolak", lalu unduh PDF rekomendasinya.

## Batasan POC

- Debit, kelas risiko, dan loading memakai tabel **contoh**. Belum ada tabel dari klien atau reasuradur.
- Satu produk rekaan. Batas usia masuk, UP maksimum per usia (non-medical limit), dan pemeriksaan wajib
  per UP belum dimodelkan.
- Semua dokter panel boleh menandatangani. Belum ada aturan "kasus tertentu wajib spesialis" atau medical
  underwriter khusus.
- Dokumen tambahan belum bisa diminta dari calon peserta lewat sistem. Pengajuan baru harus diunggah ulang.
- Pengecualian ditulis sebagai teks. Belum dipetakan ke kode ICD-10 untuk dicek otomatis saat klaim.
- Polis belum diterbitkan dari keputusan underwriting (belum terhubung ke data polis U2).
