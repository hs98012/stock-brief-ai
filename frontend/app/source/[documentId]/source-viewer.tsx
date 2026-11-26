'use client';

import { useEffect, useState } from 'react';
import { readResponse, requestError } from '../../api';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8001';

export function SourceViewer({ documentId, initialPage }: { documentId: string; initialPage: number }) {
  const [page, setPage] = useState(initialPage);
  const [total, setTotal] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    void fetch(`${API_BASE}/api/v1/documents/${encodeURIComponent(documentId)}`).then(readResponse)
      .then(body => { if (active) setTotal(body.total_pages); })
      .catch(reason => { if (active) setError(requestError(reason)); });
    return () => { active = false; };
  }, [documentId]);
  function move(next: number) {
    setError(null); setPage(next);
    window.history.replaceState(null, '', `?page=${next}`);
  }
  return <main className="mx-auto max-w-5xl p-6"><h1 className="text-xl font-bold">원문 PDF {page}페이지</h1>
    <p className="my-3 text-sm text-slate-600">원본 PDF를 페이지 이미지로 표시합니다.</p>
    <nav className="mb-4 flex items-center gap-4" aria-label="PDF 페이지 이동">
      <button className="secondary-button" disabled={page <= 1} onClick={() => move(page-1)}>이전 페이지</button>
      <span>{page} / {total ?? '…'}</span>
      <button className="secondary-button" disabled={!total || page >= total} onClick={() => move(page+1)}>다음 페이지</button>
      <a className="text-blue-700 underline" href={`${API_BASE}/api/v1/documents/${encodeURIComponent(documentId)}/file#page=${page}`} target="_blank" rel="noreferrer">전체 원본 PDF</a>
    </nav>
    {error && <p role="alert">{error}</p>}
    {/* eslint-disable-next-line @next/next/no-img-element */}
    <img className="w-full" src={`${API_BASE}/api/v1/documents/${encodeURIComponent(documentId)}/pages/${page}/image`} alt={`원문 PDF ${page}페이지`} onError={() => setError('원본 PDF 페이지를 열 수 없습니다.')} />
  </main>;
}
