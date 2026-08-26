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
    render(<AnalysisResultView result={result} />);
    expect(screen.getByText("검색된 근거에 한정한 핵심 요약입니다.")).toBeInTheDocument();
    expect(screen.getByText("증권사 리포트 해석")).toBeInTheDocument();
    expect(screen.getByText("report.pdf")).toBeInTheDocument();
    expect(screen.getByText("PDF 7페이지")).toBeInTheDocument();
    expect(screen.getByText("DB에서 복원한 원문 인용문")).toBeInTheDocument();
  });
  it("renders insufficient evidence without filling items", () => {
    render(<AnalysisResultView result={{ ...result, analysis_status: "insufficient_evidence", summary: "확인할 수 없습니다", positives: [], citations: [], insufficient_evidence_note: "근거가 부족해 추가 항목을 제시하지 않았습니다." }} />);
    expect(screen.getByText("확인할 수 없습니다")).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent("추가 항목을 제시하지 않았습니다");
    expect(screen.getByText("확인된 호재 근거가 없습니다.")).toBeInTheDocument();
  });
});
