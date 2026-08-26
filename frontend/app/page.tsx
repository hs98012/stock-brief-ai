"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { AnalysisResultView, AnalysisState } from "./analysis-view";
import type { AnalysisResult, DocumentSummary, DocumentType } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8001";
const DEFAULT_QUESTION = "이 보고서를 읽고 주식 초보자 관점에서 호재와 악재를 각각 최대 3개까지 요약해줘.";

function errorText(body: unknown, fallback: string) {
  if (typeof body === "object" && body && "detail" in body && typeof body.detail === "string") return body.detail;
  return fallback;
}

export default function Home() {
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [question, setQuestion] = useState(DEFAULT_QUESTION);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [listLoading, setListLoading] = useState(true);
  const selected = useMemo(() => documents.find((item) => item.id === selectedId) ?? null, [documents, selectedId]);

  useEffect(() => {
    let active = true;
    void fetch(`${API_BASE}/api/v1/documents`).then(async (response) => {
      const body = await response.json();
      if (!response.ok) throw new Error(errorText(body, "문서 목록을 불러오지 못했습니다."));
      if (active) setDocuments(body.items);
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : "백엔드에 연결할 수 없습니다.");
    }).finally(() => { if (active) setListLoading(false); });
    return () => { active = false; };
  }, []);

  async function patchMetadata(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!selected) return;
    const form = new FormData(event.currentTarget); const stockCode = String(form.get("stock_code") ?? "").trim();
    const payload = { company_name: String(form.get("company_name") ?? "").trim(), stock_code: stockCode || null,
      document_type: form.get("document_type") as DocumentType, issuer: String(form.get("issuer") ?? "").trim(), published_at: String(form.get("published_at") ?? "") };
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/api/v1/documents/${selected.id}/metadata`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      const body = await response.json(); if (!response.ok) throw new Error(errorText(body, "메타데이터 수정에 실패했습니다."));
      setDocuments((items) => items.map((item) => item.id === body.id ? body : item));
    } catch (reason) { setError(reason instanceof Error ? reason.message : "메타데이터 수정에 실패했습니다."); }
  }

  async function runAnalysis() {
    setResult(null); setError(null); if (!selectedId) { setError("분석할 문서를 먼저 선택하세요."); return; }
    setLoading(true);
    try {
      const response = await fetch(`${API_BASE}/api/v1/analyses`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ document_id: selectedId, question, top_k: 10 }) });
      const body = await response.json(); if (!response.ok) throw new Error(errorText(body, "분석을 실행하지 못했습니다.")); setResult(body);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "분석을 실행하지 못했습니다."); }
    finally { setLoading(false); }
  }

  return <main className="min-h-screen px-4 py-8 sm:px-8 lg:py-12"><div className="mx-auto max-w-6xl">
    <header className="rounded-3xl bg-slate-950 px-7 py-10 text-white shadow-xl sm:px-12">
      <p className="text-sm font-bold uppercase tracking-[0.22em] text-blue-300">Stock Brief AI</p><h1 className="mt-4 text-3xl font-bold tracking-tight sm:text-5xl">공시·리포트 근거 기반 초보자용 기업 분석</h1>
      <p className="mt-5 max-w-3xl leading-7 text-slate-300">업로드한 PDF의 검색 근거만 사용하고, 모든 호재·악재에 원문 페이지와 인용문을 연결합니다.</p><div className="mt-6 inline-flex rounded-full bg-amber-300 px-4 py-2 text-sm font-extrabold text-slate-950">투자 권유 아님</div>
    </header>
    <div className="mt-8 grid gap-6 lg:grid-cols-[0.9fr_1.1fr]">
      <section className="panel"><h2 className="section-title">1. 문서 선택</h2>
        {listLoading ? <p className="mt-4 text-slate-500">문서 목록을 불러오는 중…</p> : documents.length ? <select aria-label="분석 문서" className="field mt-4" value={selectedId} onChange={(event) => { setSelectedId(event.target.value); setResult(null); setError(null); }}><option value="">문서를 선택하세요</option>{documents.map((document) => <option key={document.id} value={document.id}>{document.company_name} · {document.issuer} · {document.published_at} · {document.document_type === "broker_report" ? "증권사 리포트" : "DART 공시"}</option>)}</select> : <p className="mt-4 text-slate-600">업로드된 문서가 없습니다. 먼저 Swagger의 문서 업로드 API를 사용하세요.</p>}
        {selected && <form key={selected.id} className="mt-6 border-t border-slate-200 pt-6" onSubmit={patchMetadata}><h3 className="font-bold">문서 메타데이터 수정</h3><div className="mt-4 grid gap-3 sm:grid-cols-2">
          <label className="label">기업명<input className="field" name="company_name" defaultValue={selected.company_name} required /></label><label className="label">종목코드<input className="field" name="stock_code" defaultValue={selected.stock_code ?? ""} pattern="[0-9]{6}" placeholder="6자리 숫자" /></label>
          <label className="label">발행기관<input className="field" name="issuer" defaultValue={selected.issuer} required /></label><label className="label">발행일<input className="field" type="date" name="published_at" defaultValue={selected.published_at} required /></label>
          <label className="label sm:col-span-2">문서 유형<select className="field" name="document_type" defaultValue={selected.document_type}><option value="broker_report">증권사 리포트</option><option value="dart_filing">DART 공시</option></select></label>
        </div><button className="secondary-button mt-4" type="submit">메타데이터 저장</button></form>}
      </section>
      <section className="panel"><h2 className="section-title">2. 근거 기반 질문</h2><label className="label mt-4">질문<textarea className="field min-h-36 resize-y" value={question} onChange={(event) => setQuestion(event.target.value)} /></label>
        <button className="primary-button mt-5" type="button" disabled={loading || !question.trim()} onClick={runAnalysis}>{loading ? "분석 중…" : "분석하기"}</button><p className="mt-4 text-sm leading-6 text-slate-500">임베딩이 생성된 문서만 분석할 수 있습니다. Ollama에서 bge-m3와 gemma3:4b가 실행 가능해야 합니다.</p>
      </section>
    </div><AnalysisState loading={loading} error={error} /><AnalysisResultView result={result} documentId={selectedId} />
  </div></main>;
}
