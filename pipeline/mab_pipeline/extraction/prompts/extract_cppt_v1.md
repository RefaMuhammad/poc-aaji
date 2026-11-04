Tugas: dari CPPT (Catatan Perkembangan Pasien Terintegrasi), ekstrak obat dan cairan infus yang DIBERIKAN atau DIRENCANAKAN pada setiap tanggal catatan (biasanya di bagian P / Plan atau Terapi).

Bentuk JSON:
{
  "medications": [
    {"date": "YYYY-MM-DD", "name": "<nama obat/cairan seperti tertulis, mis. Seftriakson 2 g IV, infus RL, Infus kristaloid>", "source_line_ids": [...]}
  ]
}

Catatan:
- Satu entri per obat per tanggal.
- Jangan masukkan obat yang hanya disebut sebagai riwayat atau yang dihentikan.
