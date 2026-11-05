# Skenario demo: dari file yang diunggah sampai output

> **Data rekaan untuk demonstrasi.** Semua pasien, dokter, rumah sakit, dan klaim di sini fiktif.

Dokumen ini menjelaskan apa yang terjadi di dalam web setelah sebuah file diunggah, dan apa output yang terlihat di setiap tahap. Naskah presentasi 10 menit ada di [demo-script.md](demo-script.md); arsitektur teknis di [ARSITEKTUR.md](ARSITEKTUR.md).

## 0. Menjalankan demo dalam satu jendela browser

Frontend dibangun dengan **React** (lewat Next.js, App Router + TypeScript + Tailwind) di `apps/web`. Buka http://localhost:3000 dan login dengan akun demo mana saja (password `demo12345`).

Di kanan atas portal ada pemilih kuning **Ganti peran (demo)**. Pilih peran dan halaman langsung berpindah tanpa logout:

| Pilihan | Akun | Untuk langkah |
|---|---|---|
| 1. Staf klaim | `staf@demo.test` | Unggah klaim, lihat rekomendasi, catat keputusan, ekspor CSV |
| 2. Dokter umum | `dokter.umum@mab.test` | Telaah kasus kuning, tanda tangan (PIN `123456`) |
| 3. Dokter spesialis | `dokter.spesialis@mab.test` | Telaah kasus merah dan eskalasi |
| 4. Manajer klaim | `manajer@demo.test` | Dashboard |
| 5. Admin MAB | `admin@mab.test` | Aturan klinis, pengguna, semua data |

Bila sedang membuka sebuah klaim, ganti peran tetap membuka klaim yang sama di tampilan peran baru (misalnya dari detail klaim staf ke ruang kerja dokter).

Kenapa bukan satu akun yang bisa semuanya? Prinsip produk mengharuskan rekomendasi selain "bayar penuh" ditandatangani **dokter**, dan asuransi **tidak boleh** melihat temuan sebelum dokter menandatangani. Dengan ganti peran, semua langkah tetap bisa dibuka dari satu jendela, tetapi setiap aksi tetap dicatat atas nama peran yang benar di log audit (aksi `DEMO_SWITCH` juga dicatat). Fitur ini hanya aktif untuk akun demo dan bisa dimatikan dengan `DEMO_MODE=false` di `.env`.

## 1. File apa yang diunggah

Ada dua cara unggah, keduanya di menu **Unggah klaim** (peran staf klaim).

**a. Satu klaim.** Isi formulir (nomor klaim, nomor polis, ID peserta, nama peserta, rumah sakit, nilai tagihan, tanggal masuk dan keluar), lalu lampirkan PDF atau gambar dokumennya. Untuk data demo, file ada di `data/synthetic_output/<nomor klaim>/` dan isian formulirnya di `case.json` folder yang sama.

**b. Unggah massal.** Satu file ZIP berisi `manifest.xlsx` dan satu folder per klaim. Kolom manifest: `folder`, `nomor_klaim`, `nomor_polis`, `id_peserta`, `nama_peserta`, `nama_rs`, `tanggal_masuk`, `tanggal_keluar`, `nilai_tagihan`.

> Dengan LLM mock (bawaan), nomor klaim wajib sama persis dengan nama folder data sintetis, misalnya `SYN-DEN-09`, karena jawaban AI tiruan dicari berdasarkan nomor itu.

Setiap klaim rawat inap berisi sampai empat dokumen:

| File | Isinya | Data yang diambil sistem |
|---|---|---|
| `resume_medis.pdf` | Ringkasan perawatan dari DPJP | Diagnosis utama dan sekunder (ICD-10), usia, tanggal masuk/keluar, narasi klinis: warning signs, perembesan plasma, derajat dehidrasi, syok, perdarahan, komorbid, kondisi saat pulang |
| `hasil_laboratorium.pdf` | Hasil lab per tanggal dan jam | Trombosit, hematokrit, NS1 dan IgM dengue, titer Widal, kultur darah, Tubex/Typhidot, pemeriksaan feses, jumlah darah lengkap per hari |
| `cppt.pdf` | Catatan perkembangan pasien terintegrasi | Perjalanan klinis harian, kapan kriteria pulang terpenuhi, catatan tindakan yang mendukung tagihan |
| `rincian_tagihan.pdf` | Item tagihan RS | Obat (seftriakson, kuinolon, antibiotik lain), infus, pemeriksaan, item ganda, total tagihan |

Dokumen bisa berupa **PDF digital** (teksnya langsung dibaca) atau **hasil pindai** (dibaca dengan OCR). Dari 30 klaim sintetis, 12 dibuat dalam versi pindaian.

## 2. Apa yang terjadi di web setelah unggah

Status klaim terlihat di daftar klaim dan di halaman detail, dengan progres *Diterima & antre → Membaca dokumen & menilai → Rekomendasi siap*.

| Tahap | Status di web | Yang dikerjakan sistem |
|---|---|---|
| 1. Diterima | **Diterima** → **Antre diproses** | File disimpan di penyimpanan dokumen, klaim masuk antrean worker. Unggah tercatat di log audit. |
| 2. Membaca dokumen | **Diproses** | Halaman PDF digital dibaca teksnya; halaman pindaian di-OCR. Setiap baris teks disimpan bersama halaman dan koordinatnya. |
| 3. Mengenali jenis dokumen | **Diproses** | Setiap file dikenali sebagai resume medis, hasil lab, CPPT, atau rincian tagihan (dari nama file dan isinya). Dokumen wajib yang tidak ada dicatat. |
| 4. Ekstraksi data | **Diproses** | Data di tabel bagian 1 diambil. Setiap nilai menyimpan kutipan baris sumbernya. Nilai turunan dihitung: lama rawat, kenaikan hematokrit (%), darah lengkap per hari, lama seftriakson, item tagihan ganda, klaim tumpang tindih. |
| 5. Penalaran klinis AI | **Diproses** | AI membaca narasi resume medis dan CPPT untuk data yang tidak berupa angka (mis. warning signs). Kutipan AI dicocokkan dengan dokumen; nilai yang kutipannya tidak ditemukan dianggap "tidak diketahui" dan diberi catatan kualitas. |
| 6. Aturan klinis | **Diproses** | Aturan YAML (`rules/aturan_klinis_demo.yaml`, 19 aturan untuk DBD, tifoid, gastroenteritis, dan aturan umum) dievaluasi. Kondisi yang terpenuhi menjadi temuan: kode alasan, keparahan, pesan, rujukan pedoman, dan kutipan bukti. |
| 7. Triase dan draf | **Menunggu dokter** atau **Menunggu keputusan asuransi** | Skor risiko = jumlah bobot temuan. Hijau: draf "bayar penuh", langsung ke asuransi. Kuning/merah: draf untuk dokter; asuransi belum melihat temuan. |
| 8. Telaah dokter | **Menunggu dokter** → **Menunggu keputusan asuransi** | Kuning ke dokter umum, merah ke spesialis. Dokter setuju dengan draf, mengubah, atau mengeskalasi, lalu tanda tangan dengan PIN. Draf AI tetap tersimpan sebagai versi lama. |
| 9. Keputusan asuransi | **Selesai** | Staf mencatat "setuju" atau "berbeda" (alasan wajib bila berbeda). Klaim hijau bisa disetujui massal. |

Bila semua dokumen gagal dibuka, status menjadi **Gagal diproses**. Satu file rusak tidak menghentikan klaim; file itu dicatat sebagai peringatan.

## 3. Output yang dihasilkan

| Output | Di mana | Isinya |
|---|---|---|
| Status triase | Daftar klaim, detail klaim, antrean dokter | Hijau / kuning / merah dan skor risiko 0–100 |
| Temuan berbukti | Detail klaim, ruang kerja dokter | Kode alasan, keparahan, pesan dalam bahasa Indonesia, rujukan pedoman, kutipan. Klik kutipan untuk membuka halaman dokumen asli dengan baris yang disorot. |
| Data ekstraksi | Ruang kerja dokter, tab **Data ekstraksi** | Semua nilai yang dibaca beserta kutipannya. Dokter bisa mengoreksi nilai; nilai lama tercoret dan masuk **Riwayat koreksi**. |
| Rekomendasi | Detail klaim (setelah dirilis) | Bayar penuh / bayar sebagian / tunda / tidak dijamin, nilai tagihan, nilai rekomendasi, nilai koreksi, nama dokter dan waktu tanda tangan, draf penjelasan untuk nasabah/RS |
| Jejak versi | Detail klaim dan PDF | Versi aturan, versi model AI, versi prompt |
| PDF rekomendasi | Tombol **Unduh PDF** di detail klaim | Rekomendasi bertanda tangan dalam satu file untuk arsip atau dikirim |
| CSV | Tombol **Ekspor CSV** di daftar klaim | Kolom tetap untuk diimpor ke sistem klaim: nomor klaim, polis, peserta, RS, tanggal, tagihan, status, triase, skor, rekomendasi, nilai, kode alasan, dokter, waktu tanda tangan, versi aturan dan model, keputusan asuransi |
| Riwayat telaah | Tab **Riwayat telaah** | Setuju/mengubah draf, alasan, durasi telaah, catatan eskalasi |
| Dashboard | Menu **Dashboard** | Jumlah klaim per status dan triase, yang menunggu dokter, nilai koreksi vs total tagihan, temuan dan RS dengan temuan terbanyak, waktu proses rata-rata, persetujuan dokter atas draf AI, rata-rata waktu telaah |
| Log audit | Database (tabel `audit_logs`) | Login, unggah, lihat, telaah, tanda tangan, PIN salah, koreksi, keputusan, ganti peran demo |

## 4. Hasil per klaim sintetis

Hasil awal setelah klaim selesai diproses (sebelum telaah dokter), dengan LLM mock. Kolom "Aturan" memakai ID di file aturan; lihat `rules/aturan_klinis_demo.yaml` untuk detailnya.

### Demam berdarah / dengue (A90, A91)

| Klaim | Bentuk | Skenario | Triase | Draf | Aturan yang terpicu | Yang terlihat di web |
|---|---|---|---|---|---|---|
| SYN-DEN-01 | pindaian | DBD dengan warning signs dan perembesan plasma, pulang sesuai kriteria | Hijau | Bayar penuh | — | Langsung ke asuransi tanpa temuan |
| SYN-DEN-02 | digital | DBD terkonfirmasi IgM (NS1 negatif karena datang hari ke-5) | Hijau | Bayar penuh | — | Tanpa temuan |
| SYN-DEN-03 | digital | Demam dengue dengan muntah persisten | Hijau | Bayar penuh | — | Tanpa temuan |
| SYN-DEN-04 | digital | DBD pada pasien diabetes, perembesan plasma | Hijau | Bayar penuh | — | Tanpa temuan |
| SYN-DEN-05 | digital | Severe dengue: syok dan perdarahan spontan | Hijau | Bayar penuh | — | Tanpa temuan |
| SYN-DEN-06 | pindaian | Demam dengue anak dengan muntah persisten (wajar) | Kuning | Telaah dokter | — | Catatan kualitas data: nilai AI tidak terverifikasi. Kalau ragu, klaim tidak boleh hijau. |
| SYN-DEN-07 | pindaian | Ditagih DBD padahal trombosit tidak turun dan tanpa perembesan plasma | Merah | Telaah dokter | DEN-01, DEN-03 | Diagnosis tidak didukung data + rawat inap tanpa indikasi; ke spesialis |
| SYN-DEN-08 | digital | Ditagih dengue padahal NS1 dan IgM negatif, trombosit normal | Kuning | Telaah dokter | DEN-02 | Diagnosis tanpa konfirmasi lab |
| **SYN-DEN-09** | digital | Demam dengue tanpa warning signs dirawat inap, darah lengkap 4x sehari | Kuning | Telaah dokter | DEN-03, DEN-05 | **Klaim untuk diunggah langsung saat demo.** Rawat inap tanpa indikasi + pemeriksaan berlebih |
| SYN-DEN-10 | pindaian | DBD wajar, tetapi dirawat 3 hari setelah layak pulang dan ada tagihan ganda | Merah | Telaah dokter | GEN-02, DEN-04 | Item tagihan ganda + lama rawat berlebih |

### Demam tifoid (A01.0)

| Klaim | Bentuk | Skenario | Triase | Draf | Aturan yang terpicu | Yang terlihat di web |
|---|---|---|---|---|---|---|
| SYN-TIF-01 | pindaian | Tifoid terkonfirmasi kultur darah, seftriakson 5 hari | Hijau | Bayar penuh | — | Tanpa temuan |
| SYN-TIF-02 | digital | Tifoid anak terkonfirmasi Tubex, tanpa kuinolon | Hijau | Bayar penuh | — | Tanpa temuan |
| SYN-TIF-03 | pindaian | Tifoid dengan kenaikan titer Widal 4x | Hijau | Bayar penuh | — | Tanpa temuan |
| SYN-TIF-04 | digital | Tifoid dengan perdarahan saluran cerna terdokumentasi, seftriakson 10 hari | Hijau | Bayar penuh | — | Seftriakson panjang tidak ditandai karena komplikasinya terdokumentasi |
| SYN-TIF-05 | digital | Tifoid dari Widal tunggal 1/320 | Hijau | Bayar penuh | TIF-02 (Info) | Temuan informasi "status probable", bukan dasar koreksi |
| SYN-TIF-06 | digital | Tifoid hanya dari Widal 1/160, seftriakson 7 hari | Merah | Telaah dokter | TIF-01, TIF-03 | Diagnosis tidak didukung + antibiotik terlalu lama |
| SYN-TIF-07 | digital | Remaja 15 tahun diberi siprofloksasin | Kuning | Telaah dokter | TIF-04 | Kuinolon di bawah 18 tahun |
| SYN-TIF-08 | digital | Hepatitis tifosa ditagihkan tanpa bukti | Merah | Telaah dokter | TIF-05 | Komplikasi tidak didukung bukti |
| SYN-TIF-09 | pindaian | Tifoid terkonfirmasi, dirawat 3 hari setelah layak pulang | Kuning | Telaah dokter | TIF-06 | Lama rawat berlebih |
| SYN-TIF-10 | pindaian | Rincian tagihan tidak dilampirkan (3 dokumen) | Kuning | Tunda | GEN-03 | Dokumen wajib tidak lengkap, tindak lanjut "minta dokumen" |

### Gastroenteritis akut (A09, A08.4, A04.9, K52.9)

| Klaim | Bentuk | Skenario | Triase | Draf | Aturan yang terpicu | Yang terlihat di web |
|---|---|---|---|---|---|---|
| SYN-GEA-01 | pindaian | GEA dehidrasi berat dengan muntah persisten | Hijau | Bayar penuh | — | Tanpa temuan |
| SYN-GEA-02 | digital | GEA lansia dengan penyakit ginjal kronik | Hijau | Bayar penuh | — | Tanpa temuan |
| SYN-GEA-03 | pindaian | Disentri bakteri, antibiotik sesuai indikasi | Hijau | Bayar penuh | — | Tanpa temuan |
| SYN-GEA-04 | digital | Diare viral balita dengan dehidrasi berat | Hijau | Bayar penuh | — | Tanpa temuan |
| SYN-GEA-05 | digital | Gastroenteritis dengan syok hipovolemik | Hijau | Bayar penuh | — | Tanpa temuan |
| SYN-GEA-06 | pindaian | Dehidrasi ringan-sedang dirawat inap, infus 3 hari, antibiotik tanpa indikasi | Merah | Telaah dokter | GEA-01, GEA-02, GEA-03 | Tiga temuan sekaligus |
| SYN-GEA-07 | digital | Dehidrasi berat, antibiotik tanpa indikasi | Kuning | Telaah dokter | GEA-03 | Antibiotik tanpa indikasi |
| SYN-GEA-08 | digital | Dirawat 2 hari setelah layak pulang, 2 tindakan tanpa catatan klinis | Merah | Telaah dokter | GEN-04, GEA-04 | Item tagihan tanpa catatan + lama rawat berlebih |
| SYN-GEA-09 | pindaian | Hasil laboratorium tidak dilampirkan (3 dokumen) | Kuning | Tunda | GEN-03 | Dokumen wajib tidak lengkap |
| SYN-GEA-10 | digital | Tanggal rawat tumpang tindih dengan klaim lama KLM-RIWAYAT-0001 | Merah | Telaah dokter | GEN-01 | Klaim tumpang tindih; temuan menunjuk ke klaim lama |

Setelah `seed_demo.py`, sebagian klaim di atas sudah ditelaah dokter dan diputuskan asuransi, supaya antrean, rekomendasi bertanda tangan, dan dashboard langsung berisi. SYN-DEN-09 sengaja tidak diunggah oleh seed.

## 5. Skenario 1 · Alur lengkap: unggah SYN-DEN-09

1. **Staf klaim** → **Unggah klaim** → **Satu klaim**. Isi formulir:

   | Kolom | Nilai |
   |---|---|
   | Nomor klaim | `SYN-DEN-09` |
   | Nomor polis | `POL-DEMO-8181` |
   | ID peserta | `PST-15720019` |
   | Nama peserta | `Fajar Rahayu` |
   | Rumah sakit | `RS Mitra Medika Nusantara` |
   | Nilai tagihan | `4127000` |
   | Tanggal masuk / keluar | `2026-03-26` / `2026-03-30` |

   Lampirkan 4 PDF dari `data/synthetic_output/SYN-DEN-09/`, klik **Kirim klaim**. (Bila nilainya beda di mesin Anda, ikuti `case.json`.)
2. Halaman detail menampilkan progres. Beberapa detik kemudian status **Menunggu dokter**, triase belum tampil untuk staf (kotak ungu: menunggu tanda tangan dokter).
3. **Ganti peran → 2. Dokter umum.** Halaman berpindah ke ruang kerja dokter untuk klaim yang sama: dokumen asli di kiri, temuan di kanan.
   - Temuan **Rawat inap tanpa indikasi tercatat** (DEN-03, Sedang, rujukan PNPK Dengue 2021 Tabel 8).
   - Temuan **Pemeriksaan melebihi kebutuhan** (DEN-05, Rendah): darah lengkap 4 kali sehari. Klik kutipannya: halaman hasil lab terbuka dan barisnya disorot.
   - Skor 30 → **Kuning**. Draf AI: telaah dokter, usulan tunda/klarifikasi.
4. Klik **Mulai telaah** → **Ubah rekomendasi** → **Bayar sebagian**, nilai `3500000`, kode alasan `OVER_SERVICE` → **Tanda tangan**, PIN `123456`. Output: banner hijau "Rekomendasi sudah ditandatangani", tab **Riwayat telaah** mencatat "Mengubah draf", alasan, dan durasi.
5. **Ganti peran → 1. Staf klaim.** Detail klaim kini menampilkan rekomendasi **Bayar sebagian**: tagihan Rp4.127.000, rekomendasi Rp3.500.000, koreksi Rp627.000, nama dokter, waktu tanda tangan, temuan berbukti, draf penjelasan, versi aturan/model/prompt. Klik **Unduh PDF** untuk file rekomendasi.
6. Di **Catat keputusan perusahaan**, pilih **Setuju dengan rekomendasi** → **Simpan**. Status **Selesai**. Di daftar klaim, **Ekspor CSV** memuat baris SYN-DEN-09 dengan keputusan ini.
7. **Ganti peran → 4. Manajer klaim** → **Dashboard**. Nilai koreksi bertambah Rp627.000, OVER_SERVICE dan ADMISSION_NOT_INDICATED masuk temuan terbanyak, dan persetujuan dokter atas draf AI turun karena dokter mengubah draf.

## 6. Skenario tambahan

Delapan skenario berikut memakai data yang sudah diisi `seed_demo.py`, jadi bisa dijalankan kapan saja setelah seed tanpa mengunggah apa pun (kecuali Skenario 2). Semuanya bisa dijalankan dari satu jendela dengan **Ganti peran (demo)**. Isi antrean bisa sedikit berbeda di mesin lain karena hasil OCR; bila klaim tidak ada di antrean yang disebut, cari di **Daftar klaim** sebagai admin.

| No | Skenario | Klaim | Penyakit | Triase | Peran utama | Yang ingin ditunjukkan |
|---|---|---|---|---|---|---|
| 2 | Unggah massal ZIP | SYN-DEN-09 + SYN-DEN-01 | Dengue | Kuning | Staf klaim | Unggah banyak klaim sekaligus, validasi per baris |
| 3 | Klaim wajar dibayar penuh | SYN-DEN-01, 02, 03 | Dengue | Hijau | Staf klaim | Klaim hijau tidak perlu dokter; setujui massal; CSV |
| 4 | Data pindaian meragukan | SYN-DEN-06 | Dengue | Kuning | Dokter umum | Kalau ragu, klaim tidak boleh hijau; koreksi data |
| 5 | Dokumen tidak lengkap | SYN-TIF-10 | Tifoid | Kuning | Dokter umum | Rekomendasi tunda dengan tindak lanjut minta dokumen |
| 6 | Klaim tumpang tindih | SYN-GEA-10 | Gastroenteritis | Merah | Dokter spesialis | Temuan yang menunjuk klaim lama; tidak dijamin |
| 7 | Eskalasi dokter umum ke spesialis | SYN-DEN-08 | Dengue | Kuning → spesialis | Dokter spesialis | Catatan eskalasi, diagnosis tanpa konfirmasi lab |
| 8 | Komplikasi ditagih tanpa bukti | SYN-TIF-08 | Tifoid | Merah | Dokter spesialis | Koreksi akibat diagnosis sekunder tanpa bukti |
| 9 | Asuransi berbeda dari rekomendasi | SYN-DEN-07 | Dengue | Merah (sudah ditandatangani) | Staf klaim, manajer | Keputusan akhir di asuransi; alasan wajib; dashboard |

### Skenario 2 · Unggah massal ZIP

Alternatif Skenario 1. Pilih salah satu, karena SYN-DEN-09 hanya bisa diunggah sekali.

1. Buat ZIP-nya sekali di laptop:
   ```powershell
   docker compose exec api python infra/scripts/make_demo_zip.py
   ```
   Hasilnya `data\demo_upload\unggah_massal_demo.zip`, berisi `manifest.xlsx`, folder `SYN-DEN-09/` (4 PDF), dan folder `SYN-DEN-01/` (4 PDF).
2. **Staf klaim** → **Unggah klaim** → **Banyak klaim (ZIP)** → pilih file ZIP → **Unggah ZIP**.
3. **Proses di web:** manifest dibaca baris per baris. Setiap baris divalidasi (kolom wajib, format tanggal, nilai tagihan), lalu folder PDF-nya dicocokkan. Klaim yang valid dibuat dan masuk antrean. Baris yang gagal tidak menggagalkan baris lain.
4. **Output:** ringkasan "**1** klaim dibuat dan masuk antrean proses, **1** baris gagal" dengan tabel per baris:
   - SYN-DEN-09: **Berhasil**.
   - SYN-DEN-01: "Nomor klaim SYN-DEN-01 sudah ada", karena sudah diunggah seed. Ini menunjukkan sistem menolak unggahan ganda.
5. Lanjutkan seperti Skenario 1 langkah 2 dan seterusnya: SYN-DEN-09 menjadi **Kuning** dengan temuan DEN-03 dan DEN-05.

### Skenario 3 · Klaim wajar dibayar penuh (hijau)

1. **Staf klaim** → **Daftar klaim**. SYN-DEN-01, SYN-DEN-02, dan SYN-DEN-03 berstatus **Menunggu keputusan asuransi** dengan triase **Hijau** dan rekomendasi **Bayar penuh**.
2. Buka SYN-DEN-01 (DBD dengan warning signs dan perembesan plasma, berkas pindaian). **Output:** tidak ada temuan; rekomendasi bayar penuh Rp5.285.000; versi aturan dan model tercatat. Tidak ada nama dokter karena klaim hijau tidak wajib ditelaah dokter.
3. Kembali ke **Daftar klaim** → **Pilih semua hijau** → **Setujui N klaim hijau**. Status ketiganya menjadi **Selesai** dengan keputusan **Setuju**.
4. Klik **Ekspor CSV**. **Output:** file CSV kolom tetap; baris SYN-DEN-01..03 berisi `status_triase=GREEN`, `rekomendasi=PAY_FULL`, `keputusan_asuransi=AGREE`.

Pesan: sistem mempercepat klaim yang wajar. Pemeriksaan dokter dipusatkan pada klaim yang memang bermasalah.

### Skenario 4 · Data pindaian meragukan (SYN-DEN-06)

1. **Dokter umum** → **Antrean telaah** → SYN-DEN-06 (demam dengue anak dengan muntah persisten, berkas pindaian), triase **Kuning**.
2. **Output:** tidak ada temuan aturan, tetapi ada **catatan kualitas data**: nilai klinis dari AI yang kutipannya tidak ditemukan di dokumen, dan aturan yang tidak bisa dinilai karena datanya kosong.
3. **Proses di web:** nilai yang kutipannya tidak cocok dianggap "tidak diketahui", bukan "tidak ada". Karena itu klaim tidak diloloskan sebagai hijau walaupun klinisnya wajar.
4. Klik **Mulai telaah** → tab **Data ekstraksi**. Bandingkan nilai dengan dokumen pindaian di panel kiri. Bila ada nilai yang salah baca, klik **Koreksi**, isi nilai yang benar dan catatan, lalu simpan. **Output:** nilai lama tercoret dan masuk **Riwayat koreksi**.
5. **Setujui draf & tanda tangan** (PIN `123456`). Draf untuk kasus seperti ini adalah **Tunda: minta dokumen / klarifikasi**, jadi dokter meminta klarifikasi ke RS dan tidak memutuskan dari data yang meragukan.

Pesan: AI tidak boleh menebak. Kalau datanya meragukan, klaim naik ke dokter.

### Skenario 5 · Dokumen tidak lengkap (SYN-TIF-10)

1. **Dokter umum** → **Antrean telaah** → SYN-TIF-10 (tifoid, hanya 3 dokumen).
2. **Output:** temuan **Dokumen wajib tidak ada** (GEN-03, kode `DOC_MISSING`): rincian tagihan belum dilampirkan. Triase **Kuning**, draf **Tunda: minta dokumen / klarifikasi** dengan tindak lanjut meminta dokumen.
3. **Proses di web:** aturan triase menaruh `DOC_MISSING` paling atas, jadi klaim tidak dinilai lebih jauh sebelum berkasnya lengkap. Aturan yang butuh data tagihan dicatat sebagai "tidak bisa dinilai".
4. **Mulai telaah** → **Setujui draf & tanda tangan**.
5. **Ganti peran → 1. Staf klaim** → buka SYN-TIF-10. **Output:** rekomendasi **Tunda** bertanda tangan dokter, dengan **Tindak lanjut** berisi dokumen yang harus diminta ke RS. Staf mencatat **Setuju**.

### Skenario 6 · Klaim tumpang tindih (SYN-GEA-10)

1. **Dokter spesialis** → **Antrean telaah** → SYN-GEA-10, triase **Merah**.
2. **Output:** temuan **Klaim duplikat / tumpang tindih** (GEN-01, keparahan Tinggi): ada klaim lain milik peserta yang sama, **KLM-RIWAYAT-0001**, dengan tanggal rawat beririsan. Klinisnya sendiri wajar.
3. **Proses di web:** sistem membandingkan nomor peserta dan tanggal rawat dengan semua klaim sebelumnya. Satu temuan Tinggi cukup untuk triase merah, sehingga klaim langsung ke spesialis.
4. **Mulai telaah** → **Ubah rekomendasi** → **Tidak dijamin**, kode alasan `DUP_CLAIM`, catatan "Periode rawat sudah ditagihkan pada KLM-RIWAYAT-0001" → **Tanda tangan**.
5. **Ganti peran → 1. Staf klaim** → buka SYN-GEA-10. **Output:** rekomendasi **Tidak dijamin**, nilai rekomendasi Rp0, koreksi Rp2.568.000, alasan dan nama dokter tercatat. Catat keputusan **Setuju**.

Pesan: AI tidak menolak klaim. Penolakan ini keputusan dokter yang tercatat alasannya.

### Skenario 7 · Eskalasi dokter umum ke spesialis (SYN-DEN-08)

1. **Dokter spesialis** → **Antrean telaah**. SYN-DEN-08 punya label **eskalasi**. Kasusnya kuning, tetapi dokter umum meminta pendapat spesialis (dilakukan oleh seed).
2. Buka tab **Riwayat telaah**. **Output:** catatan eskalasi dokter umum ("Mohon pendapat spesialis sebelum tanda tangan…") dan waktunya.
3. **Output temuan:** **Diagnosis dengue tanpa konfirmasi laboratorium** (DEN-02): NS1 dan IgM negatif, trombosit normal. Klik kutipan untuk melihat hasil lab yang disorot.
4. **Mulai telaah** → **Setujui draf & tanda tangan**. Draf: **Tunda**, untuk klarifikasi dasar diagnosis ke DPJP.
5. **Output:** riwayat telaah mencatat dua langkah, yaitu eskalasi oleh dokter umum dan tanda tangan oleh spesialis.

Untuk menunjukkan eskalasi secara langsung, pakai klaim kuning lain di antrean dokter umum: **Mulai telaah** → **Eskalasi ke spesialis** (catatan wajib). Klaim pindah ke antrean spesialis.

### Skenario 8 · Komplikasi ditagih tanpa bukti (SYN-TIF-08)

1. **Dokter spesialis** → **Antrean telaah** → SYN-TIF-08, triase **Merah**.
2. **Output:** temuan **Komplikasi tifoid ditagihkan tanpa bukti** (TIF-05, keparahan Tinggi). Diagnosis sekunder K75.9 (hepatitis tifosa) ditagihkan, tetapi resume medis, CPPT, dan hasil lab tidak memuat tanda klinis atau pemeriksaan enzim hati yang mendukung.
3. **Proses di web:** AI membaca narasi klinis untuk mencari bukti komplikasi. Karena tidak ada kutipan yang mendukung, aturan TIF-05 terpicu. Rujukan pedoman (KMK 364/2006, hlm. 7-8 dan 13-14) tampil di temuan.
4. **Mulai telaah** → **Ubah rekomendasi** → **Bayar sebagian**, contoh nilai `4500000` (tarif tanpa komplikasi), kode alasan `COMPLICATION_UNSUPPORTED` → **Tanda tangan**.
5. **Ganti peran → 1. Staf klaim** → **Output:** tagihan Rp5.050.000, rekomendasi Rp4.500.000, koreksi Rp550.000, temuan berbukti, dan draf penjelasan untuk RS. Klik **Unduh PDF**.

### Skenario 9 · Asuransi berbeda dari rekomendasi (SYN-DEN-07)

1. **Staf klaim** → buka SYN-DEN-07. Status **Menunggu keputusan asuransi**.
2. **Output:** rekomendasi **Bayar sebagian** yang ditandatangani dokter spesialis (seed mengubah draf AI menjadi 80% tagihan). Temuan: ditagih sebagai DBD padahal trombosit tidak turun dan tanpa perembesan plasma (DEN-01), dan rawat inap tanpa indikasi (DEN-03).
3. Di **Catat keputusan perusahaan**, pilih **Berbeda**, lalu **Simpan** tanpa alasan. **Output:** pesan bahwa alasan wajib diisi.
4. Isi alasan, mis. "Sesuai polis, kelas kamar disesuaikan; dibayar sesuai negosiasi dengan RS", lalu **Simpan**. Status **Selesai** dengan keputusan **Berbeda**.
5. **Ganti peran → 4. Manajer klaim** → **Dashboard**. **Output:** jumlah keputusan "berbeda" bertambah. Metrik ini menunjukkan seberapa sering asuransi tidak mengikuti rekomendasi MAB.

Pesan: MAB memberi rekomendasi; keputusan akhir tetap milik asuransi dan tercatat lengkap.

## 7. Catatan

- Angka dan temuan di atas berasal dari data sintetis dan LLM mock, jadi menguji alur dan aturan, bukan kualitas model AI. Dengan `LLM_PROVIDER=deepseek`, hasil penalaran bisa sedikit berbeda.
- Aturan klinis masih draf demo yang belum divalidasi dokter panel.
