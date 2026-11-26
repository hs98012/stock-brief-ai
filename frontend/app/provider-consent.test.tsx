import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import Home from './page';
import { AnalysisState } from './analysis-view';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function setup(external = true) {
  const requests: Record<string, unknown>[] = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => {
    if (url.endsWith('/analysis-options')) return new Response(JSON.stringify({external_enabled:external,fallback_enabled:external,local_model:'gemma3:4b',external_model:'gemini-3.7-flash'}));
    if (url.endsWith('/documents')) return new Response(JSON.stringify({items:[{id:'doc-a',company_name:'개발 문서',issuer:'발행기관',published_at:'2026-10-13',document_type:'broker_report',status:'completed'}]}));
    if (url.endsWith('/embedding-status')) return new Response(JSON.stringify({embedding_status:'completed',embedded_chunk_count:583,total_chunk_count:583}));
    if (url.endsWith('/analyses/stream')) {
      const body = JSON.parse(String(options?.body)); requests.push(body);
      const result={analysis_status:'insufficient_evidence',generation_model:null,generated_at:'2026-10-13',summary:'확인할 수 없습니다',positives:[],negatives:[],citations:[],insufficient_evidence_note:null,disclaimer:'원문 근거 참고',execution:{requested_mode:body.execution_mode,external_consent:body.external_consent,external_request_attempted:false,final_provider:null,fallback_used:false}};
      return new Response(JSON.stringify({type:'result',result})+'\n');
    }
    throw new Error('Unexpected request');
  }));
  render(<Home />);
  return requests;
}

async function selectDocument() {
  await screen.findByRole('option', {name:/개발 문서/});
  fireEvent.change(screen.getByLabelText('분석 문서'),{target:{value:'doc-a'}});
  await waitFor(() => expect(screen.getByRole('button',{name:'분석하기'})).toBeEnabled());
}

describe('request-scoped provider consent', () => {
  it('defaults to local and sends no external consent', async () => {
    const requests=setup(); await selectDocument();
    expect(screen.getByLabelText('분석 실행 방식')).toHaveValue('LOCAL_ONLY');
    fireEvent.click(screen.getByRole('button',{name:'분석하기'}));
    await screen.findByText(/HOLD ·/);
    expect(requests[0]).toMatchObject({execution_mode:'LOCAL_ONLY',external_consent:false});
  });
  it('requires consent, clears it after edits and submission, and keeps HOLD', async () => {
    const requests=setup(); await selectDocument();
    fireEvent.change(screen.getByLabelText('분석 실행 방식'),{target:{value:'FALLBACK_ALLOWED'}});
    const consent=screen.getByLabelText('이번 분석의 Gemini 전송에 동의');
    expect(consent).not.toBeChecked(); expect(screen.getByRole('button',{name:'분석하기'})).toBeDisabled();
    fireEvent.click(consent);
    fireEvent.change(screen.getByRole('textbox',{name:'질문'}),{target:{value:'호재 악재 요약'}});
    expect(consent).not.toBeChecked();
    fireEvent.click(consent); fireEvent.click(screen.getByRole('button',{name:'분석하기'}));
    await screen.findByText(/HOLD ·/);
    expect(requests[0]).toMatchObject({execution_mode:'FALLBACK_ALLOWED',external_consent:true});
    expect(consent).not.toBeChecked(); expect(screen.getByRole('button',{name:'분석하기'})).toBeDisabled();
  });
  it('disables external choices when server policy is closed', async () => {
    setup(false); await selectDocument();
    expect(screen.getByRole('option',{name:/외부 분석 ·/})).toBeDisabled();
    expect(screen.getByRole('option',{name:/외부 분석 후 실패/})).toBeDisabled();
  });
  it('shows local generation and a persistent fallback notice', () => {
    render(<AnalysisState loading error={null} stage="validating" provider="ollama" fallback />);
    expect(screen.getByRole('status')).toHaveTextContent('승인된 로컬 fallback');
    expect(screen.getByRole('status')).toHaveTextContent('사실·인용 근거를 검증');
  });
});
