import type { ClaimStatus } from "./types";

export const STATUS_LABEL: Record<ClaimStatus, string> = {
  RECEIVED: "Diterima",
  QUEUED: "Antre diproses",
  PROCESSING: "Diproses",
  AWAITING_DOCTOR: "Menunggu dokter",
  AWAITING_DECISION: "Menunggu keputusan asuransi",
  COMPLETED: "Selesai",
  FAILED: "Gagal diproses",
};

export const IN_PROGRESS: ClaimStatus[] = ["QUEUED", "PROCESSING"];

export const RECOMMENDATION_LABEL: Record<string, string> = {
  PAY_FULL: "Bayar penuh",
  PAY_PARTIAL: "Bayar sebagian",
  PEND: "Tunda: minta dokumen / klarifikasi",
  NOT_COVERED: "Tidak dijamin",
  DOCTOR_REVIEW: "Perlu telaah dokter",
};

export const DOC_TYPE_LABEL: Record<string, string> = {
  resume_medis: "Resume medis",
  hasil_laboratorium: "Hasil laboratorium",
  cppt: "CPPT",
  rincian_tagihan: "Rincian tagihan",
  laporan_operasi: "Laporan operasi",
  resep: "Resep",
  unknown: "Belum dikenali",
};

export const REASON_LABEL: Record<string, string> = {
  DX_NOT_SUPPORTED: "Diagnosis tidak didukung data klinis",
  PROC_NOT_INDICATED: "Tindakan tanpa indikasi",
  LOS_EXCESS: "Lama rawat melebihi kebutuhan",
  DUP_ITEM: "Item tagihan ganda",
  DUP_CLAIM: "Klaim duplikat / tumpang tindih",
  DOC_MISSING: "Dokumen wajib tidak ada",
  DOC_INCONSISTENT: "Dokumen saling bertentangan",
  ADMISSION_NOT_INDICATED: "Rawat inap tanpa indikasi tercatat",
  OVER_SERVICE: "Pemeriksaan melebihi kebutuhan",
  DRUG_NOT_INDICATED: "Obat tanpa indikasi",
  COMPLICATION_UNSUPPORTED: "Komplikasi tidak didukung bukti",
  BILLED_NOT_DOCUMENTED: "Ditagihkan tanpa catatan klinis",
};

export const SEVERITY_LABEL: Record<string, string> = { HIGH: "Tinggi", MEDIUM: "Sedang", LOW: "Rendah", INFO: "Info" };

export function rupiah(n: number | null | undefined): string {
  if (n === null || n === undefined) return "-";
  return "Rp" + n.toLocaleString("id-ID");
}

export function tanggal(iso: string | null | undefined): string {
  if (!iso) return "-";
  const d = new Date(iso.length === 10 ? iso + "T00:00:00" : iso);
  return d.toLocaleDateString("id-ID", { day: "numeric", month: "short", year: "numeric" });
}

export function waktu(iso: string | null | undefined): string {
  if (!iso) return "-";
  return new Date(iso).toLocaleString("id-ID", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

export const LEVEL_LABEL: Record<string, string> = { GP: "Dokter umum", SPECIALIST: "Dokter spesialis" };

export const REVIEW_ACTION_LABEL: Record<string, string> = {
  APPROVE: "Menyetujui draf",
  MODIFY: "Mengubah draf",
  ESCALATE: "Eskalasi ke spesialis",
  RELEASED: "Melepas kasus",
};

export function durasi(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "-";
  if (seconds < 60) return `${seconds} detik`;
  const m = Math.floor(seconds / 60);
  if (m < 60) return `${m} menit`;
  return `${Math.floor(m / 60)} jam ${m % 60} menit`;
}

/** Nilai field untuk ditampilkan (null = tidak diketahui). */
export function nilai(v: unknown): string {
  if (v === null || v === undefined) return "tidak diketahui";
  if (typeof v === "boolean") return v ? "ya" : "tidak";
  if (Array.isArray(v)) return v.length ? v.map((x) => (typeof x === "object" ? JSON.stringify(x) : String(x))).join(", ") : "(kosong)";
  if (typeof v === "number") return v.toLocaleString("id-ID");
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

export function homeFor(role: string | undefined): string {
  if (role === "doctor_gp" || role === "doctor_specialist") return "/telaah";
  if (role === "admin") return "/admin";
  return "/klaim";
}
