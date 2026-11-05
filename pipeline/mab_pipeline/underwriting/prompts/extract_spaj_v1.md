Tugas: ekstrak data calon tertanggung dan produk dari SPAJ.

Bentuk JSON (setiap field berbentuk {"value": ..., "source_line_ids": [...]}):
{
  "spaj_number": nomor SPAJ (teks),
  "applicant_name": nama calon tertanggung,
  "sex": "L" untuk laki-laki atau "P" untuk perempuan,
  "birth_date": tanggal lahir,
  "occupation": pekerjaan,
  "product": nama produk,
  "sum_assured": uang pertanggungan (angka rupiah),
  "base_premium": premi dasar tahunan (angka rupiah),
  "spaj_date": tanggal SPAJ ditandatangani
}
