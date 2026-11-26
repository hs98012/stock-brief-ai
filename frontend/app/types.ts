export type DocumentType = "broker_report" | "dart_filing";

export type DocumentSummary = {
  id: string; company_name: string; stock_code: string | null; document_type: DocumentType;
  issuer: string; published_at: string; filename: string; status: string; total_pages: number | null;
};

export type Citation = {
  chunk_id: string; filename: string; company_name: string; published_at: string; issuer: string;
  document_type: DocumentType; page_number: number; quote: string;
  display_kind?: "text" | "table" | "table_fallback"; display_quote?: string | null; table_labels?: string[];
  citation_type?: "text" | "table" | "table_fallback"; display_note?: string | null;
  source_boxes?: number[][]; page_size?: number[] | null; coordinate_system?: "unrotated_pdf_points" | null;
  table_facts?: { table_title: string | null; metric: string; row_label: string; unit: string;
    values: { period: string; value: string }[]; interpretation: string | null } | null;
};

export type AnalysisItem = {
  title: string; reason: string; evidence_chunk_ids: string[]; interpretation_label: string;
};

export type AnalysisResult = {
  execution?: { requested_mode: ExecutionMode; external_consent: boolean; external_request_attempted: boolean;
    final_provider: 'ollama' | 'gemini' | null; fallback_used: boolean } | null;
  run_id?: string | null; requirement_status?: string | null; coverage_complete?: boolean | null;
  analysis_status: string; generation_model: string | null; generated_at: string; summary: string;
  positives: AnalysisItem[]; negatives: AnalysisItem[]; citations: Citation[];
  positive_empty_state?: PolarityEmptyState | null; negative_empty_state?: PolarityEmptyState | null;
  insufficient_evidence_note: string | null; disclaimer: string;
};

export type PolarityEmptyState = {
  reason: "no_evidence" | "extraction_limited"; message: string; page_number: number | null;
};

export type ExecutionMode = 'LOCAL_ONLY' | 'EXTERNAL_WITH_CONSENT' | 'FALLBACK_ALLOWED';
