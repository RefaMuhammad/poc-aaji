# Keputusan residensi data LLM

Status: **menunggu keputusan klien dan tim hukum.** Selama belum diputuskan, `LLM_DATA_RESIDENCY_APPROVED=false` dan
platform menolak start bila `REAL_DATA_ENABLED=true`.

Catatan: ringkasan regulasi di bawah adalah bahan diskusi teknis, bukan nasihat hukum. Tim hukum klien perlu
mengonfirmasi tafsir dan aturan terbaru (termasuk peraturan pelaksana UU PDP dan putusan Mahkamah Konstitusi
terkait Pasal 56).

## Apa yang dikirim ke LLM

Pipeline mengirim teks hasil ekstraksi dokumen (resume medis, hasil lab, kuitansi, SPAJ, kuesioner kesehatan, MCU)
ke LLM untuk klasifikasi dan ekstraksi field terstruktur. Isinya **data kesehatan**, yang menurut UU PDP termasuk data
pribadi yang bersifat spesifik, ditambah nama, tanggal lahir, nomor polis, dan nama fasilitas kesehatan.

## Aturan yang relevan

| Aturan | Inti untuk keputusan ini |
|---|---|
| UU 27/2022 tentang Pelindungan Data Pribadi | Data kesehatan adalah data pribadi spesifik. Transfer ke luar wilayah hukum Indonesia (Pasal 56) hanya bila negara tujuan setara pelindungannya, ada pelindungan memadai dan mengikat, atau ada persetujuan subjek data. Pemrosesan berisiko tinggi butuh penilaian dampak (DPIA) |
| POJK 4/POJK.05/2021 (manajemen risiko TI lembaga jasa keuangan nonbank) | Pusat data dan pusat pemulihan bencana sistem elektronik LJKNB (termasuk asuransi) wajib di Indonesia; penempatan di luar negeri butuh persetujuan OJK. Penyelenggara jasa TI pihak ketiga ikut diatur |
| Kontrak dengan asuransi klien | Platform MAB memproses data atas nama asuransi (pemroses). Lokasi pemrosesan harus sesuai perjanjian pemrosesan data dengan tiap asuransi |

## Pilihan

| | A. Model open-weight di-host sendiri di Indonesia | B. LLM terkelola di region Indonesia | C. API LLM luar negeri (mis. DeepSeek saat ini) |
|---|---|---|---|
| Contoh | Qwen3-32B atau setara di GPU cloud region Jakarta (vLLM, endpoint OpenAI-compatible) | Layanan model terkelola penyedia cloud yang memproses di region Jakarta, bila tersedia untuk model yang dibutuhkan | API publik penyedia di luar negeri |
| Data keluar Indonesia | Tidak | Tidak, bila pemrosesan dijamin di region (cek kontrak dan dokumentasi residensi) | Ya |
| Kecocokan UU PDP / POJK | Paling kuat | Kuat bila residensi dijamin tertulis | Lemah untuk data kesehatan asli; perlu dasar transfer Pasal 56 dan kemungkinan persetujuan OJK |
| Kualitas | Perlu dievaluasi ulang dengan `make eval` dan `make eval-underwriting` | Tergantung model yang tersedia di region | Sudah dipakai untuk uji data rekaan |
| Biaya | GPU tetap per bulan (ada biaya walau sepi) | Per token | Per token, paling murah |
| Operasi | Tim harus mengelola GPU, model, pembaruan | Dikelola penyedia | Dikelola penyedia |
| Perubahan kode | Tidak ada: `LLM_PROVIDER=openai_compatible`, `LLM_BASE_URL`, `LLM_MODEL` | Tidak ada bila OpenAI-compatible; adaptor kecil bila tidak | Tidak ada |

## Rekomendasi

1. **Data rekaan (sekarang sampai pilot):** boleh tetap memakai C atau mock. Tidak ada data pribadi asli.
2. **Pilot dengan data sungguhan:** pilih **A** atau **B** di region Indonesia, dengan syarat:
   - lulus evaluasi pada data rekaan dengan ambang yang sama dengan model saat ini (akurasi ekstraksi, triase,
     kelas risiko underwriting, dan nol "hijau keliru");
   - penyedia memberi jaminan tertulis: data tidak disimpan atau dipakai untuk melatih model, dan diproses di Indonesia;
   - endpoint LLM hanya bisa diakses dari klaster (jaringan privat), dengan TLS.
3. **Tidak memakai C untuk data sungguhan** kecuali tim hukum menetapkan dasar transfer Pasal 56 yang sah dan OJK
   menyetujui, serta setiap asuransi klien menyetujui di perjanjian pemrosesan data.

## Yang perlu diputuskan

| Keputusan | Pemilik | Status |
|---|---|---|
| Pilihan A atau B (atau C dengan dasar hukum) | Klien + tim hukum + MAB | Belum |
| Model dan penyedia GPU/LLM, region | MAB (teknis) setelah pilihan di atas | Belum |
| Hasil evaluasi model terpilih pada data rekaan | MAB (teknis) | Belum |
| Persetujuan tertulis di perjanjian pemrosesan data tiap asuransi | Klien | Belum |

Setelah semua baris di atas selesai, atur `LLM_DATA_RESIDENCY_APPROVED=true` di Secret/ConfigMap produksi dan catat
nomor dokumen persetujuannya di checklist UU PDP.
