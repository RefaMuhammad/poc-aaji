Tugas: ekstrak isi SURAT KETERANGAN DOKTER tentang penyakit calon tertanggung.

Bentuk JSON (setiap field berbentuk {"value": ..., "source_line_ids": [...]}):
{
  "diagnosis": diagnosis yang ditulis dokter (teks, sertakan kode ICD-10 bila ada),
  "since_year": tahun penyakit diketahui (angka),
  "treatment": terapi saat ini (teks),
  "controlled": true bila dokter menyatakan kondisi terkontrol, false bila dinyatakan belum/tidak terkontrol, null bila tidak disebut,
  "letter_date": tanggal surat atau kontrol terakhir,
  "doctor": nama dokter yang menandatangani
}
