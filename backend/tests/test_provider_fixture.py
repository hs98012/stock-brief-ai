"""Independent fixture: installed SDK wire capture and existing claim validator."""
from copy import deepcopy
import json
from pathlib import Path
import sys
from uuid import uuid4

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from prepare_provider_fixture import FIXTURE, MOCK_RESULT, SOURCE_ID, capture_payload, execute_approved, validate_response
from app.generation import GenerationPolicyError
from app.schemas import GeneratedAnalysis


def test_exact_wire_is_minimal_and_independent():
    packet = capture_payload()
    wire = json.loads(packet['body'])
    assert packet['validation']['status'] == 'VERIFIED'
    assert set(wire) == {'contents', 'systemInstruction', 'generationConfig'}
    assert set(FIXTURE) == {'question', 'source', 'evidence'}
    assert SOURCE_ID in packet['body']
    for forbidden in ['LG', '003550', 'miraeasset', '/Users/', 'file_hash', 'document_id',
                      'bbox', 'embedding', '@', '5f4001ad', '3489541b', 'api_key']:
        assert forbidden not in packet['body']
    assert len(packet['validation']['citations']) == 1
    assert 'gemini-3.8-flash:generateContent' in packet['url']
    assert wire['generationConfig']['maxOutputTokens'] == 2048
    assert wire['generationConfig']['thinkingConfig'] == {'thinking_level': 'LOW'}


@pytest.mark.parametrize('change', ['unknown', 'empty', 'number', 'summary', 'duplicate', 'negative', 'scope', 'period', 'unit'])
def test_fixture_rejects_unsupported_outputs(change):
    raw = deepcopy(MOCK_RESULT)
    item = raw['positives'][0]
    if change == 'unknown': item['evidence_chunk_ids'] = ['bc748cd8-39c8-42d8-8d20-51df9e862f90']
    elif change == 'empty': item['evidence_chunk_ids'] = []
    elif change == 'number': item['reason'] = item['reason'].replace('20%', '999%')
    elif change == 'summary': raw['summary'] = '합성 장치 999% 감소'
    elif change == 'duplicate': raw['positives'].append(deepcopy(item))
    elif change == 'negative': raw['negatives'] = raw.pop('positives'); raw['positives'] = []
    elif change == 'scope': item['reason'] = '실제 기업의 처리시간은 기준 대비 20% 감소했습니다.'
    elif change == 'period': item['reason'] = '2025년 처리시간은 기준 대비 20% 감소했습니다.'
    elif change == 'unit': item['reason'] = item['reason'].replace('20%', '20억원')
    with pytest.raises(ValueError): validate_response(GeneratedAnalysis.model_validate(raw))


def test_invalid_schema_is_rejected():
    with pytest.raises(ValidationError): GeneratedAnalysis.model_validate({'summary': 123})


def test_empty_result_remains_hold():
    raw = {'summary': '확인할 수 없습니다', 'positives': [], 'negatives': []}
    assert validate_response(GeneratedAnalysis.model_validate(raw))['status'] == 'HOLD'


def test_live_gate_never_opens_transport_without_approval_and_policy(monkeypatch):
    packet = capture_payload()
    scope = {'provider': 'gemini', 'model': 'gemini-3.8-flash', 'fixture': 'independent-synthetic-v1',
             'payload_sha256': packet['sha256'], 'maximum_external_attempts': 1, 'fallback': False, 'max_output_tokens': 2048,
             'thinking_level': 'low', 'approval_id': str(uuid4())}
    monkeypatch.setattr('httpx.HTTPTransport', lambda **kw: pytest.fail('live transport constructed'))
    with pytest.raises(ValueError, match='explicit approval'): execute_approved(scope, packet)
    scope.update(approved=True, external_consent=True)
    monkeypatch.delenv('ANALYSIS_EXTERNAL_ENABLED', raising=False)
    with pytest.raises(GenerationPolicyError): execute_approved(scope, packet)
    scope['payload_sha256'] = 'different'
    with pytest.raises(ValueError, match='scope mismatch'): execute_approved(scope, packet)


def test_scoped_executor_uses_only_reviewed_wire_in_memory(monkeypatch, tmp_path):
    monkeypatch.setattr("prepare_provider_fixture.LEDGER_DIR", tmp_path / "consumption")
    import httpx
    packet = capture_payload()
    scope = {'provider': 'gemini', 'model': 'gemini-3.8-flash', 'fixture': 'independent-synthetic-v1',
             'payload_sha256': packet['sha256'], 'maximum_external_attempts': 1,
             'fallback': False, 'approved': True, 'external_consent': True,
             'max_output_tokens': 2048, 'thinking_level': 'low', 'approval_id': str(uuid4())}
    sent = []
    def handler(request):
        sent.append(request.content)
        return httpx.Response(200, json={'candidates': [{'content': {'parts': [
            {'text': json.dumps(MOCK_RESULT)}]}, 'finishReason': 'STOP'}]})
    monkeypatch.setenv('ANALYSIS_EXTERNAL_ENABLED', '1')
    monkeypatch.setenv('GEMINI_API_KEY', 'synthetic-test-key')
    monkeypatch.setattr('httpx.HTTPTransport', lambda **kw: httpx.MockTransport(handler))
    assert execute_approved(scope, packet)['validation']['status'] == 'VERIFIED'
    assert sent == [packet['body'].encode()]
    from app.generation import GenerationOutputError
    with pytest.raises(GenerationOutputError): execute_approved(scope, packet)
    assert len(sent) == 1
    assert len(list((tmp_path / 'consumption').glob('*.json'))) == 1
    # A mutated approval/body mismatch must stop before the inner transport.
    packet['sha256'] = scope['payload_sha256'] = '0' * 64
    from app.generation import GenerationOutputError
    with pytest.raises(GenerationOutputError): execute_approved(scope, packet)
    assert len(sent) == 1


@pytest.mark.parametrize('failure', ['timeout', 'rate_limit', 'schema'])
def test_fixture_sdk_failures_and_fallback(failure):
    import httpx
    from google import genai
    from google.genai import types
    from app.generation import GeminiGenerationProvider, FallbackGenerationProvider, GenerationResponseError
    class LocalMock:
        provider_name = 'ollama'
        model = 'gemma3:4b'
        available = True
        unavailable_reason = None
        calls = 0
        def generate(self, prompt):
            self.calls += 1
            return GeneratedAnalysis.model_validate(MOCK_RESULT)
    def handler(request):
        if failure == 'timeout': raise httpx.ReadTimeout('synthetic timeout', request=request)
        if failure == 'rate_limit': return httpx.Response(429, json={'error': {'code': 429, 'message': 'synthetic'}})
        return httpx.Response(200, json={'candidates': [{'content': {'parts': [{'text': '{"summary":123}'}]}, 'finishReason': 'STOP'}]})
    transport = httpx.Client(transport=httpx.MockTransport(handler))
    with genai.Client(api_key='synthetic-test-key', http_options=types.HttpOptions(
            httpx_client=transport, retry_options=types.HttpRetryOptions(attempts=1))) as sdk:
        local = LocalMock()
        primary = GeminiGenerationProvider(api_key='synthetic-test-key', client=sdk, max_attempts=1)
        provider = FallbackGenerationProvider(primary, local)
        if failure == 'schema':
            with pytest.raises(GenerationResponseError): provider.generate('independent synthetic fixture')
            assert local.calls == 0
        else:
            assert validate_response(provider.generate('independent synthetic fixture'))['status'] == 'VERIFIED'
            assert local.calls == 1


def test_atomic_consumption_race_has_one_winner(monkeypatch, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from prepare_provider_fixture import consume_approval
    monkeypatch.setattr('prepare_provider_fixture.LEDGER_DIR', tmp_path / 'consumption')
    identity = str(uuid4())
    packet = capture_payload()
    def consume(_):
        try:
            consume_approval(identity, packet)
            return True
        except FileExistsError:
            return False
    with ThreadPoolExecutor(max_workers=4) as workers:
        assert sum(workers.map(consume, range(8))) == 1
    marker = json.loads((tmp_path / 'consumption' / (identity + '.json')).read_text())
    assert marker['state'] == 'CONSUMED_BEFORE_SEND_OUTCOME_UNKNOWN'


def test_uncertain_timeout_consumes_approval_without_retry(monkeypatch, tmp_path):
    import httpx
    from app.generation import GenerationConnectionError, GenerationOutputError
    monkeypatch.setattr('prepare_provider_fixture.LEDGER_DIR', tmp_path / 'consumption')
    packet = capture_payload()
    scope = {'provider': 'gemini', 'model': 'gemini-3.8-flash', 'fixture': 'independent-synthetic-v1',
             'payload_sha256': packet['sha256'], 'maximum_external_attempts': 1,
             'fallback': False, 'approved': True, 'external_consent': True,
             'max_output_tokens': 2048, 'thinking_level': 'low', 'approval_id': str(uuid4())}
    sent = []
    def handler(request):
        assert (tmp_path / 'consumption' / (scope['approval_id'] + '.json')).exists()
        sent.append(request.content)
        assert request.extensions['timeout']['read'] == 30
        raise httpx.ReadTimeout('uncertain synthetic outcome', request=request)
    monkeypatch.setenv('ANALYSIS_EXTERNAL_ENABLED', '1')
    monkeypatch.setenv('GEMINI_API_KEY', 'synthetic-test-key')
    monkeypatch.setattr('httpx.HTTPTransport', lambda **kw: httpx.MockTransport(handler))
    with pytest.raises(GenerationConnectionError): execute_approved(scope, packet)
    with pytest.raises(GenerationOutputError): execute_approved(scope, packet)
    assert len(sent) == 1


def test_partial_consumption_marker_is_never_reused(monkeypatch, tmp_path):
    from prepare_provider_fixture import consume_approval
    monkeypatch.setattr('prepare_provider_fixture.LEDGER_DIR', tmp_path)
    identity = str(uuid4())
    (tmp_path / (identity + '.json')).write_bytes(b'')
    with pytest.raises(FileExistsError): consume_approval(identity, capture_payload())
