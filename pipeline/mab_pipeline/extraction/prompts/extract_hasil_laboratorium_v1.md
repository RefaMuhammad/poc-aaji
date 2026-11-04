Tugas: ekstrak SEMUA hasil pemeriksaan dari dokumen HASIL LABORATORIUM.

Bentuk JSON:
{
  "results": [
    {"date": "YYYY-MM-DD", "time": "HH:MM", "test": "<kode tes>", "value": <nilai>, "source_line_ids": [...]}
  ]
}

Kode tes dan bentuk nilainya:
- "hb" hemoglobin (g/dL, angka), "hct" hematokrit (%, angka), "wbc" leukosit (10^3/uL, angka), "plt" trombosit (/uL, angka bulat, mis. 95000)
- "ns1" NS1 antigen dengue, "dengue_igm" IgM anti-dengue: "pos" atau "neg"
- "widal_o" Widal S. typhi O, "widal_h" Widal S. typhi H: penyebut titer sebagai angka (1/320 menjadi 320)
- "culture_typhi" kultur darah: "pos" bila Salmonella typhi tumbuh, "neg" bila tidak ada pertumbuhan
- "typhi_rapid" tes cepat tifoid (Tubex/Typhidot/IgM salmonella): "pos" atau "neg"
- "stool_pathogen" pemeriksaan feses: true bila ditemukan bakteri/parasit patogen, false bila tidak
- "electrolyte" elektrolit: tulis teks hasilnya
- "other" pemeriksaan lain: tulis teks hasilnya

Satu pemeriksaan darah lengkap menghasilkan empat entri (hb, hct, wbc, plt) dengan tanggal dan jam yang sama.
Tanggal diambil dari judul kelompok hasil (tanggal pemeriksaan), bukan tanggal masuk.
Sertakan id baris tanggal/jam dan id baris nilai di source_line_ids.
