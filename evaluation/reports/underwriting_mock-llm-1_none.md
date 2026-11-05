# Evaluasi underwriting medis (U7) · mock-llm-1 · OCR none

Data rekaan untuk demonstrasi. Angka dari kasus sintetis, bukan data calon peserta sungguhan. Dengan LLM tiruan (mock), angka ini menguji pembacaan dokumen, bukti, dan aturan, bukan kualitas model AI. Debit, kelas risiko, dan loading adalah contoh; pada pemakaian sungguhan diambil dari tabel klien.

Dibuat 2026-11-05T14:53:09 · aturan `uw-2026.11-demo` · 35 kasus

| Ukuran | Hasil |
|---|---|
| Akurasi kelas risiko | **88.6%** |
| Akurasi rekomendasi (standar/bersyarat/tunda/tolak) | 88.6% |
| Loading premi tepat sama | 94.3% |
| Pengecualian tepat sama | 100.0% |
| Catatan (dugaan tidak diungkap, surat dokter) tepat sama | 100.0% |
| Semua komponen tepat sama | 88.6% |
| Akurasi ekstraksi field aturan | 95.1% |
| Usulan selain terima standar tanpa telaah dokter | **0** (target 0) |
| Usulan tolak tanpa telaah dokter | **0** (target 0) |
| Kasus dikirim ke dokter | 29 dari 35 |
| Temuan dengan bukti baris dokumen | 31 dari 38 |
| Rata-rata waktu proses per kasus | 0.12 detik |

## Matriks kelas risiko (baris = kunci jawaban, kolom = sistem)

| Kunci \ Sistem | STANDARD | SUB1 | SUB2 | SUB3 | SUB4 | POSTPONE | DECLINE |
|---|---|---|---|---|---|---|---|
| STANDARD | 7 |  |  |  |  | 2 |  |
| SUB1 |  | 9 |  |  |  |  |  |
| SUB2 |  |  | 4 |  |  | 1 |  |
| SUB3 |  |  |  | 2 |  |  |  |
| SUB4 |  |  |  |  |  | 1 |  |
| POSTPONE |  |  |  |  |  | 6 |  |
| DECLINE |  |  |  |  |  |  | 3 |

## Per kasus

| Kasus | Skenario | Pindaian | Kelas (kunci → sistem) | Rekomendasi (kunci → sistem) | Loading | Debit | Ke dokter |
|---|---|---|---|---|---|---|---|
| UW-01 | sehat | - | STANDARD → STANDARD | ACCEPT_STANDARD → ACCEPT_STANDARD | 0 → 0 | 0 | tidak |
| UW-02 | sehat | - | STANDARD → STANDARD | ACCEPT_STANDARD → ACCEPT_STANDARD | 0 → 0 | 0 | tidak |
| UW-03 ⚠ | sehat | hasil_mcu | STANDARD → POSTPONE | ACCEPT_STANDARD → POSTPONE | 0 → 0 | 0 | ya |
| UW-04 | sehat | - | STANDARD → STANDARD | ACCEPT_STANDARD → ACCEPT_STANDARD | 0 → 0 | 0 | tidak |
| UW-05 | sehat | - | STANDARD → STANDARD | ACCEPT_STANDARD → ACCEPT_STANDARD | 0 → 0 | 0 | tidak |
| UW-06 | sehat | - | STANDARD → STANDARD | ACCEPT_STANDARD → ACCEPT_STANDARD | 0 → 0 | 0 | tidak |
| UW-07 | sehat | - | STANDARD → STANDARD | ACCEPT_STANDARD → ACCEPT_STANDARD | 0 → 0 | 0 | tidak |
| UW-08 ⚠ | sehat | hasil_mcu | STANDARD → POSTPONE | ACCEPT_STANDARD → POSTPONE | 0 → 0 | 0 | ya |
| UW-09 | perokok | - | SUB1 → SUB1 | ACCEPT_CONDITIONAL → ACCEPT_CONDITIONAL | 25 → 25 | 25 | ya |
| UW-10 | perokok | - | SUB1 → SUB1 | ACCEPT_CONDITIONAL → ACCEPT_CONDITIONAL | 25 → 25 | 25 | ya |
| UW-11 | obesitas_1 | - | SUB1 → SUB1 | ACCEPT_CONDITIONAL → ACCEPT_CONDITIONAL | 25 → 25 | 25 | ya |
| UW-12 | obesitas_1 | - | SUB1 → SUB1 | ACCEPT_CONDITIONAL → ACCEPT_CONDITIONAL | 25 → 25 | 25 | ya |
| UW-13 ⚠ | obesitas_2 | hasil_mcu | SUB2 → POSTPONE | ACCEPT_CONDITIONAL → POSTPONE | 50 → 0 | 0 | ya |
| UW-14 | ht_terkontrol | - | SUB1 → SUB1 | ACCEPT_CONDITIONAL → ACCEPT_CONDITIONAL | 25 → 25 | 25 | ya |
| UW-15 | ht_terkontrol | surat_dokter | SUB1 → SUB1 | ACCEPT_CONDITIONAL → ACCEPT_CONDITIONAL | 25 → 25 | 25 | ya |
| UW-16 | ht_derajat1 | - | SUB1 → SUB1 | ACCEPT_CONDITIONAL → ACCEPT_CONDITIONAL | 25 → 25 | 25 | ya |
| UW-17 | ht_derajat2 | - | SUB2 → SUB2 | ACCEPT_CONDITIONAL → ACCEPT_CONDITIONAL | 50 → 50 | 50 | ya |
| UW-18 | ht_krisis | hasil_mcu | POSTPONE → POSTPONE | POSTPONE → POSTPONE | 0 → 0 | 0 | ya |
| UW-19 | dm_terkontrol | surat_dokter | SUB2 → SUB2 | ACCEPT_CONDITIONAL → ACCEPT_CONDITIONAL | 50 → 50 | 50 | ya |
| UW-20 | dm_terkontrol | - | SUB2 → SUB2 | ACCEPT_CONDITIONAL → ACCEPT_CONDITIONAL | 50 → 50 | 50 | ya |
| UW-21 | dm_tidak_diungkap | - | SUB3 → SUB3 | ACCEPT_CONDITIONAL → ACCEPT_CONDITIONAL | 100 → 100 | 100 | ya |
| UW-22 | dm_tidak_terkontrol | - | DECLINE → DECLINE | DECLINE → DECLINE | 0 → 0 | 0 | ya |
| UW-23 ⚠ | kombinasi_sub4 | surat_dokter, hasil_mcu | SUB4 → POSTPONE | ACCEPT_CONDITIONAL → POSTPONE | 125 → 0 | 75 | ya |
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
| `doctor.controlled` | 6/9 | 66.7 |
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
| `vital.bmi` | 28/35 | 80.0 |
| `vital.diastolic` | 28/35 | 80.0 |
| `vital.ecg` | 28/35 | 80.0 |
| `vital.height_cm` | 28/35 | 80.0 |
| `vital.systolic` | 28/35 | 80.0 |
| `vital.weight_kg` | 28/35 | 80.0 |

## Field yang tidak cocok

| Kasus | Field | Kunci | Sistem |
|---|---|---|---|
| UW-03 | `vital.height_cm` | 155 | None |
| UW-03 | `vital.weight_kg` | 56 | None |
| UW-03 | `vital.bmi` | 23.3 | None |
| UW-03 | `vital.systolic` | 121 | None |
| UW-03 | `vital.diastolic` | 81 | None |
| UW-03 | `vital.ecg` | normal | None |
| UW-08 | `vital.height_cm` | 169 | None |
| UW-08 | `vital.weight_kg` | 67 | None |
| UW-08 | `vital.bmi` | 23.5 | None |
| UW-08 | `vital.systolic` | 108 | None |
| UW-08 | `vital.diastolic` | 80 | None |
| UW-08 | `vital.ecg` | normal | None |
| UW-13 | `vital.height_cm` | 156 | None |
| UW-13 | `vital.weight_kg` | 91 | None |
| UW-13 | `vital.bmi` | 37.4 | None |
| UW-13 | `vital.systolic` | 113 | None |
| UW-13 | `vital.diastolic` | 73 | None |
| UW-13 | `vital.ecg` | normal | None |
| UW-15 | `doctor.controlled` | True | None |
| UW-18 | `vital.height_cm` | 180 | None |
| UW-18 | `vital.weight_kg` | 65 | None |
| UW-18 | `vital.bmi` | 20.1 | None |
| UW-18 | `vital.systolic` | 184 | None |
| UW-18 | `vital.diastolic` | 114 | None |
| UW-18 | `vital.ecg` | normal | None |
| UW-19 | `doctor.controlled` | True | None |
| UW-23 | `vital.height_cm` | 163 | None |
| UW-23 | `vital.weight_kg` | 97 | None |
| UW-23 | `vital.bmi` | 36.5 | None |
| UW-23 | `vital.systolic` | 128 | None |
| UW-23 | `vital.diastolic` | 77 | None |
| UW-23 | `vital.ecg` | normal | None |
| UW-23 | `doctor.controlled` | True | None |
| UW-28 | `vital.height_cm` | 160 | None |
| UW-28 | `vital.weight_kg` | 57 | None |
| UW-28 | `vital.bmi` | 22.3 | None |
| UW-28 | `vital.systolic` | 127 | None |
| UW-28 | `vital.diastolic` | 76 | None |
| UW-28 | `vital.ecg` | normal | None |
| UW-33 | `vital.height_cm` | 160 | None |
| UW-33 | `vital.weight_kg` | 51 | None |
| UW-33 | `vital.bmi` | 19.9 | None |
| UW-33 | `vital.systolic` | 127 | None |
| UW-33 | `vital.diastolic` | 80 | None |
| UW-33 | `vital.ecg` | iskemia | None |
