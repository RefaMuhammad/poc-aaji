# Checklist sebelum data sungguhan (UU PDP dan POJK)

`REAL_DATA_ENABLED` hanya boleh diubah menjadi `true` setelah **semua** item di bawah berstatus selesai dan
ditandatangani penanggung jawab. Kolom "Cek kode" menandai item yang juga dipaksa oleh aplikasi (aplikasi menolak start
bila tidak terpenuhi).

Catatan: daftar ini adalah bahan kerja teknis untuk tim hukum dan kepatuhan klien, bukan nasihat hukum. Rujukan pasal
perlu dikonfirmasi terhadap peraturan pelaksana terbaru.

Status: ✓ selesai · ◐ sebagian (bagian teknis siap) · ○ belum

## A. Dasar hukum dan tata kelola

| No | Item | Penanggung jawab | Status |
|---|---|---|---|
| A1 | Peran ditetapkan: asuransi = pengendali data, MAB = pemroses data; perjanjian pemrosesan data (DPA) ditandatangani dengan setiap asuransi pilot | Hukum klien + MAB | ○ |
| A2 | Dasar pemrosesan data kesehatan peserta untuk telaah klaim dan underwriting ditetapkan (perjanjian polis / persetujuan eksplisit) | Hukum asuransi | ○ |
| A3 | Penilaian dampak pelindungan data (DPIA) untuk pemrosesan data kesehatan skala besar dan pengambilan keputusan berbantuan AI | Kepatuhan + MAB | ○ |
| A4 | Pejabat pelindungan data pribadi (DPO) ditunjuk | Klien / MAB | ○ |
| A5 | Rekam aktivitas pemrosesan (tujuan, jenis data, penerima, retensi) tercatat | Kepatuhan | ○ |
| A6 | Informasi ke peserta bahwa rekomendasi disusun dengan bantuan sistem dan selalu diputus dokter/manusia; jalur keberatan tersedia | Asuransi | ◐ (alur banding U5 dan tanda tangan dokter sudah ada) |

## B. Lokasi data

| No | Item | Cek kode | Status |
|---|---|---|---|
| B1 | Klaster, database, Redis, penyimpanan dokumen, backup, dan log di region Indonesia | | ◐ (chart siap; penyedia belum dipilih) |
| B2 | Keputusan residensi data LLM disetujui (lihat [u8-residensi-llm.md](u8-residensi-llm.md)) | `LLM_DATA_RESIDENCY_APPROVED` | ○ |
| B3 | Bila ada data/DRC di luar Indonesia: persetujuan OJK sesuai POJK 4/POJK.05/2021 dan dasar transfer Pasal 56 UU PDP | | ○ (rencana: tidak ada) |
| B4 | Sub-pemroses (penyedia cloud, LLM, email) didaftar dan disetujui asuransi | | ○ |

## C. Keamanan teknis

| No | Item | Cek kode | Status |
|---|---|---|---|
| C1 | TLS di semua jalur publik (ingress, HSTS) | HSTS otomatis di luar dev | ◐ (chart siap; uji SSL Labs di staging) |
| C2 | TLS ke database | `sslmode=require` wajib | ◐ |
| C3 | Enkripsi at rest dokumen dengan KMS | `S3_SSE` wajib | ◐ (MinIO SSE-S3 terbukti; KMS cloud saat staging) |
| C4 | Enkripsi at rest database dan backup (layanan terkelola + bucket backup terenkripsi) | | ○ |
| C5 | Rahasia di Secret Manager, tidak di repo atau file values; rotasi terjadwal | rahasia bawaan ditolak | ◐ |
| C6 | Kontrol akses per peran dan per tenant; log audit tidak bisa diubah | | ✓ (M3, U1, U6) |
| C7 | Batas percobaan login dan PIN tanda tangan | | ✓ (U8) |
| C8 | Mode demo dan data rekaan dimatikan di produksi | `DEMO_MODE=false` wajib | ◐ |
| C9 | Akses admin klaster dan database dibatasi (SSO, MFA, jaringan privat) | | ○ |
| C10 | Token sesi dipindah ke cookie `HttpOnly` + `SameSite` | | ○ (disarankan sebelum produksi) |

## D. Operasi

| No | Item | Status |
|---|---|---|
| D1 | Backup harian terenkripsi, retensi 30 hari, uji pemulihan terbukti | ◐ (terbukti di sandbox; ulangi di staging) |
| D2 | PITR database terkelola aktif | ○ |
| D3 | Monitoring dan alert aktif, ada penanggung jawab on-call | ◐ (metrik dan alert siap) |
| D4 | Log terpusat di region Indonesia, retensi sesuai kebijakan, tanpa isi dokumen medis | ◐ |
| D5 | Runbook operasi disetujui tim operasi | ◐ ([runbook-operasi.md](runbook-operasi.md)) |

## E. Pengujian keamanan

| No | Item | Status |
|---|---|---|
| E1 | Uji otomatis internal (ZAP, bandit, audit dependensi, tes keamanan) | ✓ ([laporan](u8-laporan-uji-keamanan.md)) |
| E2 | Uji penetrasi pihak ketiga terhadap staging; temuan tinggi/kritis ditutup | ○ |
| E3 | Pemindaian image container di CI | ○ |

## F. Hak subjek data dan insiden

| No | Item | Status |
|---|---|---|
| F1 | Prosedur permintaan akses, koreksi, dan penghapusan data peserta (lewat asuransi sebagai pengendali) | ○ |
| F2 | Kebijakan retensi dan penghapusan dokumen klaim/underwriting (termasuk di backup) | ○ |
| F3 | Prosedur pelanggaran data: deteksi, isolasi, notifikasi tertulis ke subjek data dan lembaga paling lambat 3×24 jam, koordinasi dengan asuransi | ○ |
| F4 | Latihan insiden (tabletop) sekali sebelum go-live | ○ |

## Persetujuan

| Peran | Nama | Tanggal | Tanda tangan |
|---|---|---|---|
| Pemilik produk MAB | | | |
| Kepatuhan / DPO | | | |
| Hukum asuransi pilot | | | |
| Penanggung jawab keamanan | | | |
