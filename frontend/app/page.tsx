"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { AnalysisResultView, AnalysisState } from "./analysis-view";
import type { AnalysisResult, DocumentSummary, DocumentType, ExecutionMode } from "./types";
import { readResponse, readAnalysisStream, requestError } from './api';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8001";
const DEFAULT_QUESTION = "이 보고서를 읽고 주식 초보자 관점에서 호재와 악재를 각각 최대 3개까지 요약해줘.";

export default function Home() {
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [question, setQuestion] = useState(DEFAULT_QUESTION);
  const [executionMode, setExecutionMode] = useState<ExecutionMode>('LOCAL_ONLY');
  const [consentScope, setConsentScope] = useState<string | null>(null);
  const scope = JSON.stringify([selectedId, question, executionMode]);
  const externalConsent = consentScope === scope;
  const [options, setOptions] = useState({ external_enabled: false, fallback_enabled: false, local_model: 'gemma3:4b', external_model: 'Gemini' });
  const [stage, setStage] = useState('retrieving');
  const [activeProvider, setActiveProvider] = useState<string | null>(null);
  const [fallbackOccurred, setFallbackOccurred] = useState(false);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [listLoading, setListLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [embeddingBusy, setEmbeddingBusy] = useState(false);
  const [embeddingError, setEmbeddingError] = useState<string | null>(null);
  const [embedding, setEmbedding] = useState<{ embedding_status: string; embedded_chunk_count: number; total_chunk_count: number } | null>(null);
  const selected = useMemo(() => documents.find((item) => item.id === selectedId) ?? null, [documents, selectedId]);

  useEffect(() => {
    let active = true;
    void fetch(`${API_BASE}/api/v1/documents`).then(async (response) => {
      const body = await readResponse(response);
      if (active) setDocuments(body.items);
    }).catch((reason: unknown) => {
      if (active) setError(requestError(reason));
    }).finally(() => { if (active) setListLoading(false); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    let active = true;
    void fetch(`${API_BASE}/api/v1/analysis-options`).then(readResponse).then(body => {
      if (active) setOptions(body);
    }).catch(() => { /* Fail closed: external modes stay disabled. */ });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    let active = true;
    if (!selectedId) return;
    const update = async () => {
      try {
        const state = await readResponse(await fetch(`${API_BASE}/api/v1/documents/${selectedId}/embedding-status`));
        if (active) {
          setEmbedding(state); setEmbeddingError(null);
          if (state.embedding_status === 'completed' && timer) clearInterval(timer);
        }
      } catch (reason) { if (active) setEmbeddingError(requestError(reason)); }
    };
    void update();
    const timer = setInterval(() => { void update(); }, 3000);
    return () => { active = false; clearInterval(timer); };
  }, [selectedId, embeddingBusy]);

  async function uploadDocument(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    setUploading(true); setError(null);
    try {
      const uploaded = await readResponse(await fetch(`${API_BASE}/api/v1/documents`, { method: 'POST', body: new FormData(form) }));
      const list = await readResponse(await fetch(`${API_BASE}/api/v1/documents`));
      setDocuments(list.items);
      if (uploaded.document_id !== selectedId) { setEmbedding(null); setEmbeddingError(null); }
      setSelectedId(uploaded.document_id); setResult(null); setConsentScope(null); form.reset();
    } catch (reason) { setError(requestError(reason)); }
    finally { setUploading(false); }
  }

  async function createEmbeddings() {
    setEmbeddingBusy(true); setError(null);
    try {
      await readResponse(await fetch(`${API_BASE}/api/v1/documents/${selectedId}/embeddings`, {method:'POST'}));
      setEmbedding(await readResponse(await fetch(`${API_BASE}/api/v1/documents/${selectedId}/embedding-status`)));
    } catch (reason) { setError(requestError(reason)); }
    finally { setEmbeddingBusy(false); }
  }

  async function patchMetadata(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!selected) return;
    const form = new FormData(event.currentTarget); const stockCode = String(form.get("stock_code") ?? "").trim();
    const payload = { company_name: String(form.get("company_name") ?? "").trim(), stock_code: stockCode || null,
      document_type: form.get("document_type") as DocumentType, issuer: String(form.get("issuer") ?? "").trim(), published_at: String(form.get("published_at") ?? "") };
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/api/v1/documents/${selected.id}/metadata`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      const body = await readResponse(response);
      setDocuments((items) => items.map((item) => item.id === body.id ? body : item));
      setConsentScope(null);
    } catch (reason) { setError(requestError(reason)); }
  }

  async function runAnalysis() {
    setResult(null); setError(null); if (!selectedId) { setError("분석할 문서를 먼저 선택하세요."); return; }
    if (executionMode !== 'LOCAL_ONLY' && !externalConsent) { setError('이번 문서와 질문의 외부 전송에 동의해야 합니다.'); return; }
    setLoading(true); setStage('retrieving'); setActiveProvider(null); setFallbackOccurred(false);
    const body = { document_id: selectedId, question, top_k: 10, execution_mode: executionMode,
      external_consent: executionMode !== 'LOCAL_ONLY' && externalConsent };
    setConsentScope(null);
    try {
      const response = await fetch(`${API_BASE}/api/v1/analyses/stream`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      setResult(await readAnalysisStream(response, (nextStage, provider) => {
        setStage(nextStage); setActiveProvider(provider);
        if (nextStage === 'fallback') setFallbackOccurred(true);
      }));
    } catch (reason) { setError(requestError(reason)); }
    finally { setLoading(false); }
  }

  async function loadSavedAnalysis() {
    setError(null);
    try {
      setResult(await readResponse(await fetch(`${API_BASE}/api/v1/documents/${selectedId}/analyses/latest`)));
    } catch (reason) { setError(requestError(reason)); }
  }

  return <main className="min-h-screen px-4 py-8 sm:px-8 lg:py-12"><div className="mx-auto max-w-6xl">
    <header className="rounded-3xl bg-slate-950 px-7 py-10 text-white shadow-xl sm:px-12">
      <p className="text-sm font-bold uppercase tracking-[0.22em] text-blue-300">Stock Brief AI</p><h1 className="mt-4 text-3xl font-bold tracking-tight sm:text-5xl">공시·리포트 근거 기반 초보자용 기업 분석</h1>
      <p className="mt-5 max-w-3xl leading-7 text-slate-300">업로드한 PDF의 검색 근거만 사용하고, 모든 호재·악재에 원문 페이지와 인용문을 연결합니다.</p><div className="mt-6 inline-flex rounded-full bg-amber-300 px-4 py-2 text-sm font-extrabold text-slate-950">투자 권유 아님</div>
    </header>
    <div className="mt-8 grid gap-6 lg:grid-cols-[0.9fr_1.1fr]">
      <section className="panel"><h2 className="section-title">1. 문서 선택</h2>
        <details className="mt-4"><summary className="cursor-pointer font-bold">PDF 업로드</summary><form className="mt-3 space-y-3" onSubmit={uploadDocument}>
          <label className="label">PDF<input className="field" type="file" name="file" accept="application/pdf" required /></label>
          <label className="label">기업명<input className="field" name="company_name" required /></label>
          <label className="label">종목코드<input className="field" name="stock_code" pattern="[0-9]{6}" required /></label>
          <label className="label">발행기관<input className="field" name="issuer" required /></label>
          <label className="label">발행일<input className="field" type="date" name="published_at" required /></label>
          <label className="label">문서 유형<select className="field" name="document_type"><option value="broker_report">증권사 리포트</option><option value="dart_filing">DART 공시</option></select></label>
          <button className="secondary-button" disabled={uploading} type="submit">{uploading ? '업로드·문서 처리 중…' : 'PDF 업로드'}</button>
          {uploading && <p role="status">PDF 업로드 및 텍스트 추출/OCR을 처리하고 있습니다. 완료 후 문서가 표시됩니다.</p>}
        </form></details>
        {listLoading ? <p className="mt-4 text-slate-500">문서 목록을 불러오는 중…</p> : documents.length ? <select aria-label="분석 문서" className="field mt-4" value={selectedId} disabled={loading} onChange={(event) => { setSelectedId(event.target.value); setConsentScope(null); setEmbedding(null); setEmbeddingError(null); setResult(null); setError(null); }}><option value="">문서를 선택하세요</option>{documents.map((document) => <option key={document.id} value={document.id}>{document.company_name} · {document.issuer} · {document.published_at} · {document.document_type === "broker_report" ? "증권사 리포트" : "DART 공시"}</option>)}</select> : <p className="mt-4 text-slate-600">업로드된 문서가 없습니다. 먼저 Swagger의 문서 업로드 API를 사용하세요.</p>}
        {selected && <form key={selected.id} className="mt-6 border-t border-slate-200 pt-6" onSubmit={patchMetadata}><h3 className="font-bold">문서 메타데이터 수정</h3><div className="mt-4 grid gap-3 sm:grid-cols-2">
          <label className="label">기업명<input className="field" name="company_name" defaultValue={selected.company_name} required /></label><label className="label">종목코드<input className="field" name="stock_code" defaultValue={selected.stock_code ?? ""} pattern="[0-9]{6}" placeholder="6자리 숫자" /></label>
          <label className="label">발행기관<input className="field" name="issuer" defaultValue={selected.issuer} required /></label><label className="label">발행일<input className="field" type="date" name="published_at" defaultValue={selected.published_at} required /></label>
          <label className="label sm:col-span-2">문서 유형<select className="field" name="document_type" defaultValue={selected.document_type}><option value="broker_report">증권사 리포트</option><option value="dart_filing">DART 공시</option></select></label>
        </div><button className="secondary-button mt-4" type="submit">메타데이터 저장</button></form>}
      </section>
      <section className="panel"><h2 className="section-title">2. 근거 기반 질문</h2><label className="label mt-4">질문<textarea className="field min-h-36 resize-y" value={question} disabled={loading} onChange={(event) => { setQuestion(event.target.value); setConsentScope(null); }} /></label>
        {embeddingError && <p role="alert" className="text-red-800">{embeddingError}</p>}
        {selected && <button className="secondary-button mt-3" type="button" disabled={loading} onClick={loadSavedAnalysis}>최근 저장된 분석 보기</button>}
        {selected && <div className="mt-4 text-sm" role="status">문서: {selected.status === 'processing' ? '텍스트 추출/OCR 처리 중' : selected.status === 'failed' ? '처리 실패' : '텍스트 추출 완료'} · {embedding?.embedding_status === 'completed' ? '분석 준비 완료' : embedding?.embedding_status === 'failed' ? '임베딩 실패' : embeddingBusy || embedding?.embedding_status === 'processing' ? '임베딩 생성 중' : '임베딩 필요'} {embedding && `(${embedding.embedded_chunk_count}/${embedding.total_chunk_count})`}</div>}
        {selected && embedding?.embedding_status !== 'completed' && <button className="secondary-button mt-3" type="button" disabled={embeddingBusy || selected.status === 'processing' || selected.status === 'failed'} onClick={createEmbeddings}>{embeddingBusy ? '임베딩 생성 중…' : '임베딩 생성 / 누락분 재시도'}</button>}
        <label className="label mt-4">분석 실행 방식<select aria-label="분석 실행 방식" className="field" value={executionMode} disabled={loading} onChange={event => { setExecutionMode(event.target.value as ExecutionMode); setConsentScope(null); }}>
          <option value="LOCAL_ONLY">로컬 분석 · {options.local_model}</option>
          <option value="EXTERNAL_WITH_CONSENT" disabled={!options.external_enabled}>외부 분석 · {options.external_model} · 요청별 동의</option>
          <option value="FALLBACK_ALLOWED" disabled={!options.fallback_enabled}>외부 분석 후 실패 시 로컬 fallback · 요청별 동의</option>
        </select></label>
        {!options.external_enabled && <p className="mt-2 text-sm text-slate-500">서버 정책에서 외부 분석을 허용하지 않았습니다.</p>}
        {executionMode !== 'LOCAL_ONLY' && <div className="state-box mt-3">
          <p>이번 질문, 문서의 기업명·종목코드·유형·발행기관·발행일, 검색된 검증 근거의 원문 발췌·페이지·청크 ID·수치·기간·단위·범위, 분석 지시문과 출력 형식을 Google Gemini 서버로 전송합니다. PDF 파일·이미지·전체 provenance·embedding은 전송하지 않습니다.</p>
          <label className="mt-3 flex gap-2"><input type="checkbox" aria-label="이번 분석의 Gemini 전송에 동의" checked={externalConsent} disabled={loading} onChange={event => setConsentScope(event.target.checked ? scope : null)} />이번 문서·질문의 분석 요청 1회와 설정된 재시도에 동의합니다.{executionMode === 'FALLBACK_ALLOWED' ? ' Gemini 일시 오류 시 동일 근거의 로컬 fallback도 허용합니다.' : ''}</label>
        </div>}
        <button className="primary-button mt-5" type="button" disabled={loading || !question.trim() || embedding?.embedding_status !== 'completed' || (executionMode !== 'LOCAL_ONLY' && !externalConsent)} onClick={runAnalysis}>{loading ? "분석 중…" : "분석하기"}</button><p className="mt-4 text-sm leading-6 text-slate-500">완료된 OCR과 임베딩은 같은 문서를 다시 분석할 때 재사용합니다.</p>
      </section>
    </div><AnalysisState loading={loading} error={error} stage={stage} provider={activeProvider} fallback={fallbackOccurred} /><AnalysisResultView result={result} documentId={selectedId} />
  </div></main>;
}
