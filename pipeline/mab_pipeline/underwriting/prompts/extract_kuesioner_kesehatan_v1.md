Tugas: ekstrak jawaban kuesioner kesehatan calon tertanggung.

Bentuk JSON:
{
  "answers": [
    {"code": "<kode>", "value": true/false/null, "detail": "<keterangan atau null>", "source_line_ids": [...]}
  ]
}

Kode pertanyaan (cocokkan dengan isi pertanyaan, bukan nomornya):
- "Q1" hipertensi / tekanan darah tinggi
- "Q2" diabetes melitus / kencing manis
- "Q3" penyakit jantung koroner / serangan jantung
- "Q4" kanker atau tumor ganas dalam 5 tahun terakhir
- "Q5" asma atau penyakit paru kronis
- "Q6" hepatitis atau penyakit hati
- "Q7" sedang menunggu pemeriksaan lanjutan atau operasi
- "Q8" sedang hamil
- "Q9" merokok dalam 12 bulan terakhir

`value` true bila dijawab "Ya", false bila "Tidak", null bila tidak dijawab atau tidak terbaca.
Sertakan id baris pertanyaan beserta jawabannya.
