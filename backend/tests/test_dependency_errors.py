import builtins
import pytest
from app.generation import GeminiGenerationProvider, GenerationConfigurationError


def test_missing_gemini_sdk_is_configuration_error(monkeypatch):
    original = builtins.__import__
    def missing(name, *args, **kwargs):
        if name == 'google':
            raise ImportError('SDK absent')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', missing)
    with pytest.raises(GenerationConfigurationError, match='requirements'):
        GeminiGenerationProvider(api_key='test-only')


def test_retrieval_error_finishes_single_run(client, db, monkeypatch):
    from tests.test_analysis import ready_document, set_providers, FakeGenerationProvider
    from app.schemas import GeneratedAnalysis
    from app.models import AnalysisRun
    document, _ = ready_document(db)
    set_providers(FakeGenerationProvider(GeneratedAnalysis(summary='요약', positives=[], negatives=[])))
    def fail(*args, **kwargs):
        raise RuntimeError('private retrieval failure')
    monkeypatch.setattr('app.analysis_service.collect_analysis_evidence', fail)
    response = client.post('/api/v1/analyses', json={'document_id': str(document.id), 'question':'호재 악재 요약'})
    assert response.status_code == 503
    assert 'private' not in response.text
    assert db.query(AnalysisRun).one().status == 'failed'


def test_saved_analysis_read_excludes_internal_trace_without_new_run(client, db):
    from tests.test_analysis import ready_document
    from app.models import AnalysisRun
    from app.schemas import AnalysisResult
    from datetime import datetime, timezone
    document, _ = ready_document(db)
    result = AnalysisResult(analysis_status='insufficient_evidence', generation_model=None,
        generated_at=datetime.now(timezone.utc), summary='확인할 수 없습니다', positives=[],
        negatives=[], citations=[], insufficient_evidence_note=None, disclaimer='투자 권유 아님')
    run = AnalysisRun(document_id=document.id, question='요약', status='insufficient_evidence',
        generation_provider='ollama', generation_model='gemma3:4b',
        result={**result.model_dump(mode='json'), '_evaluation_trace':{'private':'audit'}})
    db.add(run); db.commit()
    response = client.get(f'/api/v1/documents/{document.id}/analyses/latest')
    assert response.status_code == 200
    assert '_evaluation_trace' not in response.text
    assert db.query(AnalysisRun).count() == 1
