# Evaluasi deteksi fraud - fraud-2026.11-demo

> DATA REKAAN UNTUK DEMONSTRASI. Riwayat klaim dibuat `synthetic/generate_fraud.py` dengan pola fraud yang ditanam.

Seed utama 2026: 805 klaim, 8 sinyal, **8 dari 8 pola tertangkap**, **0 alarm palsu**.

| Pola | Aturan diharapkan | Entitas | Tertangkap | Bukti (pesan sinyal) |
|---|---|---|---|---|
| FP-01 Lama rawat RS jauh di atas sejawat | FRD-01 | RS Cempaka Rekaan | ya | Rata-rata lama rawat di RS Cempaka Rekaan 7,3 hari, sedangkan RS lain 4,4 hari (indeks 1,69, z = 18,8, 87 klaim). |
| FP-02 Biaya per hari dokter jauh di atas sejawat | FRD-03 | dr. Prita Pratama, Sp.PD | ya | Rata-rata biaya per hari pasien dr. Prita Pratama, Sp.PD (RS Anggrek Fiktif) Rp2.215.609, sedangkan dokter lain Rp1.432.429 (indeks 1,6, z = 14,7, 28 klaim). |
| FP-03 Frekuensi pemeriksaan lab dokter berlebihan | FRD-04 | dr. Miftah Halim, Sp.PD | ya | Pasien dr. Miftah Halim, Sp.PD (RSU Melati Contoh) rata-rata diperiksa lab 3 kali per hari rawat, sedangkan pasien dokter lain 1,3 kali (indeks 2,55, z = 44,4). |
| FP-04 Rekening bersama banyak peserta | FRD-05 | REK-77810042 | ya | Rekening REK-77810042 menerima pembayaran untuk 6 peserta dengan 6 nama keluarga dan 6 alamat berbeda (9 klaim). |
| FP-05 Alamat bersama peserta tak bersaudara | FRD-06 | Jl. Rekaan Raya No. 17, Kota Fiktif Timur | ya | 5 peserta dengan 5 nama keluarga berbeda tinggal di Jl. Rekaan Raya No. 17, Kota Fiktif Timur; 6 klaim, sebagian besar di RS Kenari Demo. |
| FP-06 Rujukan berputar antar-RS | FRD-07 | RS Bakti Rekaan -> RS Teratai Rekaan -> RS Bakti Rekaan | ya | Pasien dirujuk berputar RS Bakti Rekaan -> RS Teratai Rekaan -> RS Bakti Rekaan: 14 klaim rujukan, paling sedikit 7 per arah. |
| FP-07 Klaim beruntun satu peserta | FRD-08 | PST-H-9001 | ya | Peserta PST-H-9001 punya 7 klaim rawat inap dalam 180 hari di 3 RS; jarak terpendek antar-rawat 14 hari. |
| FP-08 Rawat inap tumpang tindih di dua RS | FRD-09 | PST-H-9002 | ya | Peserta PST-H-9002 punya 1 pasangan klaim rawat inap dengan tanggal yang beririsan di 2 RS. |

## Alarm palsu (seed utama)

Tidak ada. Populasi normal (keluarga satu alamat/rekening, rujukan satu arah, peserta dengan 2-3 klaim) tidak memicu sinyal.

## Kestabilan ambang (beberapa seed)

| Seed | Klaim | Sinyal | Pola tertangkap | Alarm palsu |
|---|---|---|---|---|
| 2026 | 805 | 8 | 8/8 | 0 |
| 1 | 846 | 8 | 8/8 | 0 |
| 2 | 843 | 8 | 8/8 | 0 |
| 3 | 831 | 8 | 8/8 | 0 |
| 4 | 839 | 8 | 8/8 | 0 |
| 5 | 865 | 8 | 8/8 | 0 |
| 6 | 864 | 8 | 8/8 | 0 |
| 7 | 850 | 8 | 8/8 | 0 |
| 8 | 817 | 8 | 8/8 | 0 |
| 9 | 824 | 8 | 8/8 | 0 |

Total: 80/80 pola tertangkap, 0 alarm palsu dari 80 sinyal.

Catatan: pola ditanam dengan efek yang cukup besar (mis. lama rawat +70%). Pada data sungguhan efek biasanya lebih halus dan populasi lebih beragam, jadi ambang perlu dikalibrasi ulang dan setiap sinyal tetap ditelaah manusia. Sinyal fraud tidak pernah menolak klaim.
