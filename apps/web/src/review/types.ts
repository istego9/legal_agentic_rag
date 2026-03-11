export type ReviewEvidenceRef = {
  doc_id: string;
  doc_title?: string | null;
  page_number: number;
  snippet?: string | null;
  paragraph_id?: string | null;
  is_used?: boolean | null;
  source_origin?: string | null;
  highlight_offsets?: number[];
  source_page_id?: string | null;
  parse_warnings?: string[];
};

export type ReviewCandidate = {
  candidate_id: string;
  candidate_kind: "system" | "strong_model" | "challenger" | "mini_check";
  answer: unknown;
  answerability: "answerable" | "abstain";
  confidence?: number | null;
  reasoning_summary?: string | null;
  sources: ReviewEvidenceRef[];
  support_status?: string | null;
  run_id?: string | null;
  created_at?: string | null;
  label?: string | null;
  unavailable_reason?: string | null;
  metadata?: Record<string, unknown>;
};

export type ReviewDecision = {
  final_answer: unknown;
  final_sources: ReviewEvidenceRef[];
  answerability?: "answerable" | "abstain" | null;
  decision_source?: string | null;
  reviewer?: string | null;
  reviewer_confidence?: number | null;
  adjudication_note?: string | null;
  locked_at?: string | null;
  updated_at?: string | null;
  gold_dataset_id?: string | null;
  gold_question_id?: string | null;
};

export type MiniCheckResult = {
  verdict: "supported" | "not_supported" | "insufficient_evidence";
  extracted_answer: unknown;
  confidence: number;
  rationale: string;
  conflict_type: string;
  candidate_answer?: unknown;
  candidate_kind?: string | null;
  created_at?: string | null;
  model_name?: string | null;
  unavailable_reason?: string | null;
};

export type ReviewRecord = {
  question_id: string;
  question: string;
  answer_type: string;
  primary_route?: string | null;
  document_scope?: string | null;
  risk_tier?: string | null;
  status: string;
  disagreement_flags: string[];
  current_run_id?: string | null;
  trace_id?: string | null;
  candidate_bundle: ReviewCandidate[];
  accepted_decision?: ReviewDecision | null;
  mini_check_result?: MiniCheckResult | null;
  report_summary?: Record<string, unknown>;
  question_metadata?: Record<string, unknown>;
  evidence?: Record<string, unknown>;
  document_viewer?: Record<string, unknown>;
  promotion_preview?: Record<string, unknown>;
  comparison_context?: Record<string, unknown>;
  created_at?: string | null;
  updated_at?: string | null;
};

export type ReviewSummary = {
  run_id: string;
  total_questions: number;
  auto_lock_candidates: number;
  locked_gold_count: number;
  needs_review_count: number;
  disagreement_histogram: Record<string, number>;
  answerability_conflict_count: number;
  source_conflict_count: number;
  mini_check_failure_count: number;
  route_breakdown: Record<string, number>;
  answer_type_breakdown: Record<string, number>;
  exported_at?: string | null;
};

export type ReviewPdfPreview = {
  run_id: string;
  question_id: string;
  document_id: string;
  title: string;
  pdf_id: string;
  file_url: string;
  page: {
    page_id: string;
    page_num: number;
    source_page_id: string;
    used: boolean;
    chunk_text: string;
    page_text: string;
    parse_warnings: string[];
  };
  fallback: {
    doc_id: string;
    page_number: number;
    text: string;
    parse_warnings: string[];
  };
};

export type ReviewFilters = {
  route: string;
  answer_type: string;
  status: string;
  disagreement_only: boolean;
  needs_review_only: boolean;
  gold_locked_only: boolean;
  no_answer_only: boolean;
  missing_sources_only: boolean;
  contract_failures_only: boolean;
  search: string;
};
