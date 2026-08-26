import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AnalysisResultView, AnalysisState } from "./analysis-view";
import type { AnalysisResult } from "./types";

const result: AnalysisResult = {
  analysis_status: "completed", generation_model: "gemma3:4b", generated_at: "2026-08-23T00:00:00Z",
  summary: "검색된 근거에 한정한 핵심 요약입니다.",
  positives: [{ title: "근거가 있는 호재", reason: "증권사 전망에 따른 쉬운 설명입니다.", evidence_chunk_ids: ["chunk-1"], interpretation_label: "증권사 리포트 해석" }],
  negatives: [], citations: [{ chunk_id: "chunk-1", filename: "report.pdf", company_name: "삼성전자", published_at: "2025-07-09", issuer: "한화리서치", document_type: "broker_report", page_number: 7, quote: "DB에서 복원한 원문 인용문" }],
  insufficient_evidence_note: null, disclaimer: "투자 권유가 아닙니다.",
};

describe("analysis states", () => {
  it("renders loading state", () => { render(<AnalysisState loading error={null} />); expect(screen.getByRole("status")).toHaveTextContent("검토"); });
  it("renders error state", () => { render(<AnalysisState loading={false} error="Ollama 서버 오류" />); expect(screen.getByRole("alert")).toHaveTextContent("Ollama 서버 오류"); });
  it("renders successful grounded result", () => {
    render(<AnalysisResultView result={result} documentId="document-1" />);
    expect(screen.getByText("검색된 근거에 한정한 핵심 요약입니다.")).toBeInTheDocument();
    expect(screen.getByText("증권사 리포트 해석")).toBeInTheDocument();
    expect(screen.getByText("report.pdf")).toBeInTheDocument();
    expect(screen.getByText("PDF 7페이지")).toBeInTheDocument();
    expect(screen.getByText("DB에서 복원한 원문 인용문")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "원문 PDF 7페이지 보기" })).toHaveAttribute("href",
      "http://localhost:8001/api/v1/documents/document-1/file?page_number=7#page=7");
  });
  it("hides raw numeric table fragments and shows the page guidance", () => {
    const tableResult = { ...result, citations: [{ ...result.citations[0], display_kind: "table" as const,
      display_quote: null, table_labels: [], display_note: "표 수치는 원문 PDF 3페이지에서 확인할 수 있습니다.",
      page_number: 3, quote: "영업이익 53.7 89.2 117.2 Foundry/LS -1.4 -2.2 -0.9" }] };
    render(<AnalysisResultView result={tableResult} documentId="document-1" />);
    expect(screen.queryByText(/53\.7 89\.2/)).not.toBeInTheDocument();
    expect(screen.getByText("표 수치는 원문 PDF 3페이지에서 확인할 수 있습니다.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "원문 PDF 3페이지 보기" })).toHaveAttribute("href",
      "http://localhost:8001/api/v1/documents/document-1/file?page_number=3#page=3");
  });
  it("renders verified table facts as an accessible key figures card", () => {
    const tableResult = { ...result, citations: [{ ...result.citations[0], citation_type: "table" as const,
      display_kind: "table" as const, display_quote: null, display_note: null, page_number: 3,
      quote: "Foundry/LS -7.6 -5.1 -2.8", table_facts: { table_title: null, metric: "영업이익",
        row_label: "Foundry/LS", unit: "조원", values: [{ period: "2025", value: "-7.6" },
          { period: "2026F", value: "-5.1" }, { period: "2027F", value: "-2.8" }],
        interpretation: "보고서는 Foundry/LS 부문의 영업적자가 이어질 것으로 제시합니다." } }] };
    render(<AnalysisResultView result={tableResult} documentId="document-1" />);
    expect(screen.getByLabelText("핵심 수치")).toHaveTextContent("Foundry/LS 영업이익");
    expect(screen.getByLabelText("핵심 수치")).toHaveTextContent("2026년 전망-5.1");
    expect(screen.getByText(/보고서는 Foundry\/LS 부문의 영업적자가/)).toBeInTheDocument();
    expect(screen.queryByText("Foundry/LS -7.6 -5.1 -2.8")).not.toBeInTheDocument();
  });
  it("renders insufficient evidence without filling items", () => {
    render(<AnalysisResultView result={{ ...result, analysis_status: "insufficient_evidence", summary: "확인할 수 없습니다", positives: [], citations: [], insufficient_evidence_note: "근거가 부족해 추가 항목을 제시하지 않았습니다." }} />);
    expect(screen.getByText("확인할 수 없습니다")).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent("추가 항목을 제시하지 않았습니다");
    expect(screen.getByText("확인된 호재 근거가 없습니다.")).toBeInTheDocument();
  });
});
