export type DocumentType = "broker_report" | "dart_filing";

export type DocumentSummary = {
  id: string; company_name: string; stock_code: string | null; document_type: DocumentType;
  issuer: string; published_at: string; filename: string; status: string; total_pages: number | null;
};

export type Citation = {
  chunk_id: string; filename: string; company_name: string; published_at: string; issuer: string;
  document_type: DocumentType; page_number: number; quote: string;
  display_kind?: "text" | "table"; display_quote?: string | null; table_labels?: string[];
  citation_type?: "text" | "table"; display_note?: string | null;
  table_facts?: { table_title: string | null; metric: string; row_label: string; unit: string;
    values: { period: string; value: string }[]; interpretation: string | null } | null;
};

export type AnalysisItem = {
  title: string; reason: string; evidence_chunk_ids: string[]; interpretation_label: string;
};

export type AnalysisResult = {
  analysis_status: string; generation_model: string | null; generated_at: string; summary: string;
  positives: AnalysisItem[]; negatives: AnalysisItem[]; citations: Citation[];
  insufficient_evidence_note: string | null; disclaimer: string;
};
