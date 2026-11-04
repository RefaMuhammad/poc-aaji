Tugas: ekstrak data RESUME MEDIS.

Bentuk JSON:
{
  "care_type": {"value": "inpatient" | "outpatient" | null, "source_line_ids": [...]},
  "patient_age": {"value": <usia dalam tahun, angka bulat> | null, "source_line_ids": [...]},
  "admission_date": {"value": "YYYY-MM-DD" | null, "source_line_ids": [...]},
  "discharge_date": {"value": "YYYY-MM-DD" | null, "source_line_ids": [...]},
  "primary_dx": {"value": "<kode ICD-10 diagnosis utama, mis. A91>" | null, "source_line_ids": [...]},
  "secondary_dx": {"value": ["<kode ICD-10>", ...], "source_line_ids": [...]},
  "attending_doctor": {"value": "<nama dokter penanggung jawab>" | null, "source_line_ids": [...]}
}

Catatan:
- care_type "inpatient" bila ada tanggal masuk dan tanggal keluar rawat inap yang berbeda.
- Untuk diagnosis, ambil KODE ICD-10 saja (tanpa nama penyakit). Diagnosis sekunder "-" berarti daftar kosong.
