# Changelog aturan klinis

## rules-2026.11-demo
- Bagian `triase.aturan_status` kini punya syarat yang bisa dibaca mesin (`ada_kode_alasan`, `ada_keparahan`, `skor_min`) dan `rekomendasi_awal` di setiap baris, supaya ambang triase bisa diubah tanpa mengubah kode.
- Tambah `triase.skor_maksimum` (100).
- Isi 19 aturan klinis tidak berubah.

## rules-2026.10-demo
- Versi awal untuk demo Tahap 0: 19 aturan (4 umum, 5 DBD, 6 tifoid, 4 GEA), kamus data, dan aturan triase.
- Status: draf, belum divalidasi dokter.
