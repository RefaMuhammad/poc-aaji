# Kamus data

Sumber kebenaran kamus data ada di bagian `kamus_data` pada `rules/aturan_klinis_demo.yaml`: setiap field punya tipe (`angka`, `teks`, `ya_tidak`, `daftar`), sumber (`dokumen`, `hitung`, `ai`), dan keterangan. Field yang sama dipakai oleh mesin aturan, ditampilkan di tab **Data ekstraksi** ruang kerja dokter, dan dipakai untuk mengukur akurasi ekstraksi.

Cara field diisi dijelaskan di [ARSITEKTUR.md](ARSITEKTUR.md) bagian 5 (pipeline) dan 6 (mesin aturan).
