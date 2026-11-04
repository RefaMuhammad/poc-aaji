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
