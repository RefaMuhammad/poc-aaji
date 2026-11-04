# Naskah demo 10 menit

> **Data rekaan untuk demonstrasi.** Semua pasien, dokter, rumah sakit, dan klaim di demo ini fiktif.

Alur cerita: **unggah klaim DBD bermasalah → lihat temuan dan bukti → dokter menelaah dan menandatangani → asuransi memutuskan → dashboard.**

## Persiapan (sebelum audiens datang, ±5 menit)

1. Nyalakan aplikasi dan kosongkan data lama:
   - Git Bash / Linux / macOS: `make reset` (atau `bash infra/scripts/reset_demo.sh`)
   - PowerShell: `docker compose down -v`, `docker compose up -d --build`, tunggu http://localhost:8000/health, lalu `docker compose exec api python infra/scripts/seed_demo.py`
2. Pastikan seed selesai dengan pesan "Klaim SYN-DEN-09 sengaja belum diunggah".
3. Siapkan dua jendela browser di http://localhost:3000:
   - **Jendela A (biasa):** login `staf@demo.test`
   - **Jendela B (incognito):** login `dokter.umum@mab.test`
4. Siapkan folder `data/synthetic_output/SYN-DEN-09/` di File Explorer (4 PDF) dan buka `case.json`-nya untuk menyalin isian formulir.

Isian formulir SYN-DEN-09 (dari `case.json`, generator memakai seed tetap jadi nilainya sama di setiap mesin):

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

Password semua akun `demo12345`, PIN dokter `123456`.

---

## 0:00–1:00 · Pembuka (Jendela A, Daftar klaim)

Tunjukkan banner kuning "Data rekaan untuk demonstrasi" dan daftar klaim yang sudah berisi.

> "Ini portal untuk staf klaim asuransi. Setiap klaim rawat inap yang masuk dibaca sistem, dicek dengan aturan klinis dan AI, lalu diberi triase: hijau, kuning, atau merah. Yang hijau bisa langsung dibayar penuh; yang kuning dan merah harus ditelaah dokter MAB dulu. Prinsipnya: **AI tidak pernah menolak klaim**."

Tunjuk kolom Triase dan Rekomendasi. Sebut bahwa klaim kuning/merah yang belum ditandatangani dokter tampil tanpa triase, karena asuransi belum boleh melihatnya.

## 1:00–2:30 · Unggah klaim DBD (Jendela A)

1. Klik **Unggah klaim**, isi formulir **Satu klaim** dengan tabel di atas, lampirkan 4 PDF SYN-DEN-09, klik **Kirim klaim**.
2. Halaman detail terbuka dan menampilkan progres: *Diterima & antre → Membaca dokumen & menilai → Rekomendasi siap*.

> "Dokumen bisa PDF digital atau hasil pindai. Halaman pindaian di-OCR, lalu data seperti trombosit, hematokrit, dan jumlah pemeriksaan darah per hari diekstraksi. Setiap angka menyimpan lokasinya di dokumen."

3. Setelah selesai, status menjadi **Menunggu dokter** dan kotak ungu menjelaskan bahwa rekomendasi akan tampil setelah ditandatangani dokter.

> "Asuransi belum melihat temuan apa pun. Ini disengaja: selain bayar penuh, keputusan klinis harus lewat dokter."

(Opsional, 20 detik) Sebut bahwa ada juga unggah massal ZIP + `manifest.xlsx` di halaman yang sama.

## 2:30–5:30 · Dokter umum menelaah (Jendela B)

1. Muat ulang **Antrean telaah**. SYN-DEN-09 ada di antrean dengan badge **Kuning**, diagnosis A90 Demam dengue.

> "Kasus kuning masuk ke dokter umum, kasus merah langsung ke spesialis sebidang. Antrean diurutkan dari skor risiko tertinggi."

2. Buka SYN-DEN-09. Tunjukkan **layar dua panel**: kiri dokumen asli, kanan temuan dan draf.
3. Pada temuan **Pemeriksaan melebihi kebutuhan (OVER_SERVICE)**, klik salah satu kutipan bukti. Panel kiri membuka halaman hasil lab dan **menyorot baris** yang dikutip.

> "Setiap temuan wajib punya bukti. Kalau AI menyebut sesuatu tapi kutipannya tidak ditemukan di dokumen, temuan itu dibuang dan klaim tidak boleh hijau."

4. Tunjukkan temuan **Rawat inap tanpa indikasi tercatat (ADMISSION_NOT_INDICATED)** dan rujukan pedomannya (PNPK Dengue 2021).
5. Klik **Mulai telaah**. Banner biru menunjukkan waktu telaah mulai dihitung dan kasus terkunci untuk dokter ini.
6. Buka tab **Data ekstraksi**. Tunjukkan nilai yang diekstraksi beserta kutipannya. (Opsional) klik **Koreksi** pada satu field, ubah nilainya, isi catatan, simpan: nilai lama tercoret dan muncul di **Riwayat koreksi**.
7. Di kotak bawah, tunjukkan **Usulan dari draf AI** (tunda / klarifikasi) dan pilihannya:
   - **Setujui draf & tanda tangan**
   - **Ubah rekomendasi** (pilih bayar penuh / sebagian / tunda / tidak dijamin; kode alasan wajib bila berbeda dari draf)
   - **Eskalasi ke spesialis** (catatan wajib)
8. Untuk demo, klik **Ubah rekomendasi** → pilih **Bayar sebagian**, isi nilai dibayar mis. `3500000`, kode alasan `OVER_SERVICE`, klik **Tanda tangan**. Masukkan PIN salah sekali (`000000`) untuk menunjukkan penolakan, lalu PIN `123456`.

> "Dokter yang memutuskan. Sistem mencatat apakah dokter setuju dengan draf AI, berapa lama telaahnya, dan alasan bila berbeda. Draf AI tetap tersimpan sebagai versi lama, jadi jejaknya bisa diaudit."

9. Banner hijau: rekomendasi sudah ditandatangani dan terlihat di portal asuransi. Buka tab **Riwayat telaah** untuk menunjukkan catatan "Mengubah draf", alasan, dan durasi.

## 5:30–7:30 · Asuransi memutuskan (Jendela A)

1. Muat ulang halaman detail SYN-DEN-09. Rekomendasi **Bayar sebagian** kini tampil: nilai tagihan, nilai rekomendasi, koreksi, nama dokter dan waktu tanda tangan, temuan dengan bukti, draf penjelasan untuk nasabah/RS, serta versi model/prompt/aturan.
2. Klik kutipan bukti: pratinjau dokumen terbuka dengan sorotan, sama seperti yang dilihat dokter.
3. Klik **Unduh PDF** untuk menunjukkan rekomendasi versi PDF.
4. Di **Catat keputusan perusahaan**, klik **Berbeda** lalu **Simpan** tanpa alasan → muncul pesan alasan wajib. Lalu pilih **Setuju dengan rekomendasi** dan simpan.

> "Keputusan akhir tetap di tangan asuransi. Kalau berbeda dari rekomendasi, alasannya wajib dicatat."

5. Kembali ke **Daftar klaim**: pilih klaim hijau yang belum diputuskan → **Setujui N klaim hijau** (setujui massal). Klik **Ekspor CSV** untuk menunjukkan file kolom tetap yang bisa diimpor ke sistem klaim.

## 7:30–9:00 · Dashboard (Jendela A, atau login `manajer@demo.test`)

Buka **Dashboard**:

- Jumlah klaim per triase dan per status, berapa yang masih menunggu dokter.
- **Nilai koreksi** dibanding total tagihan.
- **Temuan terbanyak** dan **rumah sakit dengan temuan terbanyak**.
- Waktu proses rata-rata (unggah sampai rekomendasi awal).
- **Persetujuan dokter atas draf AI** dan rata-rata waktu telaah. Ini metrik utama untuk menilai apakah AI benar-benar membantu dokter.

> "Untuk asuransi, hanya rekomendasi yang sudah dirilis yang dihitung. Tim MAB melihat semuanya dari akun admin."

## 9:00–10:00 · Penutup dan pertanyaan

Poin penutup:

- Aturan klinis adalah file konfigurasi berversi (tunjukkan halaman **Aturan & pengguna** dari akun `admin@mab.test` bila sempat), sehingga dokter MAB bisa mengubah ambang tanpa mengubah kode.
- Semua aksi tercatat di log audit yang tidak bisa diubah.
- Laporan evaluasi pada 30 klaim sintetis ada di `evaluation/reports/`. Sampaikan dengan jujur: angkanya dari data sintetis dan LLM mock, jadi menguji alur dan aturan, bukan kualitas model AI.
- Tahap berikutnya: validasi aturan oleh dokter, uji dengan LLM sungguhan, dan data pilot yang disamarkan.

---

## Variasi bila ada waktu

- **Kasus merah + spesialis:** login `dokter.spesialis@mab.test`. SYN-DEN-08 ada di antrean dengan label **eskalasi** dari dokter umum; tunjukkan catatan eskalasinya di **Riwayat telaah**.
- **Klaim tumpang tindih:** buka SYN-GEA-10 (sebagai spesialis); temuan DUP_CLAIM menunjuk ke klaim lama KLM-RIWAYAT-0001.
- **Dokumen tidak lengkap:** SYN-TIF-10 (antrean dokter umum) berstatus kuning dengan rekomendasi tunda dan tindak lanjut "minta dokumen" karena rincian tagihan tidak dilampirkan.
- **Kehati-hatian kualitas data:** SYN-DEN-06 sebenarnya wajar, tetapi dinaikkan ke kuning karena ada catatan kualitas data pada dokumen pindaian. Kalau ragu, klaim tidak boleh hijau.
- **Rekomendasi bertanda tangan:** buka SYN-DEN-07 sebagai staf; dokter spesialis mengubah draf menjadi bayar sebagian.

## Bila ada yang tidak berjalan

| Masalah saat demo | Tindakan cepat |
|---|---|
| SYN-DEN-09 sudah ada di daftar | Seed lama. Pakai SYN-DEN-08 (antrean spesialis) untuk alur dokter, atau reset sebelum sesi berikutnya. |
| Klaim lama di "Diproses" | Worker sedang OCR; tunggu beberapa detik. Cek `docker compose logs -f worker`. |
| Klaim "Gagal diproses" | Pastikan nomor klaim persis `SYN-DEN-09` (mode mock mencari jawaban berdasarkan nomor klaim). |
| Antrean dokter kosong | Pastikan login sebagai dokter yang tepat: kuning → dokter umum, merah → spesialis. |
