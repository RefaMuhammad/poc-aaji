"""Konstanta bersama underwriting: jenis dokumen, pertanyaan kuesioner, pemeriksaan lab.

Dipakai generator data sintetis, mock LLM, ekstraksi, dan web (label), supaya semuanya
membaca "dokumen" yang sama.
"""
from __future__ import annotations

UW_DOC_TYPES = ("spaj", "kuesioner_kesehatan", "hasil_mcu", "hasil_lab_uw", "surat_dokter", "unknown")

UW_DOC_LABELS = {
    "spaj": "SPAJ",
    "kuesioner_kesehatan": "Kuesioner kesehatan",
    "hasil_mcu": "Hasil MCU",
    "hasil_lab_uw": "Hasil laboratorium",
    "surat_dokter": "Surat keterangan dokter",
    "unknown": "Tidak dikenali",
}

# Judul khas di bagian atas dokumen (klasifikasi kata kunci)
UW_TITLE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "spaj": ("surat permintaan asuransi jiwa", "surat pengajuan asuransi", "spaj kesehatan"),
    "kuesioner_kesehatan": ("kuesioner kesehatan", "pernyataan kesehatan"),
    "hasil_mcu": ("hasil medical check up", "hasil pemeriksaan kesehatan", "laporan mcu"),
    "hasil_lab_uw": ("hasil pemeriksaan laboratorium", "hasil laboratorium"),
    "surat_dokter": ("surat keterangan dokter", "surat keterangan sakit", "keterangan medis"),
}

DOC_TITLES = {
    "spaj": "SURAT PERMINTAAN ASURANSI JIWA (SPAJ) KESEHATAN",
    "kuesioner_kesehatan": "KUESIONER KESEHATAN CALON TERTANGGUNG",
    "hasil_mcu": "HASIL MEDICAL CHECK UP",
    "hasil_lab_uw": "HASIL PEMERIKSAAN LABORATORIUM",
    "surat_dokter": "SURAT KETERANGAN DOKTER",
}

# (kode, field riwayat/kebiasaan, teks pertanyaan)
QUESTIONS: list[tuple[str, str, str]] = [
    ("Q1", "hypertension", "Hipertensi (tekanan darah tinggi)"),
    ("Q2", "diabetes", "Diabetes melitus (kencing manis)"),
    ("Q3", "heart_disease", "Penyakit jantung koroner / serangan jantung"),
    ("Q4", "cancer_5y", "Kanker/tumor ganas dalam 5 tahun terakhir"),
    ("Q5", "asthma", "Asma atau penyakit paru kronis"),
    ("Q6", "liver_disease", "Hepatitis atau penyakit hati lain"),
    ("Q7", "pending_treatment", "Menunggu pemeriksaan lanjutan / operasi"),
    ("Q8", "pregnant", "Sedang hamil (khusus perempuan)"),
    ("Q9", "smoker", "Merokok dalam 12 bulan terakhir"),
]
QUESTION_FIELDS = {code: name for code, name, _ in QUESTIONS}

# (kode tes, label di dokumen, satuan, nilai rujukan)
LAB_TESTS: list[tuple[str, str, str, str]] = [
    ("fasting_glucose", "Glukosa darah puasa", "mg/dL", "70-99"),
    ("hba1c", "HbA1c", "%", "< 5,7"),
    ("total_cholesterol", "Kolesterol total", "mg/dL", "< 200"),
    ("ldl", "Kolesterol LDL", "mg/dL", "< 130"),
    ("hdl", "Kolesterol HDL", "mg/dL", "> 40"),
    ("triglycerides", "Trigliserida", "mg/dL", "< 150"),
    ("sgot", "SGOT (AST)", "U/L", "< 40"),
    ("sgpt", "SGPT (ALT)", "U/L", "< 45"),
    ("creatinine", "Kreatinin", "mg/dL", "0,6-1,2"),
    ("hbsag", "HBsAg", "-", "Non-reaktif"),
    ("urine_protein", "Protein urin", "-", "Negatif"),
]
LAB_LABELS = {code: label for code, label, _, _ in LAB_TESTS}

ECG_TEXT = {
    "normal": "Irama sinus, dalam batas normal",
    "abnormal_ringan": "Irama sinus, RBBB inkomplet",
    "iskemia": "Depresi segmen ST di V4-V6, kesan iskemia",
}

RECOMMENDATIONS = ("ACCEPT_STANDARD", "ACCEPT_CONDITIONAL", "POSTPONE", "DECLINE")
RECOMMENDATION_LABELS = {
    "ACCEPT_STANDARD": "Terima standar",
    "ACCEPT_CONDITIONAL": "Terima dengan syarat",
    "POSTPONE": "Tunda",
    "DECLINE": "Tolak",
}
