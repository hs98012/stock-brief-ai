import type { AnalysisItem, AnalysisResult, Citation } from "./types";

export function AnalysisState({ loading, error }: { loading: boolean; error: string | null }) {
  if (loading) return <div role="status" className="state-box">Ollama가 검색 근거를 검토하고 있습니다…</div>;
  if (error) return <div role="alert" className="state-box border-red-200 bg-red-50 text-red-800">{error}</div>;
  return null;
}

function SourceCard({ citation }: { citation: Citation }) {
  return <article className="source-card">
    <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs font-semibold text-slate-600"><span>{citation.filename}</span><span>{citation.issuer}</span><span>{citation.published_at}</span><span>PDF {citation.page_number}페이지</span></div>
    <p className="mt-3 text-xs font-bold text-blue-700">관련 원문 발췌</p>
    <blockquote className="mt-2 whitespace-pre-line border-l-2 border-blue-300 pl-3 text-sm leading-6 text-slate-700">{citation.quote}</blockquote>
  </article>;
}

function ItemCard({ item, citations }: { item: AnalysisItem; citations: Citation[] }) {
  const sources = citations.filter((citation) => item.evidence_chunk_ids.includes(citation.chunk_id));
  return <article className="item-card"><div className="flex flex-wrap items-center gap-2"><h4 className="text-lg font-bold text-slate-900">{item.title}</h4><span className="badge">{item.interpretation_label}</span></div>
    <p className="mt-2 leading-7 text-slate-700">{item.reason}</p><div className="mt-4 space-y-3">{sources.map((source) => <SourceCard key={source.chunk_id} citation={source} />)}</div></article>;
}

export function AnalysisResultView({ result }: { result: AnalysisResult | null }) {
  if (!result) return null;
  return <section aria-label="분석 결과" className="mt-8 space-y-6">
    <div className="panel"><p className="eyebrow">핵심 요약</p><p className="mt-3 text-lg leading-8 text-slate-800">{result.summary}</p></div>
    <div className="grid gap-6 lg:grid-cols-2">
      <section className="panel"><h3 className="section-title text-emerald-800">호재</h3><div className="mt-4 space-y-4">{result.positives.map((item, index) => <ItemCard key={`${item.title}-${index}`} item={item} citations={result.citations} />)}{!result.positives.length && <p className="empty-copy">확인된 호재 근거가 없습니다.</p>}</div></section>
      <section className="panel"><h3 className="section-title text-rose-800">악재</h3><div className="mt-4 space-y-4">{result.negatives.map((item, index) => <ItemCard key={`${item.title}-${index}`} item={item} citations={result.citations} />)}{!result.negatives.length && <p className="empty-copy">확인된 악재 근거가 없습니다.</p>}</div></section>
    </div>
    {result.insufficient_evidence_note && <div role="note" className="state-box border-amber-200 bg-amber-50 text-amber-900">{result.insufficient_evidence_note}</div>}
    <p className="rounded-xl bg-slate-900 px-5 py-4 text-sm leading-6 text-white">{result.disclaimer}</p>
  </section>;
}
