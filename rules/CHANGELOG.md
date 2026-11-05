# Changelog aturan klinis

## benefit-2026.11-demo (file baru `aturan_benefit_demo.yaml`, U2)
- Aturan benefit polis terpisah dari aturan klinis: BEN-00 polis tidak ditemukan, BEN-01 polis tidak aktif,
  BEN-02 masa tunggu, BEN-03 diagnosis dikecualikan, BEN-04 melebihi sisa limit, BEN-05 kelas kamar melebihi hak.
- Kode alasan baru: POLICY_NOT_FOUND, POLICY_INACTIVE, WAITING_PERIOD, EXCLUDED_CONDITION, LIMIT_EXCEEDED, ROOM_CLASS_EXCEEDED.
- Isi aturan klinis `rules-2026.11-demo` tidak berubah.

## rules-2026.11-demo
- Bagian `triase.aturan_status` kini punya syarat yang bisa dibaca mesin (`ada_kode_alasan`, `ada_keparahan`, `skor_min`) dan `rekomendasi_awal` di setiap baris, supaya ambang triase bisa diubah tanpa mengubah kode.
- Tambah `triase.skor_maksimum` (100).
- Isi 19 aturan klinis tidak berubah.
- (M7) Tambah `spesialisasi` per diagnosis untuk menentukan dokter spesialis penelaah kasus merah dan eskalasi. Hanya dipakai untuk antrean dokter; tidak mengubah temuan, skor, atau rekomendasi.

## rules-2026.10-demo
- Versi awal untuk demo Tahap 0: 19 aturan (4 umum, 5 DBD, 6 tifoid, 4 GEA), kamus data, dan aturan triase.
- Status: draf, belum divalidasi dokter.
