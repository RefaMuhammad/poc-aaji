Tugas: ekstrak SEMUA hasil pemeriksaan dari HASIL LABORATORIUM medical check up.

Bentuk JSON:
{
  "results": [
    {"test": "<kode tes>", "value": <nilai>, "source_line_ids": [...]}
  ]
}

Kode tes dan bentuk nilainya:
- "fasting_glucose" glukosa darah puasa (mg/dL, angka)
- "hba1c" HbA1c (%, angka)
- "total_cholesterol" kolesterol total, "ldl" kolesterol LDL, "hdl" kolesterol HDL, "triglycerides" trigliserida (mg/dL, angka)
- "sgot" SGOT/AST, "sgpt" SGPT/ALT (U/L, angka)
- "creatinine" kreatinin serum (mg/dL, angka)
- "hbsag" HBsAg: "pos" bila reaktif/positif, "neg" bila non-reaktif/negatif
- "urine_protein" protein urin: "neg", "+1", "+2", atau "+3"
- "other" pemeriksaan lain: tulis teks hasilnya
