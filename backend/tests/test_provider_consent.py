import json
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.generation import (FallbackGenerationProvider, GenerationConnectionError,
    GenerationPolicyError, GenerationResponseError, get_generation_provider)
from app.models import AnalysisRun
from app.schemas import AnalysisRequest, GeneratedAnalysis, GeneratedItem
from tests.test_analysis import CountingProvider, ready_document, set_providers


@pytest.mark.parametrize('mode', ['EXTERNAL_WITH_CONSENT', 'FALLBACK_ALLOWED'])
@pytest.mark.parametrize('consent', [False, 'true', 1, None])
def test_consent_is_explicit_boolean(mode, consent):
    with pytest.raises(ValidationError):
        AnalysisRequest(document_id=uuid4(), execution_mode=mode, external_consent=consent)


def test_environment_and_key_cannot_enable_external_default(monkeypatch):
    monkeypatch.setenv('ANALYSIS_LLM_PROVIDER', 'gemini')
    monkeypatch.setenv('GEMINI_API_KEY', 'synthetic')
    monkeypatch.setenv('ANALYSIS_EXTERNAL_ENABLED', '1')
    monkeypatch.setattr('app.generation.GeminiGenerationProvider', lambda: pytest.fail('External adapter constructed'))
    assert get_generation_provider(AnalysisRequest(document_id=uuid4())).provider_name == 'ollama'


@pytest.mark.parametrize('path', ['/api/v1/analyses', '/api/v1/analyses/stream'])
def test_missing_api_consent_never_constructs_external_adapter(client, db, monkeypatch, path):
    monkeypatch.setenv('ANALYSIS_EXTERNAL_ENABLED', '1')
    monkeypatch.setattr('app.generation.GeminiGenerationProvider', lambda: pytest.fail('External adapter constructed'))
    response = client.post(path, json=dict(document_id=str(uuid4()), execution_mode='EXTERNAL_WITH_CONSENT'))
    assert response.status_code == 422 and db.query(AnalysisRun).count() == 0


@pytest.mark.parametrize('path', ['/api/v1/analyses', '/api/v1/analyses/stream'])
def test_server_policy_blocks_even_consented_request_before_run(client, db, monkeypatch, path):
    monkeypatch.delenv('ANALYSIS_EXTERNAL_ENABLED', raising=False)
    provider = CountingProvider('gemini', None)
    set_providers(provider)
    response = client.post(path, json=dict(document_id=str(uuid4()), execution_mode='EXTERNAL_WITH_CONSENT', external_consent=True))
    assert response.status_code == 403
    assert response.json()['detail']['code'] == 'provider_policy'
    assert provider.calls == 0 and db.query(AnalysisRun).count() == 0


def test_injected_external_provider_cannot_bypass_local_request(client, db):
    provider = CountingProvider('gemini', None)
    set_providers(provider)
    assert client.post('/api/v1/analyses', json=dict(document_id=str(uuid4()))).status_code == 403
    assert provider.calls == 0 and db.query(AnalysisRun).count() == 0


def test_fallback_requires_server_permission(monkeypatch):
    monkeypatch.setenv('ANALYSIS_EXTERNAL_ENABLED', '1')
    monkeypatch.delenv('ANALYSIS_OLLAMA_FALLBACK_ENABLED', raising=False)
    with pytest.raises(GenerationPolicyError):
        get_generation_provider(AnalysisRequest(document_id=uuid4(), execution_mode='FALLBACK_ALLOWED', external_consent=True))


@pytest.mark.parametrize('mode', ['LOCAL_ONLY', 'EXTERNAL_WITH_CONSENT', 'FALLBACK_ALLOWED'])
def test_requirement_hold_precedes_every_provider(client, db, monkeypatch, mode):
    monkeypatch.setenv('ANALYSIS_EXTERNAL_ENABLED', '1')
    monkeypatch.setenv('ANALYSIS_OLLAMA_FALLBACK_ENABLED', '1')
    document, _ = ready_document(db)
    primary = CountingProvider('ollama' if mode == 'LOCAL_ONLY' else 'gemini', None)
    fallback = CountingProvider('ollama', None) if mode == 'FALLBACK_ALLOWED' else None
    set_providers(FallbackGenerationProvider(primary, fallback))
    response = client.post('/api/v1/analyses', json=dict(document_id=str(document.id),
        question='영업이익은?', execution_mode=mode, external_consent=mode != 'LOCAL_ONLY'))
    assert response.status_code == 200
    result = response.json()
    assert result['analysis_status'] == 'insufficient_evidence'
    assert result['summary'] == '확인할 수 없습니다' and result['citations'] == []
    assert result['execution']['final_provider'] is None and not result['execution']['external_request_attempted']
    assert primary.calls == 0 and (fallback is None or fallback.calls == 0)


ID_FIELDS = {'chunk_id', 'source_chunk_id', 'source_chunk_ids', 'evidence_chunk_ids'}


def _without_ids(value):
    """Drops identifier fields so a number check only sees user-visible text."""
    if isinstance(value, dict):
        return {k: _without_ids(v) for k, v in value.items() if k not in ID_FIELDS}
    if isinstance(value, list):
        return [_without_ids(v) for v in value]
    return value


# A chunk UUID that contains the ungrounded number below. uuid4() does this about
# 0.55% of the time, which made the grounding check flaky.
CHUNK_ID_CONTAINING_999 = UUID('00000000-0000-4000-8000-000000000999')


@pytest.mark.parametrize('pinned_chunk_id', [None, CHUNK_ID_CONTAINING_999], ids=['random-id', 'id-with-999'])
@pytest.mark.parametrize('mode,fails,expected', [
    ('LOCAL_ONLY', False, 'ollama'), ('EXTERNAL_WITH_CONSENT', False, 'gemini'),
    ('FALLBACK_ALLOWED', True, 'ollama')])
def test_stream_all_modes_share_grounding_and_citations(client, db, monkeypatch, mode, fails, expected,
    pinned_chunk_id):
    monkeypatch.setenv('ANALYSIS_EXTERNAL_ENABLED', '1')
    monkeypatch.setenv('ANALYSIS_OLLAMA_FALLBACK_ENABLED', '1')
    document, chunk = ready_document(db, '매출은 전년 대비 20% 증가했습니다.')
    if pinned_chunk_id is not None:
        chunk.id = pinned_chunk_id
        db.commit()
    generated = GeneratedAnalysis(summary='임의의 숫자 999억원', positives=[GeneratedItem(
        title='매출 증가', reason='매출 999억원을 보장합니다.', evidence_chunk_ids=[chunk.id])], negatives=[])
    primary = CountingProvider('ollama' if mode == 'LOCAL_ONLY' else 'gemini',
        GenerationConnectionError('synthetic timeout') if fails else generated)
    fallback = CountingProvider('ollama', generated) if mode == 'FALLBACK_ALLOWED' else None
    provider = FallbackGenerationProvider(primary, fallback)
    set_providers(provider)
    response = client.post('/api/v1/analyses/stream', json=dict(document_id=str(document.id),
        execution_mode=mode, external_consent=mode != 'LOCAL_ONLY'))
    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines()]
    statuses = [e for e in events if e['type'] == 'status']
    assert [s['stage'] for s in statuses] == ['retrieving', 'generating'] + (['fallback'] if fails else []) + ['validating']
    assert all(set(s) == {'type', 'stage', 'provider'} for s in statuses)
    result = events[-1]['result']
    assert result['analysis_status'] == 'completed'
    assert len(result['positives']) == len(result['citations']) == 1
    assert result['citations'][0]['quote'] == chunk.content
    assert '999' not in json.dumps(_without_ids({k: result[k] for k in ['summary', 'positives', 'negatives', 'citations']}))
    assert result['execution'] == dict(requested_mode=mode, external_consent=mode != 'LOCAL_ONLY',
        external_request_attempted=mode != 'LOCAL_ONLY', final_provider=expected, fallback_used=fails)
    assert primary.calls == 1 and (fallback is None or fallback.calls == 1)
    run = db.query(AnalysisRun).one()
    assert run.result['execution'] == result['execution']


def test_stream_schema_failure_is_error_without_fallback_or_raw_output(client, db, monkeypatch):
    monkeypatch.setenv('ANALYSIS_EXTERNAL_ENABLED', '1')
    monkeypatch.setenv('ANALYSIS_OLLAMA_FALLBACK_ENABLED', '1')
    document, _ = ready_document(db)
    primary = CountingProvider('gemini', GenerationResponseError('private invalid output'))
    fallback = CountingProvider('ollama', None)
    set_providers(FallbackGenerationProvider(primary, fallback))
    response = client.post('/api/v1/analyses/stream', json=dict(document_id=str(document.id), execution_mode='FALLBACK_ALLOWED', external_consent=True))
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[-1]['type'] == 'error' and events[-1]['status'] == 502
    assert not any(e['type'] == 'result' for e in events)
    assert 'private invalid output' not in response.text and fallback.calls == 0
    assert db.query(AnalysisRun).one().status == 'failed'
