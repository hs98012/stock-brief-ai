import { describe, expect, it } from 'vitest';
import { readAnalysisStream, readResponse, requestError } from './api';

describe('safe API errors', () => {
  it('classifies non-JSON server failures', async () => {
    await expect(readResponse(new Response('Internal Server Error', { status: 500 }))).rejects.toThrow('서버 처리');
  });
  it('classifies incomplete embeddings and network failures', async () => {
    await expect(readResponse(new Response('{}', { status: 409 }))).rejects.toThrow('임베딩');
    expect(requestError(new TypeError('Failed to fetch'))).toContain('연결');
  });
  it('does not expose upstream stack traces', async () => {
    await expect(readResponse(new Response(JSON.stringify({detail:'Traceback secret'}), {status:503}))).rejects.toThrow('설정');
  });
});

describe('validated analysis event stream', () => {
  it('decodes fragmented Korean and reports fallback before returning the result', async () => {
    const wire = new TextEncoder().encode(JSON.stringify({type:'status',stage:'fallback',provider:'ollama'}) + '\n' +
      JSON.stringify({type:'result',result:{summary:'확인할 수 없습니다'}}) + '\n');
    const body = new ReadableStream({start(controller) {
      for (let i=0;i<wire.length;i+=3) controller.enqueue(wire.slice(i,i+3));
      controller.close();
    }});
    const statuses: string[] = [];
    const result = await readAnalysisStream(new Response(body), (stage,provider) => statuses.push(`${stage}:${provider}`));
    expect(statuses).toEqual(['fallback:ollama']);
    expect(result.summary).toBe('확인할 수 없습니다');
  });
  it('rejects incomplete streams and safe failure events', async () => {
    await expect(readAnalysisStream(new Response('{"type":"status","stage":"generating"}\n'),()=>{})).rejects.toThrow('완료 결과');
    await expect(readAnalysisStream(new Response('{"type":"error","status":502,"detail":"private upstream text"}\n'),()=>{})).rejects.toThrow('근거 검증');
  });
});
