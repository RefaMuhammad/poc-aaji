Tugas: ekstrak hasil pemeriksaan fisik dari HASIL MEDICAL CHECK UP.

Bentuk JSON (setiap field berbentuk {"value": ..., "source_line_ids": [...]}):
{
  "exam_date": tanggal pemeriksaan,
  "height_cm": tinggi badan (cm, angka),
  "weight_kg": berat badan (kg, angka),
  "systolic": tekanan darah sistolik (mmHg, angka bulat),
  "diastolic": tekanan darah diastolik (mmHg, angka bulat),
  "pulse": nadi (x/menit, angka bulat),
  "ecg": kesan EKG: "normal" bila dalam batas normal, "iskemia" bila disebut iskemia / depresi ST / gelombang T terbalik,
         "abnormal_ringan" untuk kelainan lain (mis. RBBB inkomplet, ekstrasistol jarang)
}
