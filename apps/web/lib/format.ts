import type { ClaimStatus } from "./types";

export const STATUS_LABEL: Record<ClaimStatus, string> = {
  RECEIVED: "Diterima",
  QUEUED: "Antre diproses",
  PROCESSING: "Diproses",
  AWAITING_DOCTOR: "Menunggu dokter",
  AWAITING_DECISION: "Menunggu keputusan asuransi",
  PENDING_DOCUMENTS: "Menunggu dokumen susulan",
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
  // U2: aturan benefit polis
  POLICY_NOT_FOUND: "Polis peserta tidak ditemukan",
  POLICY_INACTIVE: "Polis tidak aktif saat rawat",
  WAITING_PERIOD: "Masih dalam masa tunggu",
  EXCLUDED_CONDITION: "Diagnosis dikecualikan polis",
  LIMIT_EXCEEDED: "Melebihi sisa limit tahunan",
  ROOM_CLASS_EXCEEDED: "Kelas kamar melebihi hak",
};

export const SOURCE_LABEL: Record<string, string> = {
  PORTAL: "Portal",
  BATCH: "Unggah massal",
  API: "API",
  SFTP: "SFTP",
  FHIR: "FHIR",
};

export const POLICY_STATUS_LABEL: Record<string, string> = { ACTIVE: "Aktif", LAPSED: "Lewat masa", TERMINATED: "Berakhir" };

export const CHANNEL_LABEL: Record<string, string> = {
  API: "API klaim",
  FHIR: "FHIR Bundle",
  SFTP: "SFTP batch",
  POLICY_IMPORT: "Impor polis (file)",
  POLICY_API: "Polis lewat API",
  FRAUD_HISTORY: "Riwayat klaim (fraud)",
};

export const JOB_STATUS_LABEL: Record<string, string> = { SUCCESS: "Berhasil", PARTIAL: "Sebagian", FAILED: "Gagal" };
export const DELIVERY_STATUS_LABEL: Record<string, string> = { PENDING: "Menunggu", DELIVERED: "Terkirim", FAILED: "Gagal" };

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
  if (role === "underwriter") return "/underwriting";
  if (role === "facility_officer") return "/faskes";
  if (role === "member") return "/peserta";
  if (role === "tpa_operator") return "/tpa";
  return "/klaim";
}

export const ROLE_LABEL: Record<string, string> = {
  insurer_staff: "Staf klaim",
  insurer_manager: "Manajer klaim",
  tpa_operator: "Operator TPA",
  doctor_gp: "Dokter umum",
  doctor_specialist: "Dokter spesialis",
  auditor: "Auditor",
  facility_officer: "Petugas faskes",
  member: "Peserta",
  underwriter: "Underwriter",
  admin: "Admin",
};

export const SLA_LABEL: Record<string, string> = {
  ON_TRACK: "Sesuai SLA",
  AT_RISK: "Hampir lewat",
  OVERDUE: "Lewat SLA",
};

/** Sisa waktu (atau keterlambatan) sampai batas SLA, mis. "sisa 5 j 20 m" / "lewat 2 j". */
export function slaRemaining(due: string | null | undefined, now: number = Date.now()): string {
  if (!due) return "-";
  const diff = new Date(due).getTime() - now;
  const mins = Math.round(Math.abs(diff) / 60000);
  const d = Math.floor(mins / 1440);
  const h = Math.floor((mins % 1440) / 60);
  const m = mins % 60;
  const text = d > 0 ? `${d} hr ${h} j` : h > 0 ? `${h} j ${m} m` : `${m} m`;
  return diff >= 0 ? `sisa ${text}` : `lewat ${text}`;
}

// ----------------------------------------------------------------------------- U3 fraud analytics

export const FRAUD_ENTITY_LABEL: Record<string, string> = {
  HOSPITAL: "Rumah sakit",
  DOCTOR: "Dokter",
  MEMBER: "Peserta",
  BANK_ACCOUNT: "Rekening",
  ADDRESS: "Alamat",
  REFERRAL_LOOP: "Rujukan berputar",
};

export const FRAUD_REVIEW_LABEL: Record<string, string> = {
  OPEN: "Belum ditelaah",
  INVESTIGATING: "Sedang diselidiki",
  CONFIRMED: "Pola terkonfirmasi",
  DISMISSED: "Wajar / bukan fraud",
};

export const FRAUD_REVIEW_STYLE: Record<string, string> = {
  OPEN: "bg-slate-100 text-slate-700",
  INVESTIGATING: "bg-sky-50 text-sky-900",
  CONFIRMED: "bg-rose-50 text-rose-800",
  DISMISSED: "bg-emerald-50 text-emerald-800",
};

export const FRAUD_LEVEL_STYLE: Record<string, string> = {
  TINGGI: "bg-rose-100 text-rose-800",
  SEDANG: "bg-amber-100 text-amber-900",
  RENDAH: "bg-slate-100 text-slate-700",
};

export const FRAUD_SOURCE_LABEL: Record<string, string> = {
  HISTORY: "riwayat impor",
  PLATFORM: "klaim platform",
};

/** Angka desimal gaya Indonesia: 7.25 -> "7,25". */
export function desimal(n: number | null | undefined, digits = 1): string {
  if (n === null || n === undefined) return "-";
  return n.toLocaleString("id-ID", { maximumFractionDigits: digits });
}

/** Jenis dokumen yang bisa diminta sebagai dokumen susulan (sama dengan KNOWN_DOC_TYPES di API). */
export const REQUESTABLE_DOC_TYPES = ["resume_medis", "rincian_tagihan", "hasil_laboratorium", "cppt", "laporan_operasi", "resep"];

export const REQUEST_STATUS_LABEL: Record<string, string> = { OPEN: "Menunggu dokumen", FULFILLED: "Sudah dipenuhi", CANCELLED: "Dibatalkan" };

export const NOTIFICATION_EVENT_LABEL: Record<string, string> = {
  "claim.documents_requested": "Permintaan dokumen",
  "claim.documents_received": "Dokumen diterima",
  "claim.recommendation_released": "Rekomendasi dirilis",
  "claim.decision_recorded": "Keputusan klaim",
};
