# U3 · Fraud analytics

> Data rekaan untuk demonstrasi. Semua RS, dokter, peserta, alamat, rekening, dan pola fraud di dokumen ini fiktif.

U3 menambah lapisan analisis **pola di banyak klaim**, terpisah dari penilaian klinis per klaim:

- **Statistik sejawat** per RS dan per dokter: lama rawat, biaya per hari rawat, dan frekuensi pemeriksaan lab, dibandingkan rata-rata sejawat (indeks dan z-score).
- **Graf relasi** peserta, RS, dokter, rekening, dan alamat (networkx): rekening bersama, alamat bersama, rujukan berputar.
- **Urutan klaim per peserta**: klaim beruntun dan rawat inap dengan tanggal tumpang tindih.
- **Skor fraud** per entitas dan per klaim, terpisah dari skor risiko klinis.
- Halaman **Fraud Monitor** untuk menelaah sinyal beserta buktinya.

Prinsip yang tetap berlaku: **sinyal fraud tidak pernah menolak klaim**, tidak mengubah status, rekomendasi, skor risiko klinis, atau keputusan klaim. Setiap sinyal adalah bahan telaah investigator, dan setiap sinyal membawa bukti (klaim, angka pembanding, atau relasi graf).

## Hasil evaluasi

Generator `synthetic/generate_fraud.py` membuat riwayat ±800 klaim dari 10 RS dan 34 dokter, termasuk keluarga yang wajar (satu alamat dan satu rekening, satu nama keluarga) dan rujukan normal satu arah. Generator menanam delapan pola fraud:

| Pola | Yang ditanam | Aturan |
|---|---|---|
| FP-01 | RS Cempaka Rekaan memperpanjang lama rawat ~70% | FRD-01 |
| FP-02 | Seorang dokter di RS Anggrek Fiktif menagih ~65% lebih tinggi per hari | FRD-03 |
| FP-03 | Seorang dokter di RSU Melati Contoh memesan lab ~3x lipat | FRD-04 |
| FP-04 | Rekening REK-77810042 dipakai 6 peserta tak bersaudara | FRD-05 |
| FP-05 | 5 peserta tak bersaudara di satu alamat, semua dirawat di RS Kenari Demo | FRD-06 |
| FP-06 | Rujukan berputar RS Teratai Rekaan dan RS Bakti Rekaan (7 per arah) | FRD-07 |
| FP-07 | Peserta PST-H-9001 dengan 7 klaim berselang 2–3 minggu | FRD-08 |
| FP-08 | Peserta PST-H-9002 dirawat di dua RS pada tanggal beririsan | FRD-09 |

`python -m evaluation.fraud_eval` menjalankan analisis atas seed utama ditambah 9 seed lain. Hasil: **8/8 pola tertangkap di setiap seed (80/80), 0 alarm palsu**. Laporannya ada di [evaluation/reports/deteksi_fraud-2026.11-demo.md](../evaluation/reports/deteksi_fraud-2026.11-demo.md).

Catatan jujur: pola sengaja ditanam dengan efek besar. Pada data sungguhan efeknya lebih halus dan populasinya lebih beragam, jadi ambang perlu dikalibrasi ulang dengan data historis asuransi, dan angka "0 alarm palsu" tidak boleh dibaca sebagai janji untuk data sungguhan.

## Cara kerja

```
riwayat klaim (CSV/XLSX dari sistem inti) ─┐
klaim yang selesai diproses platform ──────┴─> fraud_claim_records ──> analisis (mab_pipeline.fraud)
                                                                         │  aturan: rules/aturan_fraud_demo.yaml
                                                                         v
                                                       fraud_runs + fraud_signals (bukti JSON)
                                                                         │
                                       Fraud Monitor  <──────────────────┤──> fraud_reviews (telaah, bertahan lintas run)
                                       kartu fraud di detail klaim <─────┘
```

- **Data analitik** (`fraud_claim_records`): satu baris per klaim. Sumber `HISTORY` berasal dari impor riwayat; rekening, alamat, dan rujukan hanya ada di sini karena dokumen RS tidak memuatnya. Sumber `PLATFORM` diisi otomatis oleh `process_claim` setelah dokumen dibaca: DPJP dari resume medis dan jumlah pemeriksaan lab (panel per tanggal dan jam) dari hasil lab. Bila riwayat impor memuat nomor klaim yang sama dengan klaim platform, impor hanya melengkapi rekening, alamat, dan rujukan.
- **Analisis** (`mab_pipeline/fraud/`) murni tanpa database dan deterministik. Analisis dijalankan lewat tombol "Jalankan analisis", otomatis setelah impor riwayat, atau oleh seed. Untuk ribuan klaim, analisis selesai dalam hitungan detik secara sinkron. Lima run terakhir per tenant disimpan.
- **Indeks** = rata-rata (nilai klaim ÷ median diagnosis yang sama di seluruh data). Indeks ini menetralkan perbedaan campuran diagnosis antar-RS. **z-score** dihitung dibanding sejawat sejenis, dengan entitas yang dinilai dikeluarkan dari pembanding, dan simpangan baku diberi lantai 0,03 agar sejawat yang sangat seragam tidak menghasilkan z yang tidak masuk akal. Ukuran biaya yang dipakai adalah biaya **per hari rawat**, supaya RS yang memperpanjang rawat tidak ikut terbaca sebagai upcoding.
- **Skor fraud**: entitas mendapat jumlah bobot sinyalnya (maksimal 100), dengan tingkat TINGGI ≥ 50, SEDANG ≥ 25, dan RENDAH ≥ 1. Klaim mendapat jumlah bobot sinyal yang menyebut klaim itu atau entitasnya (RS, dokter, atau peserta), sehingga klaim baru yang diproses setelah run terakhir tetap terlihat terkait. Sinyal yang ditelaah "Wajar / bukan fraud" tidak menambah skor klaim.
- **Telaah**: status *Sedang diselidiki*, *Pola terkonfirmasi*, atau *Wajar / bukan fraud* (yang terakhir wajib disertai alasan). Hasil telaah disimpan per aturan + entitas, jadi tetap berlaku setelah analisis ulang. Setiap telaah tercatat di log audit (`FRAUD_SIGNAL_REVIEWED`), begitu juga `FRAUD_HISTORY_IMPORTED` dan `FRAUD_ANALYSIS_RUN`.

## Aturan fraud (`rules/aturan_fraud_demo.yaml`, versi `fraud-2026.11-demo`)

Format aturan sama dengan aturan klinis dan benefit (kondisi, kode_alasan, keparahan, pesan, dengan evaluator ekspresi aman yang sama), ditambah `entitas` dan `bobot`. Field di kondisi dan pesan hanya boleh berasal dari kelompok entitasnya: `rs.*`, `dokter.*`, `peserta.*`, `rekening.*`, `alamat.*`, atau `rujukan.*`. Ambang lain ada di bagian `parameter`: minimal klaim untuk dibandingkan, jendela klaim beruntun, minimal rujukan per arah, dan tingkat skor.

| Id | Entitas | Kondisi | Bobot |
|---|---|---|---|
| FRD-01 | RS | `rs.claims >= 8 and rs.los_z >= 3 and rs.los_index >= 1.3` | 40 |
| FRD-02 | RS | `rs.claims >= 8 and rs.cost_z >= 3 and rs.cost_index >= 1.35` | 40 |
| FRD-03 | Dokter | `dokter.claims >= 8 and dokter.cost_z >= 3 and dokter.cost_index >= 1.35` | 40 |
| FRD-04 | Dokter | `dokter.claims >= 8 and dokter.lab_z >= 3 and dokter.lab_index >= 1.8` | 30 |
| FRD-05 | Rekening | `rekening.members >= 3 and rekening.surnames >= 2` | 50 |
| FRD-06 | Alamat | `alamat.members >= 4 and alamat.surnames >= 3` | 30 |
| FRD-07 | Rujukan | `rujukan.min_edge >= 3` (putaran di graf rujukan berarah) | 40 |
| FRD-08 | Peserta | `peserta.claims_in_window >= 4` (jendela 180 hari) | 30 |
| FRD-09 | Peserta | `peserta.overlaps >= 1` | 50 |

Ambang memakai z-score **dan** indeks sekaligus. Ini disengaja: di RS dengan sedikit dokter, satu dokter yang menagih tinggi ikut menaikkan indeks RS-nya (z RS bisa > 3), tetapi indeks RS tetap di bawah 1,35, sehingga yang ditandai hanya dokternya.

## API

| Endpoint | Izin |
|---|---|
| `GET /fraud/overview?insurer_id=` (jumlah data, run terakhir, skor per entitas, `stale` bila ada data baru) | `fraud.view` |
| `GET /fraud/signals?insurer_id=&entity_type=&review_status=` (tanpa bukti lengkap) | `fraud.view` |
| `GET /fraud/signals/{id}` (bukti: pembanding, sebaran sejawat, relasi, graf, klaim; tautan ke klaim platform) | `fraud.view` |
| `PUT /fraud/signals/{id}/review` `{status, notes}` | `fraud.manage` |
| `POST /fraud/runs?insurer_id=` | `fraud.manage` |
| `GET /fraud/claims/{claim_id}` (kartu fraud detail klaim) | `fraud.view` + akses klaim |
| `POST /fraud/records/import` (multipart `file`, `insurer_id`, `run`), `GET /fraud/records/template.csv` | `fraud.manage` / `fraud.view` |
| `GET /fraud/ruleset` | `fraud.view` |

Hak akses: `fraud.view` dimiliki staf dan manajer klaim, operator TPA, auditor, dan admin. `fraud.manage` (impor, analisis, telaah) dimiliki **manajer klaim** sebagai investigator tenant-nya, dan admin MAB. Dokter, faskes, peserta, dan underwriter tidak punya akses. Data dan sinyal tenant lain menjawab 404.

Kolom impor riwayat: `nomor_klaim, id_peserta, nama_peserta, alamat_peserta, rekening_bank, rumah_sakit, dokter, rujukan_dari, icd10, tanggal_masuk, tanggal_keluar, total_tagihan, jumlah_pemeriksaan_lab`. Kolom wajib: nomor klaim, peserta, RS, kedua tanggal, dan tagihan. Baris yang salah dilewati dan dilaporkan; riwayat impor tercatat di "Riwayat integrasi" dengan kanal `FRAUD_HISTORY`.

## Database (migrasi `0005`)

| Tabel | Isi |
|---|---|
| `fraud_claim_records` | data analitik per klaim (unik per tenant + nomor klaim), `source` HISTORY/PLATFORM, `claim_id` bila klaim platform |
| `fraud_runs` | versi aturan, jumlah klaim dan sinyal, skor per entitas (JSON) |
| `fraud_signals` | aturan, entitas, pesan, bobot, `claim_numbers`, `evidence` (JSON) |
| `fraud_reviews` | telaah investigator per (tenant, aturan, entitas) |

## Demo

1. `git pull origin dev`, lalu jalankan ulang docker (ada dependensi baru `networkx`):
   ```powershell
   docker compose down -v
   docker compose up -d --build
   docker compose exec -T api python infra/scripts/seed_demo.py
   ```
   Seed membuat `data/synthetic_output/fraud/riwayat_klaim.csv` bila belum ada, mengimpornya ke tenant DEMO dan PELITA, lalu menjalankan analisis. Hasilnya 8 sinyal di setiap tenant.
2. Masuk sebagai `manajer@demo.test` (atau pilih "Manajer klaim" di Ganti peran), lalu buka **Fraud Monitor**.
   - "Provider berisiko": RS Cempaka Rekaan (lama rawat), dr. Prita Pratama (biaya per hari), dan dr. Miftah Halim (lab). Klik satu baris untuk menyaring sinyalnya.
   - Klik sinyal FRD-01 untuk melihat angka pembanding, sebaran indeks semua RS, graf RS–dokter, dan klaim dengan lama rawat tertinggi.
   - Klik sinyal FRD-05 untuk melihat graf rekening bersama: enam peserta, alamat masing-masing, dan RS tempat mereka dirawat.
   - Klik sinyal FRD-07 untuk melihat dua panah rujukan yang saling berbalas. Isi telaah "Pola terkonfirmasi" lalu simpan. Klaim tidak berubah.
3. Buka detail klaim mana pun: kartu **Analitik fraud** menampilkan skor fraud klaim, terpisah dari rekomendasi klinis.
4. Contoh klaim platform yang terkait sinyal: unggah klaim apa pun dengan nomor peserta `PST-H-9002`, lalu jalankan analisis. Kartu fraud klaim itu akan menampilkan FRD-09 (peserta dengan rawat inap tumpang tindih).
5. `docker compose exec api python -m evaluation.fraud_eval` membuat ulang laporan evaluasi.

Generator riwayat dijalankan sendiri dengan `python -m synthetic.generate_fraud`; generator ini juga ikut dijalankan oleh `docker compose run --rm synthetic`.

## Batasan POC

- Analisis berjalan sinkron di request API. Untuk jutaan klaim, analisis perlu dipindah ke worker (RQ) dan statistik dihitung bertahap. Untuk graf sebesar itu, database graf baru perlu dipertimbangkan.
- Rekening dan alamat hanya tersedia dari riwayat impor. Klaim yang masuk lewat portal, API, FHIR, atau SFTP belum membawa kedua data itu.
- Nama RS dan dokter dicocokkan sebagai teks persis. Data sungguhan butuh master data provider (kode faskes, SIP dokter).
- Ambang aturan dikalibrasi pada data sintetis. Sebelum memakai data sungguhan, ambang perlu divalidasi bersama tim investigasi asuransi.
