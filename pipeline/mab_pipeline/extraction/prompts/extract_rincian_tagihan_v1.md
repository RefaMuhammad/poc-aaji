Tugas: ekstrak SEMUA baris item dari dokumen RINCIAN TAGIHAN, sesuai urutan di dokumen.

Bentuk JSON:
{
  "items": [
    {"date": "YYYY-MM-DD", "time": "HH:MM" | null, "name": "<uraian item persis seperti tertulis>", "qty": <jumlah>, "unit_price": <tarif satuan dalam rupiah, angka bulat>, "source_line_ids": [...]}
  ]
}

Catatan:
- Jangan menggabungkan atau membuang item yang tampak sama: item ganda harus tetap ditulis dua kali.
- Lewati baris judul kolom dan baris total.
