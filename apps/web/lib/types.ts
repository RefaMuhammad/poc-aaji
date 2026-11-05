export type Role =
  | "insurer_staff"
  | "insurer_manager"
  | "doctor_gp"
  | "doctor_specialist"
  | "admin"
  | "tpa_operator"
  | "auditor"
  | "facility_officer"
  | "member"
  | "underwriter";

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  insurer_id: string | null;
  specialty: string | null;
  facility_name?: string | null;
  member_ref?: string | null;
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
  insurer_id: string;
  insurer_name: string | null;
  source: ClaimSource;
  policy_id: string | null;
}

export type ClaimSource = "PORTAL" | "BATCH" | "API" | "SFTP" | "FHIR";

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
  policy: Policy | null;
}

export interface Evidence {
  doc: string | null;
  page: number | null;
  quote: string | null;
  bbox: number[] | null;
  field: string | null;
  claim_id: string | null;
  policy_number?: string | null;
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
  benefit_ruleset_version: string | null;
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
  insurer_name: string | null;
  sla_hours: number | null;
  sla_due_at: string | null;
  sla_state: "ON_TRACK" | "AT_RISK" | "OVERDUE" | null;
  sla_met: boolean | null;
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
  benefit: { version: string; path: string; rules: RulesetRule[] } | null;
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

// --- Tenant & akun layanan (U1) ---------------------------------------------------------

export interface Branding {
  insurer_id: string;
  code: string;
  name: string;
  display_name: string | null;
  logo_data_url: string | null;
  primary_color: string | null;
}

export interface TenantSettingsInput {
  display_name: string | null;
  logo_data_url: string | null;
  primary_color: string | null;
  triage_red_min_score: number | null;
  triage_yellow_min_score: number | null;
  disabled_rules: string[];
  sla_gp_hours: number;
  sla_specialist_hours: number;
  auto_assign: boolean;
  webhook_url: string | null;
  webhook_secret?: string | null;   // hanya dikirim; kosong = tidak diubah
}

export interface Tenant extends Branding, TenantSettingsInput {
  version: number;
  updated_at: string | null;
  default_red_min_score: number | null;
  default_yellow_min_score: number | null;
  effective_ruleset_version: string;
  claim_count: number;
  webhook_secret_set: boolean;
  policy_count: number;
}

export interface ApiClient {
  id: string;
  insurer_id: string;
  name: string;
  key_prefix: string;
  scopes: string[];
  is_active: boolean;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
  api_key?: string;
}

// --- U2: polis, benefit, integrasi -------------------------------------------------------

export interface BenefitPlan {
  id: string;
  insurer_id: string;
  code: string;
  name: string;
  room_class: string | null;
  room_rate_limit: number | null;
  annual_limit: number | null;
  waiting_period_days: number;
  excluded_icd10: string[];
  policy_count: number;
}

export interface Policy {
  id: string;
  insurer_id: string;
  policy_number: string;
  member_id: string;
  member_name: string | null;
  plan_code: string;
  plan_name: string;
  room_class: string | null;
  room_rate_limit: number | null;
  annual_limit: number | null;
  waiting_period_days: number;
  excluded_icd10: string[];
  start_date: string;
  end_date: string;
  status: "ACTIVE" | "LAPSED" | "TERMINATED";
  limit_used: number;
  limit_remaining: number | null;
  source: string;
  updated_at: string;
}

export interface PolicyImportResult {
  job_id: string;
  status: "SUCCESS" | "PARTIAL" | "FAILED";
  created: number;
  updated: number;
  errors: string[];
}

export interface IntegrationJob {
  id: string;
  insurer_id: string;
  channel: string;
  reference: string | null;
  status: "SUCCESS" | "PARTIAL" | "FAILED";
  summary: Record<string, unknown>;
  created_at: string;
}

export interface WebhookDelivery {
  id: string;
  insurer_id: string;
  event: string;
  claim_id: string | null;
  url: string;
  status: "PENDING" | "DELIVERED" | "FAILED";
  attempts: number;
  last_status_code: number | null;
  last_error: string | null;
  created_at: string;
  delivered_at: string | null;
  payload: Record<string, unknown>;
}

export interface ApiScope {
  scope: string;
  description: string;
}

// ----------------------------------------------------------------------------- U3 fraud analytics

export type FraudEntityType = "HOSPITAL" | "DOCTOR" | "MEMBER" | "BANK_ACCOUNT" | "ADDRESS" | "REFERRAL_LOOP";
export type FraudReviewStatus = "OPEN" | "INVESTIGATING" | "CONFIRMED" | "DISMISSED";

export interface FraudReview {
  status: Exclude<FraudReviewStatus, "OPEN">;
  notes: string | null;
  reviewed_by_id: string;
  reviewed_by_name: string | null;
  reviewed_at: string;
}

export interface FraudGraphNode {
  id: string;
  label: string;
  type: FraudEntityType | string;
  subject: boolean;
}

export interface FraudGraphEdge {
  source: string;
  target: string;
  label: string;
  count: number;
  directed: boolean;
}

export interface FraudEvidenceClaim {
  claim_number: string;
  member_id: string;
  hospital: string;
  doctor: string | null;
  icd10: string | null;
  admission_date: string;
  discharge_date: string;
  los_days: number;
  billed_amount: number;
  lab_panels: number | null;
  referral_from: string | null;
  value: number | null;
}

export interface FraudEvidence {
  kind?: "peer" | "relation" | "timeline";
  metric?: "los" | "cost" | "lab";
  comparison?: { label: string; unit: string; value: number | null; peer: number | null; index: number | null; z: number | null; peer_group: string }[];
  peer_distribution?: { name: string; claims: number; index: number | null; z: number | null; is_subject: boolean }[];
  relations?: { from: string; to: string; label: string }[];
  claims?: FraudEvidenceClaim[];
  graph?: { nodes: FraudGraphNode[]; edges: FraudGraphEdge[] };
  metrics?: Record<string, unknown>;
  claim_links?: Record<string, string>;
}

export interface FraudSignal {
  id: string;
  run_id: string;
  rule_id: string;
  rule_name: string | null;
  reason_code: string;
  reason_label: string | null;
  severity: "HIGH" | "MEDIUM" | "LOW" | "INFO";
  weight: number;
  entity_type: FraudEntityType;
  entity_key: string;
  entity_label: string;
  message: string;
  claim_count: number;
  claim_numbers: string[];
  evidence: FraudEvidence;
  review: FraudReview | null;
}

export interface FraudEntity {
  entity_type: FraudEntityType;
  entity_key: string;
  entity_label: string;
  score: number;
  level: string | null;
  rule_ids: string[];
  claims: number;
  review_statuses: FraudReviewStatus[];
}

export interface FraudRun {
  id: string;
  insurer_id: string;
  ruleset_version: string;
  record_count: number;
  signal_count: number;
  created_by_id: string | null;
  created_at: string;
}

export interface FraudOverview {
  insurer_id: string;
  ruleset_version: string;
  record_count: number;
  record_sources: Record<string, number>;
  last_run: FraudRun | null;
  stale: boolean;
  signals_open: number;
  signals_by_status: Partial<Record<FraudReviewStatus, number>>;
  entities: FraudEntity[];
}

export interface FraudImportResult {
  job_id: string;
  status: string;
  created: number;
  updated: number;
  errors: string[];
  run: FraudRun | null;
}

export interface FraudClaim {
  claim_id: string;
  ruleset_version: string | null;
  run_at: string | null;
  score: number;
  level: string | null;
  in_analysis: boolean;
  signals: FraudSignal[];
}

export interface FraudRule {
  id: string;
  name: string;
  entity: string;
  entity_type: FraudEntityType;
  condition: string;
  reason_code: string;
  severity: string;
  weight: number;
  message: string;
}

export interface FraudRuleset {
  version: string;
  params: Record<string, unknown>;
  reason_codes: Record<string, string>;
  rules: FraudRule[];
}
