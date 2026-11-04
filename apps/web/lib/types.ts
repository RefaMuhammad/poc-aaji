export type Role = "insurer_staff" | "insurer_manager" | "doctor_gp" | "doctor_specialist" | "admin";

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  insurer_id: string | null;
  specialty: string | null;
}

export type ClaimStatus =
  | "RECEIVED"
  | "QUEUED"
  | "PROCESSING"
  | "AWAITING_DOCTOR"
  | "AWAITING_DECISION"
  | "COMPLETED"
  | "FAILED";

export type Triage = "GREEN" | "YELLOW" | "RED";

export interface ClaimListItem {
  id: string;
  claim_number: string;
  policy_number: string;
  member_id: string;
  patient_name: string | null;
  hospital_name: string;
  admission_date: string;
  discharge_date: string;
  billed_amount: number;
  primary_icd10: string | null;
  status: ClaimStatus;
  processing_error: string | null;
  created_at: string;
  updated_at: string;
  triage_status: Triage | null;
  risk_score: number | null;
  recommendation: string | null;
  decision: string | null;
}

export interface DocumentInfo {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  doc_type: string;
  page_count: number | null;
  created_at: string;
}

export interface ClaimDetail extends Omit<ClaimListItem, "risk_score" | "recommendation"> {
  documents: DocumentInfo[];
  missing_documents: string[];
  recommendation_available: boolean;
  awaiting_doctor: boolean;
}

export interface Evidence {
  doc: string | null;
  page: number | null;
  quote: string | null;
  bbox: number[] | null;
  field: string | null;
  claim_id: string | null;
}

export interface FindingView {
  code: string;
  severity: "HIGH" | "MEDIUM" | "LOW" | "INFO";
  source: string;
  text: string;
  rule_id: string | null;
  evidence: Evidence[];
  guideline_refs: string[];
}

export interface LineAdjustment {
  item: string;
  date: string | null;
  time: string | null;
  qty: number;
  amount: number;
  reason_code: string;
  note: string;
}

export interface Recommendation {
  claim_id: string;
  claim_number: string;
  triage_status: Triage;
  risk_score: number;
  recommendation: string;
  state: "DRAFT" | "SIGNED";
  billed_amount: number;
  recommended_amount: number | null;
  line_adjustments: LineAdjustment[];
  findings: FindingView[];
  guideline_refs: string[];
  next_action: string | null;
  reviewer: { name: string; specialty: string | null; signed_at: string } | null;
  explanation_text: string | null;
  quality_flags: { code: string; message: string }[];
  model_version: string;
  prompt_version: string;
  ruleset_version: string;
  insurer_decision: { decision: "AGREE" | "DIFFER"; reason: string | null; decided_by: string; decided_at: string } | null;
  label: string;
}

export interface BatchResult {
  created: number;
  failed: number;
  rows: { row: number; folder: string | null; claim_number: string | null; ok: boolean; claim_id: string | null; documents: number; reason: string | null }[];
}

// --- Ruang kerja dokter (M7) ---

export type FinalRecommendation = "PAY_FULL" | "PAY_PARTIAL" | "PEND" | "NOT_COVERED";

export interface QueueItem {
  id: string;
  claim_number: string;
  hospital_name: string;
  admission_date: string;
  discharge_date: string;
  billed_amount: number;
  primary_icd10: string | null;
  diagnosis_name: string | null;
  status: ClaimStatus;
  triage_status: Triage | null;
  risk_score: number | null;
  findings: number;
  level: "GP" | "SPECIALIST";
  specialty: string | null;
  escalated: boolean;
  assigned_to: string | null;
  assigned_to_me: boolean;
  waiting_since: string;
  signed_by: string | null;
  signed_at: string | null;
}

export interface ReviewField {
  id: string;
  field_path: string;
  label: string | null;
  kind: string | null;
  value: unknown;
  source: string;
  confidence: number | null;
  status: string | null;
  evidence: Evidence[];
  corrected_value: unknown;
  corrected: boolean;
  corrected_by: string | null;
  corrected_at: string | null;
}

export interface FieldHistory {
  field_path: string;
  old: unknown;
  new: unknown;
  note: string | null;
  by: string | null;
  at: string;
}

export interface ReviewInfo {
  id: string;
  doctor: string;
  doctor_specialty: string | null;
  action: string | null;
  reason_code: string | null;
  agrees_with_ai: boolean | null;
  escalated_specialty: string | null;
  notes: string | null;
  started_at: string;
  finished_at: string | null;
  duration_seconds: number | null;
}

export interface Workspace {
  claim: ClaimDetail;
  level: "GP" | "SPECIALIST";
  specialty: string | null;
  diagnosis_name: string | null;
  escalated: boolean;
  assigned_to: string | null;
  can_start: boolean;
  blocked_reason: string | null;
  my_review: ReviewInfo | null;
  reviews: ReviewInfo[];
  draft: Recommendation | null;
  suggestion: { recommendation: FinalRecommendation; recommended_amount: number | null } | null;
  fields: ReviewField[];
  field_history: FieldHistory[];
  reason_codes: Record<string, string>;
}

export interface RulesetRule {
  id: string;
  name: string;
  reason_code: string;
  severity: string;
  needs_ai: boolean;
  reference: string | null;
}

export interface RulesetInfo {
  version: string;
  status: string | null;
  path: string;
  general_rules: RulesetRule[];
  diagnoses: { id: string; name: string; icd10: string[]; specialty: string | null; rules: RulesetRule[] }[];
  triage: { jika: string; status: Triage; rekomendasi_awal: string }[];
  reason_codes: Record<string, string>;
}

// --- Dashboard (M8) ---

export interface CountItem {
  key: string;
  label: string | null;
  count: number;
  amount: number | null;
}

export interface Dashboard {
  label: string;
  total_claims: number;
  by_status: CountItem[];
  by_triage: CountItem[];
  by_recommendation: CountItem[];
  awaiting_doctor: number;
  billed_total: number;
  recommended_total: number;
  correction_total: number;
  top_findings: CountItem[];
  top_hospitals: CountItem[];
  avg_processing_seconds: number | null;
  decisions: CountItem[];
  doctor_reviews: number;
  doctor_agreement_pct: number | null;
  avg_review_seconds: number | null;
}
