/** U7: tipe dan label underwriting medis. */

export type UwStatus = "QUEUED" | "PROCESSING" | "AWAITING_DOCTOR" | "AWAITING_UNDERWRITER" | "DECIDED" | "FAILED";
export type UwRecommendation = "ACCEPT_STANDARD" | "ACCEPT_CONDITIONAL" | "POSTPONE" | "DECLINE";

export interface UwSummary {
  id: string;
  application_number: string;
  status: UwStatus;
  insurer_id: string;
  insurer_name: string;
  spaj_number: string | null;
  applicant_name: string | null;
  applicant_sex: string | null;
  applicant_birth_date: string | null;
  product_name: string | null;
  sum_assured: number | null;
  base_premium: number | null;
  created_at: string;
  updated_at: string;
  documents: number;
  processing_error: string | null;
  recommendation: UwRecommendation | null;
  risk_class: string | null;
  loading_pct: number;
  terms_source: "doctor" | "system" | null;
  needs_doctor: boolean | null;
  signed_by: string | null;
  decision: UwRecommendation | null;
  findings: number;
}

export interface UwLabels {
  recommendations: Record<string, string>;
  doc_types: Record<string, string>;
  classes: { code: string; name: string; max_debit?: number }[];
  fields: Record<string, string>;
  questions: Record<string, string>;
  lab_tests: Record<string, string>;
}

export interface UwList {
  items: UwSummary[];
  counts: Record<string, number>;
  label: string;
  can_submit: boolean;
  can_sign: boolean;
  can_decide: boolean;
  rules_version: string;
  labels: UwLabels;
}

export interface UwField {
  value: unknown;
  line_ids: string[];
  source: string;
  detail?: string;
}

export interface UwFinding {
  rule_id: string;
  name: string;
  reason_code: string;
  kind: string;
  debit: number;
  exclusion: string | null;
  decision: string | null;
  note: boolean;
  message: string;
  fields: string[];
  line_ids: string[];
  reference: string | null;
}

export interface UwEvidenceLine {
  document_id: string;
  doc_type: string;
  page: number;
  text: string;
  bbox: number[];
}

export interface UwAssessment {
  id: string;
  version: number;
  fields: Record<string, UwField>;
  profile: Record<string, UwField>;
  findings: UwFinding[];
  skipped: { rule_id: string; name: string; missing: string[] }[];
  evidence: Record<string, UwEvidenceLine>;
  missing_docs: string[];
  missing_fields: string[];
  debit_total: number;
  risk_class: string;
  loading_pct: number;
  exclusions: { reason_code: string; text: string; rule_id: string }[];
  recommendation: UwRecommendation;
  needs_doctor: boolean;
  doctor_reasons: string[];
  rules_version: string;
  model_version: string;
  prompt_version: string;
  ocr_engine: string;
  warnings: string[];
  created_at: string;
}

export interface UwDetail extends UwSummary {
  label: string;
  labels: UwLabels;
  documents_list: { id: string; filename: string; doc_type: string; content_type: string; page_count: number | null; sha256: string; created_at: string }[];
  assessment: UwAssessment | null;
  review: { id: string; doctor: string; action: string; recommendation: UwRecommendation; risk_class: string; loading_pct: number; exclusions: string[]; notes: string | null; signed_at: string } | null;
  decision_detail: { decision: UwRecommendation; risk_class: string; loading_pct: number; exclusions: string[]; final_premium: number | null; notes: string | null; decided_by: string; decided_at: string } | null;
  terms: { source: string | null; recommendation: UwRecommendation | null; risk_class: string | null; loading_pct: number; exclusions: string[] };
  premium_preview: number | null;
  can_sign: boolean;
  can_decide: boolean;
  allowed_decisions: UwRecommendation[];
}

export const UW_STATUS_LABEL: Record<UwStatus, string> = {
  QUEUED: "Antre diproses",
  PROCESSING: "Diproses",
  AWAITING_DOCTOR: "Menunggu dokter",
  AWAITING_UNDERWRITER: "Menunggu underwriter",
  DECIDED: "Diputuskan",
  FAILED: "Gagal diproses",
};

export const UW_REC_LABEL: Record<UwRecommendation, string> = {
  ACCEPT_STANDARD: "Terima standar",
  ACCEPT_CONDITIONAL: "Terima dengan syarat",
  POSTPONE: "Tunda",
  DECLINE: "Tolak",
};

export const UW_REC_STYLE: Record<UwRecommendation, string> = {
  ACCEPT_STANDARD: "bg-emerald-100 text-emerald-800",
  ACCEPT_CONDITIONAL: "bg-amber-100 text-amber-900",
  POSTPONE: "bg-sky-100 text-sky-800",
  DECLINE: "bg-rose-100 text-rose-800",
};

export const UW_KIND_LABEL: Record<string, string> = {
  debit: "Debit",
  debit_pengecualian: "Debit + pengecualian",
  pengecualian: "Pengecualian",
  tunda: "Tunda",
  tolak: "Usul tolak",
  catatan: "Catatan",
};

export function uwValue(v: unknown): string {
  if (v === null || v === undefined) return "tidak terbaca";
  if (typeof v === "boolean") return v ? "Ya" : "Tidak";
  if (typeof v === "number") return v.toLocaleString("id-ID", { maximumFractionDigits: 1 });
  return String(v);
}

/** Label singkat field kamus data (keterangan lengkap ada di aturan YAML). */
export const UW_FIELD_LABEL: Record<string, string> = {
  "applicant.age": "Usia pada tanggal SPAJ",
  "applicant.sex": "Jenis kelamin",
  "applicant.smoker": "Merokok 12 bulan terakhir",
  "vital.height_cm": "Tinggi badan (cm)",
  "vital.weight_kg": "Berat badan (kg)",
  "vital.bmi": "Indeks massa tubuh",
  "vital.systolic": "Tekanan darah sistolik",
  "vital.diastolic": "Tekanan darah diastolik",
  "vital.ecg": "Kesan EKG",
  "doctor.letter": "Ada surat keterangan dokter",
  "doctor.controlled": "Kondisi terkontrol (surat dokter)",
};
