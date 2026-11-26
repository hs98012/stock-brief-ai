import type { AnalysisResult } from './types';

export async function readResponse(response: Response) {
  const body = await response.json().catch(() => null);
  if (response.ok) return body;
  if (body?.detail?.code === 'retrieval_failure') throw new Error('문서 검색·근거 검증에 실패했습니다. 잠시 후 다시 시도하세요.');
  if (body?.detail?.code === 'provider_policy') throw new Error('외부 분석 정책 또는 이번 요청의 전송 동의를 확인하세요.');
  const messages: Record<number, string> = {
    409: 'PDF 처리 또는 임베딩이 완료되지 않았습니다. 문서 상태를 확인하세요.',
    503: '분석 모델의 dependency·설정 또는 서버 연결을 확인해야 합니다.',
    504: '분석 요청 시간이 초과됐습니다. 잠시 후 다시 시도하세요.',
    502: '모델 응답 또는 근거 검증에 실패했습니다. 안전한 결과를 확인할 수 없습니다.',
    500: '서버 처리 중 오류가 발생했습니다. 잠시 후 다시 시도하세요.',
  };
  throw new Error(messages[response.status] ?? (typeof body?.detail === 'string' ? body.detail : `요청에 실패했습니다(${response.status}).`));
}

export function requestError(reason: unknown) {
  if (reason instanceof TypeError) return '서버에 연결할 수 없습니다. 네트워크와 API 실행 상태를 확인하세요.';
  return reason instanceof Error ? reason.message : '요청을 완료하지 못했습니다.';
}

export async function readAnalysisStream(response: Response, onStatus: (stage: string, provider: string | null) => void): Promise<AnalysisResult> {
  if (!response.ok) return readResponse(response);
  if (!response.body) throw new Error('분석 상태 연결을 확인할 수 없습니다.');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let pending = '';
  let result: AnalysisResult | null = null;
  try {
    while (true) {
      const { value, done } = await reader.read();
      pending += decoder.decode(value, { stream: !done });
      const lines = pending.split('\n'); pending = lines.pop() ?? '';
      for (const line of lines) {
        if (!line.trim()) continue;
        const event = JSON.parse(line);
        if (event.type === 'status') onStatus(event.stage, event.provider ?? null);
        else if (event.type === 'result') result = event.result;
        else if (event.type === 'error') await readResponse(new Response(JSON.stringify({detail: event.detail}), {status: event.status}));
      }
      if (done) break;
    }
    if (pending.trim() || !result) throw new Error('분석 완료 결과를 확인할 수 없습니다.');
    return result;
  } finally { reader.releaseLock(); }
}
