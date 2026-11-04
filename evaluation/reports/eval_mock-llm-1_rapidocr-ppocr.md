# Laporan evaluasi Tahap 0

> **DATA REKAAN UNTUK DEMONSTRASI.** Semua angka berasal dari 30 klaim sintetis buatan generator repo ini, bukan data klaim sungguhan. Aturan klinis masih draf dan belum divalidasi dokter.

> LLM yang dipakai adalah **mock** yang menjawab dari skenario sintetis. Angka di bawah menguji pembacaan dokumen, cek bukti, aturan, dan triase, **bukan** kualitas model AI sungguhan.

Dibuat 2026-11-04T13:06:59 · LLM `mock-llm-1` · OCR `rapidocr-ppocr` · aturan `rules-2026.11-demo`

## Ringkasan

| Ukuran | Hasil | Target |
|---|---|---|
| Akurasi ekstraksi field kunci | 100.0% | >= 90% |
| Akurasi ekstraksi semua field | 100.0% | - |
| Status triase sesuai kunci jawaban | 96.7% | >= 90% |
| Status + rekomendasi awal sesuai | 96.7% | - |
| Klaim bermasalah keliru jadi hijau | 0  | 0 |
| Temuan dengan bukti yang bisa ditelusuri | 22/22 | semua |
| Waktu proses per klaim (rata-rata / median / maks) | 3.9 / 0.2 / 15.2 detik | - |

## Ekstraksi per mode dokumen

| Mode | Benar | Total | Akurasi |
|---|---|---|---|
| pindaian | 165 | 165 | 100.0% |
| semua | 419 | 419 | 100.0% |
| digital | 254 | 254 | 100.0% |

## Per klaim

| Klaim | Mode | Ekstraksi | Harapan | Hasil | Aturan hasil | Catatan kualitas | Detik |
|---|---|---|---|---|---|---|---|
| SYN-DEN-01 | pindaian | 14/14 | GREEN / PAY_FULL | GREEN / PAY_FULL | - | - | 15.2 |
| SYN-DEN-02 | digital | 15/15 | GREEN / PAY_FULL | GREEN / PAY_FULL | - | - | 0.2 |
| SYN-DEN-03 | digital | 14/14 | GREEN / PAY_FULL | GREEN / PAY_FULL | - | - | 0.2 |
| SYN-DEN-04 | digital | 14/14 | GREEN / PAY_FULL | GREEN / PAY_FULL | - | - | 0.2 |
| SYN-DEN-05 | digital | 14/14 | GREEN / PAY_FULL | GREEN / PAY_FULL | - | - | 0.3 |
| SYN-DEN-06 | pindaian | 14/14 | GREEN / PAY_FULL | YELLOW / DOCTOR_REVIEW ⚠ | - | AI_UNVERIFIED, RULE_SKIPPED | 11.7 |
| SYN-DEN-07 | pindaian | 14/14 | RED / DOCTOR_REVIEW | RED / DOCTOR_REVIEW | DEN-01, DEN-03 | - | 10.2 |
| SYN-DEN-08 | digital | 15/15 | YELLOW / DOCTOR_REVIEW | YELLOW / DOCTOR_REVIEW | DEN-02 | - | 0.2 |
| SYN-DEN-09 | digital | 14/14 | YELLOW / DOCTOR_REVIEW | YELLOW / DOCTOR_REVIEW | DEN-03, DEN-05 | - | 0.2 |
| SYN-DEN-10 | pindaian | 14/14 | RED / DOCTOR_REVIEW | RED / DOCTOR_REVIEW | GEN-02, DEN-04 | - | 13.4 |
| SYN-TIF-01 | pindaian | 15/15 | GREEN / PAY_FULL | GREEN / PAY_FULL | - | - | 8.6 |
| SYN-TIF-02 | digital | 15/15 | GREEN / PAY_FULL | GREEN / PAY_FULL | - | - | 0.2 |
| SYN-TIF-03 | pindaian | 15/15 | GREEN / PAY_FULL | GREEN / PAY_FULL | - | - | 7.7 |
| SYN-TIF-04 | digital | 16/16 | GREEN / PAY_FULL | GREEN / PAY_FULL | - | - | 0.3 |
| SYN-TIF-05 | digital | 14/14 | GREEN / PAY_FULL | GREEN / PAY_FULL | TIF-02 | - | 0.2 |
| SYN-TIF-06 | digital | 14/14 | RED / DOCTOR_REVIEW | RED / DOCTOR_REVIEW | TIF-01, TIF-03 | - | 0.2 |
| SYN-TIF-07 | digital | 15/15 | YELLOW / DOCTOR_REVIEW | YELLOW / DOCTOR_REVIEW | TIF-04 | - | 0.2 |
| SYN-TIF-08 | digital | 16/16 | RED / DOCTOR_REVIEW | RED / DOCTOR_REVIEW | TIF-05 | - | 0.2 |
| SYN-TIF-09 | pindaian | 15/15 | YELLOW / DOCTOR_REVIEW | YELLOW / DOCTOR_REVIEW | TIF-06 | - | 10.5 |
| SYN-TIF-10 | pindaian | 15/15 | YELLOW / PEND | YELLOW / PEND | GEN-03 | RULE_SKIPPED | 5.2 |
| SYN-GEA-01 | pindaian | 13/13 | GREEN / PAY_FULL | GREEN / PAY_FULL | - | - | 7.1 |
| SYN-GEA-02 | digital | 13/13 | GREEN / PAY_FULL | GREEN / PAY_FULL | - | - | 0.1 |
| SYN-GEA-03 | pindaian | 13/13 | GREEN / PAY_FULL | GREEN / PAY_FULL | - | - | 8.8 |
| SYN-GEA-04 | digital | 13/13 | GREEN / PAY_FULL | GREEN / PAY_FULL | - | - | 0.2 |
| SYN-GEA-05 | digital | 13/13 | GREEN / PAY_FULL | GREEN / PAY_FULL | - | - | 0.1 |
| SYN-GEA-06 | pindaian | 13/13 | RED / DOCTOR_REVIEW | RED / DOCTOR_REVIEW | GEA-01, GEA-02, GEA-03 | - | 7.9 |
| SYN-GEA-07 | digital | 13/13 | YELLOW / DOCTOR_REVIEW | YELLOW / DOCTOR_REVIEW | GEA-03 | - | 0.2 |
| SYN-GEA-08 | digital | 13/13 | RED / DOCTOR_REVIEW | RED / DOCTOR_REVIEW | GEN-04, GEA-04 | - | 0.2 |
| SYN-GEA-09 | pindaian | 10/10 | YELLOW / PEND | YELLOW / PEND | GEN-03 | - | 5.8 |
| SYN-GEA-10 | digital | 13/13 | RED / DOCTOR_REVIEW | RED / DOCTOR_REVIEW | GEN-01 | - | 0.1 |

## Akurasi per field

| Field | Benar | Total | Akurasi |
|---|---|---|---|
| `bill.duplicate_items` | 29 | 29 | 100.0% |
| `claim.care_type` | 30 | 30 | 100.0% |
| `claim.los_days` | 30 | 30 | 100.0% |
| `claim.patient_age` | 30 | 30 | 100.0% |
| `docs.missing` | 2 | 2 | 100.0% |
| `dx.primary` | 30 | 30 | 100.0% |
| `dx.secondary` | 2 | 2 | 100.0% |
| `lab.blood_culture_typhi` | 7 | 7 | 100.0% |
| `lab.cbc_max_per_day` | 29 | 29 | 100.0% |
| `lab.dengue_igm` | 2 | 2 | 100.0% |
| `lab.dengue_ns1` | 10 | 10 | 100.0% |
| `lab.hct_rise_pct` | 10 | 10 | 100.0% |
| `lab.platelet_min` | 29 | 29 | 100.0% |
| `lab.stool_pathogen` | 9 | 9 | 100.0% |
| `lab.typhi_rapid` | 1 | 1 | 100.0% |
| `lab.widal_fourfold_rise` | 10 | 10 | 100.0% |
| `lab.widal_o_max_titer` | 10 | 10 | 100.0% |
| `lab.widal_tests` | 29 | 29 | 100.0% |
| `tx.antibiotic_given` | 30 | 30 | 100.0% |
| `tx.ceftriaxone_days` | 30 | 30 | 100.0% |
| `tx.fluoroquinolone_given` | 30 | 30 | 100.0% |
| `tx.iv_fluid_days` | 30 | 30 | 100.0% |

Waktu proses diukur di mesin yang menjalankan evaluasi (baca dokumen + OCR + LLM + aturan), tanpa antrean.
