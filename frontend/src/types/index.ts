export type AnalysisStatus = "queued" | "running" | "completed" | "failed";
export type AIEnrichmentStatus = "not_started" | "running" | "completed" | "partial" | "failed";

export interface ProjectAnalysisCreated {
  project_id: string;
  analysis_id: string;
  status: AnalysisStatus;
}

export interface AnalysisErrorDetails {
  code: string;
  message: string;
}

export interface AnalysisStatusResponse {
  analysis_id: string;
  project_id: string;
  status: AnalysisStatus;
  progress: number;
  current_stage: string;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
  error_details: AnalysisErrorDetails | null;
  ai_enrichment_status: AIEnrichmentStatus;
  ai_enrichment_progress: number;
  ai_enrichment_error: AnalysisErrorDetails | null;
}

export type FindingCategory =
  | "overview" | "completed" | "ongoing" | "unfinished"
  | "technical_decision" | "contributor" | "risk" | "knowledge_gap";
export type ClaimType = "fact" | "inference" | "unknown";
export type EvidenceStatus = "source_verified" | "partially_verified" | "insufficient" | "not_applicable";
export type Timeframe = "first_2_hours" | "first_8_hours" | "first_24_hours" | "first_48_hours";

export interface Finding {
  finding_id: string;
  category: FindingCategory;
  title: string;
  description: string;
  claim_type: ClaimType;
  evidence_status: EvidenceStatus;
  confidence: number;
  evidence_ids: string[];
  recommended_next_action: string | null;
}

export interface EvidenceReference {
  evidence_id: string;
  evidence_type: string;
  source_identifier: string;
  source_url: string;
  retrieved_at: string;
  repository_commit_sha: string | null;
}

export interface EvidenceDetail extends EvidenceReference {
  content: string;
  related_finding_ids: string[];
}

export interface OnboardingTask {
  task_id: string;
  timeframe: Timeframe;
  title: string;
  reason: string;
  priority: "high" | "medium" | "low";
  finding_ids: string[];
  evidence_ids: string[];
}

export interface AnalysisResults {
  analysis_id: string;
  project_id: string;
  findings: Finding[];
  evidence_references: EvidenceReference[];
  first_48_hours_plan: OnboardingTask[];
}

export interface AIEnrichmentItem {
  enrichment_id: string;
  category: "project_understanding" | "technical_decision" | "work_status" | "risk" | "knowledge_gap" | "plan";
  title: string;
  explanation: string;
  claim_type: ClaimType;
  evidence_status: "source_verified" | "partially_verified" | "insufficient";
  confidence: number;
  evidence_ids: string[];
  related_finding_ids: string[];
  plan_task_ids: string[];
  recommended_action: string | null;
  human_review_status: "needs_review";
}

export interface AIEnrichmentResponse {
  analysis_id: string;
  status: AIEnrichmentStatus;
  progress: number;
  items: AIEnrichmentItem[];
  rejected_item_count: number;
  error_details: AnalysisErrorDetails | null;
}
