export type DocumentType = "broker_report" | "dart_filing";

export type DocumentSummary = {
  id: string; company_name: string; stock_code: string | null; document_type: DocumentType;
  issuer: string; published_at: string; filename: string; status: string; total_pages: number | null;
};

export type Citation = {
  chunk_id: string; filename: string; company_name: string; published_at: string; issuer: string;
  document_type: DocumentType; page_number: number; quote: string;
};

export type AnalysisItem = {
  title: string; reason: string; evidence_chunk_ids: string[]; interpretation_label: string;
};

export type AnalysisResult = {
  analysis_status: string; generation_model: string | null; generated_at: string; summary: string;
  positives: AnalysisItem[]; negatives: AnalysisItem[]; citations: Citation[];
  insufficient_evidence_note: string | null; disclaimer: string;
};

