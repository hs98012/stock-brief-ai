import type { AnalysisItem, AnalysisResult, Citation } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8001";

export function AnalysisState({ loading, error }: { loading: boolean; error: string | null }) {
  if (loading) return <div role="status" className="state-box">Ollama가 검색 근거를 검토하고 있습니다…</div>;
  if (error) return <div role="alert" className="state-box border-red-200 bg-red-50 text-red-800">{error}</div>;
  return null;
}

function SourceCard({ citation, documentId }: { citation: Citation; documentId: string }) {
  const isTable = (citation.citation_type ?? citation.display_kind) === "table";
  const displayQuote = citation.display_quote ?? (isTable ? null : citation.quote);
  const pdfUrl = `${API_BASE}/api/v1/documents/${encodeURIComponent(documentId)}/file?page_number=${citation.page_number}#page=${citation.page_number}`;
  return <article className="source-card">
    <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs font-semibold text-slate-600"><span>{citation.filename}</span><span>{citation.issuer}</span><span>{citation.published_at}</span><span>PDF {citation.page_number}페이지</span></div>
    <div className="mt-3 flex flex-wrap items-center justify-between gap-2"><p className="text-xs font-bold text-blue-700">{isTable ? "표 근거" : "관련 원문 발췌"}</p>
      <a className="text-xs font-bold text-blue-700 underline decoration-blue-300 underline-offset-4 hover:text-blue-900" href={pdfUrl} target="_blank" rel="noreferrer">원문 PDF {citation.page_number}페이지 보기</a></div>
    {isTable && citation.table_facts ? <div className="mt-3 rounded-xl border border-slate-200 bg-white p-4" aria-label="핵심 수치">
      <p className="text-sm font-extrabold text-slate-900">핵심 수치</p>
      {citation.table_facts.table_title ? <p className="mt-2 text-sm font-semibold text-slate-700">{citation.table_facts.table_title}</p> : null}
      <dl className="mt-3 grid grid-cols-[minmax(0,1fr)_auto] gap-x-4 gap-y-2 text-sm">
        <dt className="text-slate-500">항목</dt><dd className="text-right font-bold text-slate-900">{citation.table_facts.row_label} {citation.table_facts.metric}</dd>
        <dt className="text-slate-500">단위</dt><dd className="text-right font-bold text-slate-900">{citation.table_facts.unit}</dd>
        {citation.table_facts.values.map(({ period, value }) => <div className="contents" key={period}>
          <dt className="text-slate-600">{period.endsWith("F") ? `${period.slice(0, -1)}년 전망` : `${period}년`}</dt>
          <dd className="text-right font-mono font-bold tabular-nums text-slate-900">{value}</dd>
        </div>)}
      </dl>
      {citation.table_facts.interpretation ? <p className="mt-4 border-t border-slate-100 pt-3 text-sm leading-6 text-slate-700">{citation.table_facts.interpretation}</p> : null}
    </div> : null}
    {isTable && !citation.table_facts && citation.table_labels?.length ? <div className="mt-3 flex flex-wrap gap-2" aria-label="표 라벨">{citation.table_labels.map((label) => <span key={label} className="rounded-md bg-slate-100 px-2 py-1 text-xs font-semibold text-slate-700">{label}</span>)}</div> : null}
    {displayQuote ? <blockquote className="mt-2 border-l-2 border-blue-300 pl-3 text-sm leading-6 text-slate-700">{displayQuote}</blockquote> : null}
    {citation.display_note ? <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-sm leading-6 text-amber-900">{citation.display_note}</p> : null}
  </article>;
}

function ItemCard({ item, citations, documentId }: { item: AnalysisItem; citations: Citation[]; documentId: string }) {
  const sources = citations.filter((citation) => item.evidence_chunk_ids.includes(citation.chunk_id));
  return <article className="item-card"><div className="flex flex-wrap items-center gap-2"><h4 className="text-lg font-bold text-slate-900">{item.title}</h4><span className="badge">{item.interpretation_label}</span></div>
    <p className="mt-2 leading-7 text-slate-700">{item.reason}</p><div className="mt-4 space-y-3">{sources.map((source) => <SourceCard key={source.chunk_id} citation={source} documentId={documentId} />)}</div></article>;
}

export function AnalysisResultView({ result, documentId = "" }: { result: AnalysisResult | null; documentId?: string }) {
  if (!result) return null;
  return <section aria-label="분석 결과" className="mt-8 space-y-6">
    <div className="panel"><p className="eyebrow">핵심 요약</p><p className="mt-3 text-lg leading-8 text-slate-800">{result.summary}</p></div>
    <div className="grid gap-6 lg:grid-cols-2">
      <section className="panel"><h3 className="section-title text-emerald-800">호재</h3><div className="mt-4 space-y-4">{result.positives.map((item, index) => <ItemCard key={`${item.title}-${index}`} item={item} citations={result.citations} documentId={documentId} />)}{!result.positives.length && <p className="empty-copy">확인된 호재 근거가 없습니다.</p>}</div></section>
      <section className="panel"><h3 className="section-title text-rose-800">악재</h3><div className="mt-4 space-y-4">{result.negatives.map((item, index) => <ItemCard key={`${item.title}-${index}`} item={item} citations={result.citations} documentId={documentId} />)}{!result.negatives.length && <p className="empty-copy">확인된 악재 근거가 없습니다.</p>}</div></section>
    </div>
    {result.insufficient_evidence_note && <div role="note" className="state-box border-amber-200 bg-amber-50 text-amber-900">{result.insufficient_evidence_note}</div>}
    <p className="rounded-xl bg-slate-900 px-5 py-4 text-sm leading-6 text-white">{result.disclaimer}</p>
  </section>;
}
