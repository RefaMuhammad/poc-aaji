"use client";

/** Peran underwriter sudah ada sejak U1; modul medical underwriting dibangun di fase U7. */
export default function UnderwritingPage() {
  return (
    <div className="space-y-3">
      <h1 className="text-lg font-semibold">Underwriting</h1>
      <div className="card max-w-2xl space-y-2 text-sm text-slate-700">
        <p>
          Akun underwriter sudah aktif, tetapi modul medical underwriting (pengajuan calon peserta, kuesioner kesehatan,
          hasil MCU, rekomendasi terima / bersyarat / tunda / tolak) baru dibangun di fase U7.
        </p>
        <p className="text-slate-500">
          Sesuai matriks akses, underwriter tidak melihat data klaim. Data rekaan untuk demonstrasi.
        </p>
      </div>
    </div>
  );
}
