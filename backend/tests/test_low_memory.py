import json
import threading
import time

import httpx
import pytest

from app.embeddings import OllamaEmbeddingProvider
from app.generation import OllamaGenerationProvider, generation_request_id
from app.local_inference import serial_local_inference


def test_low_memory_payloads_and_private_trace(monkeypatch, caplog):
    monkeypatch.setenv('STOCK_BRIEF_LOW_MEMORY', '1')
    payloads = []
    def handler(request):
        payloads.append(json.loads(request.content))
        if request.url.path == '/api/embed':
            return httpx.Response(200, json={'embeddings': [[1.0] * 1024]})
        return httpx.Response(200, json={'response': json.dumps({'summary': '확인할 수 없습니다',
            'positives': [], 'negatives': [], 'insufficient_evidence_note': '확인할 수 없습니다'}),
            'eval_count': 20, 'eval_duration': 2_000_000_000})
    client = httpx.Client(base_url='http://local.test', transport=httpx.MockTransport(handler))
    OllamaEmbeddingProvider(client=client).embed(['private-source'])
    provider = OllamaGenerationProvider(client=client)
    token = generation_request_id.set('run-test')
    try:
        with caplog.at_level('INFO'):
            provider.generate('private-prompt')
    finally:
        generation_request_id.reset(token)
    assert payloads[0]['keep_alive'] == 0
    assert payloads[1]['keep_alive'] == '60s' and payloads[1]['options']['num_ctx'] == 4096
    assert 'num_batch' not in payloads[1]['options']
    assert provider.generation_trace['tokens_per_second'] == 10
    assert provider.generation_trace['request_id'] == 'run-test'
    assert 'private-prompt' not in caplog.text and 'private-source' not in caplog.text


def test_low_memory_serializes_embedding_and_generation(monkeypatch):
    monkeypatch.setenv('STOCK_BRIEF_LOW_MEMORY', '1')
    active = 0
    peak = 0
    barrier = threading.Barrier(2)
    @serial_local_inference
    def work():
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        time.sleep(0.02)
        active -= 1
    def run():
        barrier.wait()
        work()
    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)
    assert peak == 1 and all(not thread.is_alive() for thread in threads)


def test_failed_request_does_not_keep_previous_native_timings(monkeypatch):
    monkeypatch.delenv('STOCK_BRIEF_LOW_MEMORY', raising=False)
    outcomes = [httpx.Response(200, json={'response': '{"summary":"확인할 수 없습니다",'
        '"positives":[],"negatives":[],"insufficient_evidence_note":null}', 'eval_count': 10}),
        httpx.Response(500)]
    client = httpx.Client(base_url='http://local.test', transport=httpx.MockTransport(lambda r: outcomes.pop(0)))
    provider = OllamaGenerationProvider(client=client)
    provider.generate('first')
    with pytest.raises(Exception):
        provider.generate('second')
    assert 'eval_count' not in provider.generation_trace
    assert provider.generation_trace['status'] == 'GenerationHTTPError'

