# Evaluasi underwriting medis (U7) · mock-llm-1 · OCR rapidocr-ppocr

Data rekaan untuk demonstrasi. Angka dari kasus sintetis, bukan data calon peserta sungguhan. Dengan LLM tiruan (mock), angka ini menguji pembacaan dokumen, bukti, dan aturan, bukan kualitas model AI. Debit, kelas risiko, dan loading adalah contoh; pada pemakaian sungguhan diambil dari tabel klien.

Dibuat 2026-11-05T14:53:04 · aturan `uw-2026.11-demo` · 35 kasus

| Ukuran | Hasil |
|---|---|
| Akurasi kelas risiko | **100.0%** |
| Akurasi rekomendasi (standar/bersyarat/tunda/tolak) | 100.0% |
| Loading premi tepat sama | 100.0% |
| Pengecualian tepat sama | 100.0% |
| Catatan (dugaan tidak diungkap, surat dokter) tepat sama | 100.0% |
| Semua komponen tepat sama | 100.0% |
| Akurasi ekstraksi field aturan | 100.0% |
| Usulan selain terima standar tanpa telaah dokter | **0** (target 0) |
| Usulan tolak tanpa telaah dokter | **0** (target 0) |
| Kasus dikirim ke dokter | 27 dari 35 |
| Temuan dengan bukti baris dokumen | 35 dari 35 |
| Rata-rata waktu proses per kasus | 0.61 detik |

## Matriks kelas risiko (baris = kunci jawaban, kolom = sistem)

| Kunci \ Sistem | STANDARD | SUB1 | SUB2 | SUB3 | SUB4 | POSTPONE | DECLINE |
|---|---|---|---|---|---|---|---|
| STANDARD | 9 |  |  |  |  |  |  |
| SUB1 |  | 9 |  |  |  |  |  |
| SUB2 |  |  | 5 |  |  |  |  |
| SUB3 |  |  |  | 2 |  |  |  |
| SUB4 |  |  |  |  | 1 |  |  |
| POSTPONE |  |  |  |  |  | 6 |  |
| DECLINE |  |  |  |  |  |  | 3 |

## Per kasus

| Kasus | Skenario | Pindaian | Kelas (kunci → sistem) | Rekomendasi (kunci → sistem) | Loading | Debit | Ke dokter |
|---|---|---|---|---|---|---|---|
| UW-01 | sehat | - | STANDARD → STANDARD | ACCEPT_STANDARD → ACCEPT_STANDARD | 0 → 0 | 0 | tidak |
| UW-02 | sehat | - | STANDARD → STANDARD | ACCEPT_STANDARD → ACCEPT_STANDARD | 0 → 0 | 0 | tidak |
| UW-03 | sehat | hasil_mcu | STANDARD → STANDARD | ACCEPT_STANDARD → ACCEPT_STANDARD | 0 → 0 | 0 | tidak |
| UW-04 | sehat | - | STANDARD → STANDARD | ACCEPT_STANDARD → ACCEPT_STANDARD | 0 → 0 | 0 | tidak |
| UW-05 | sehat | - | STANDARD → STANDARD | ACCEPT_STANDARD → ACCEPT_STANDARD | 0 → 0 | 0 | tidak |
| UW-06 | sehat | - | STANDARD → STANDARD | ACCEPT_STANDARD → ACCEPT_STANDARD | 0 → 0 | 0 | tidak |
| UW-07 | sehat | - | STANDARD → STANDARD | ACCEPT_STANDARD → ACCEPT_STANDARD | 0 → 0 | 0 | tidak |
| UW-08 | sehat | hasil_mcu | STANDARD → STANDARD | ACCEPT_STANDARD → ACCEPT_STANDARD | 0 → 0 | 0 | tidak |
| UW-09 | perokok | - | SUB1 → SUB1 | ACCEPT_CONDITIONAL → ACCEPT_CONDITIONAL | 25 → 25 | 25 | ya |
| UW-10 | perokok | - | SUB1 → SUB1 | ACCEPT_CONDITIONAL → ACCEPT_CONDITIONAL | 25 → 25 | 25 | ya |
| UW-11 | obesitas_1 | - | SUB1 → SUB1 | ACCEPT_CONDITIONAL → ACCEPT_CONDITIONAL | 25 → 25 | 25 | ya |
| UW-12 | obesitas_1 | - | SUB1 → SUB1 | ACCEPT_CONDITIONAL → ACCEPT_CONDITIONAL | 25 → 25 | 25 | ya |
| UW-13 | obesitas_2 | hasil_mcu | SUB2 → SUB2 | ACCEPT_CONDITIONAL → ACCEPT_CONDITIONAL | 50 → 50 | 50 | ya |
| UW-14 | ht_terkontrol | - | SUB1 → SUB1 | ACCEPT_CONDITIONAL → ACCEPT_CONDITIONAL | 25 → 25 | 25 | ya |
| UW-15 | ht_terkontrol | surat_dokter | SUB1 → SUB1 | ACCEPT_CONDITIONAL → ACCEPT_CONDITIONAL | 25 → 25 | 25 | ya |
| UW-16 | ht_derajat1 | - | SUB1 → SUB1 | ACCEPT_CONDITIONAL → ACCEPT_CONDITIONAL | 25 → 25 | 25 | ya |
| UW-17 | ht_derajat2 | - | SUB2 → SUB2 | ACCEPT_CONDITIONAL → ACCEPT_CONDITIONAL | 50 → 50 | 50 | ya |
| UW-18 | ht_krisis | hasil_mcu | POSTPONE → POSTPONE | POSTPONE → POSTPONE | 0 → 0 | 0 | ya |
| UW-19 | dm_terkontrol | surat_dokter | SUB2 → SUB2 | ACCEPT_CONDITIONAL → ACCEPT_CONDITIONAL | 50 → 50 | 50 | ya |
| UW-20 | dm_terkontrol | - | SUB2 → SUB2 | ACCEPT_CONDITIONAL → ACCEPT_CONDITIONAL | 50 → 50 | 50 | ya |
| UW-21 | dm_tidak_diungkap | - | SUB3 → SUB3 | ACCEPT_CONDITIONAL → ACCEPT_CONDITIONAL | 100 → 100 | 100 | ya |
| UW-22 | dm_tidak_terkontrol | - | DECLINE → DECLINE | DECLINE → DECLINE | 0 → 0 | 0 | ya |
| UW-23 | kombinasi_sub4 | surat_dokter, hasil_mcu | SUB4 → SUB4 | ACCEPT_CONDITIONAL → ACCEPT_CONDITIONAL | 125 → 125 | 125 | ya |
| UW-24 | kombinasi_tolak | - | DECLINE → DECLINE | DECLINE → DECLINE | 0 → 0 | 200 | ya |
| UW-25 | asma | - | STANDARD → STANDARD | ACCEPT_CONDITIONAL → ACCEPT_CONDITIONAL | 0 → 0 | 0 | ya |
| UW-26 | hepatitis_b | - | SUB1 → SUB1 | ACCEPT_CONDITIONAL → ACCEPT_CONDITIONAL | 25 → 25 | 25 | ya |
| UW-27 | sgpt_tinggi | - | POSTPONE → POSTPONE | POSTPONE → POSTPONE | 0 → 0 | 0 | ya |
| UW-28 | kanker_5th | hasil_mcu | POSTPONE → POSTPONE | POSTPONE → POSTPONE | 0 → 0 | 0 | ya |
| UW-29 | hamil | - | POSTPONE → POSTPONE | POSTPONE → POSTPONE | 0 → 0 | 0 | ya |
| UW-30 | menunggu_operasi | - | POSTPONE → POSTPONE | POSTPONE → POSTPONE | 0 → 0 | 0 | ya |
| UW-31 | ginjal_berat | - | DECLINE → DECLINE | DECLINE → DECLINE | 0 → 0 | 25 | ya |
| UW-32 | kolesterol_perokok | - | SUB2 → SUB2 | ACCEPT_CONDITIONAL → ACCEPT_CONDITIONAL | 50 → 50 | 50 | ya |
| UW-33 | ekg_iskemia | hasil_mcu | POSTPONE → POSTPONE | POSTPONE → POSTPONE | 0 → 0 | 0 | ya |
| UW-34 | pjk_stabil | - | SUB3 → SUB3 | ACCEPT_CONDITIONAL → ACCEPT_CONDITIONAL | 100 → 100 | 100 | ya |
| UW-35 | ht_tanpa_surat | - | SUB1 → SUB1 | ACCEPT_CONDITIONAL → ACCEPT_CONDITIONAL | 25 → 25 | 25 | ya |

## Akurasi ekstraksi per field

| Field | Benar | % |
|---|---|---|
| `applicant.age` | 35/35 | 100.0 |
| `applicant.sex` | 35/35 | 100.0 |
| `applicant.smoker` | 35/35 | 100.0 |
| `doctor.controlled` | 9/9 | 100.0 |
| `doctor.letter` | 35/35 | 100.0 |
| `history.asthma` | 35/35 | 100.0 |
| `history.cancer_5y` | 35/35 | 100.0 |
| `history.diabetes` | 35/35 | 100.0 |
| `history.heart_disease` | 35/35 | 100.0 |
| `history.hypertension` | 35/35 | 100.0 |
| `history.liver_disease` | 35/35 | 100.0 |
| `history.pending_treatment` | 35/35 | 100.0 |
| `history.pregnant` | 35/35 | 100.0 |
| `lab.creatinine` | 35/35 | 100.0 |
| `lab.fasting_glucose` | 35/35 | 100.0 |
| `lab.hba1c` | 35/35 | 100.0 |
| `lab.hbsag` | 35/35 | 100.0 |
| `lab.ldl` | 35/35 | 100.0 |
| `lab.sgpt` | 35/35 | 100.0 |
| `lab.total_cholesterol` | 35/35 | 100.0 |
| `lab.urine_protein` | 35/35 | 100.0 |
| `vital.bmi` | 35/35 | 100.0 |
| `vital.diastolic` | 35/35 | 100.0 |
| `vital.ecg` | 35/35 | 100.0 |
| `vital.height_cm` | 35/35 | 100.0 |
| `vital.systolic` | 35/35 | 100.0 |
| `vital.weight_kg` | 35/35 | 100.0 |
