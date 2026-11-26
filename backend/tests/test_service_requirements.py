import pytest

from app.evidence_bundle import requirements_for


@pytest.mark.parametrize('question', [
    'LG의 2Q26 연결 영업이익은?',
    'LG CNS의 2026년 매출을 조원 단위로 알려줘',
    '2026년 별도 매출액 및 증감률은?',
])
def test_factual_question_never_has_empty_requirements(question):
    from app.evidence_bundle import requirement_resolution
    assert requirement_resolution(question)['requirements']


def test_empty_parser_result_is_not_coverage_success():
    from app.evidence_bundle import requirement_resolution
    assert requirement_resolution('2026년 직원 수는?')['status'] == 'unsupported_requirement'
    assert requirement_resolution('영업이익은?')['status'] == 'ambiguous_requirement'
    assert requirement_resolution('호재와 악재를 요약해줘')['status'] == 'no_factual_requirement_applicable'


def test_parser_error_is_fail_closed(monkeypatch):
    from app import evidence_bundle
    def fail(_):
        raise ValueError('parser failure')
    monkeypatch.setattr(evidence_bundle, 'requirements_for', fail)
    assert evidence_bundle.requirement_resolution('2026년 매출액은?')['status'] == 'requirement_generation_error'


def test_supported_parser_cannot_bypass_missing_search_requirements(monkeypatch):
    from uuid import uuid4
    from app.analysis_retrieval import collect_analysis_evidence
    from app.search import SearchExecution
    monkeypatch.setattr('app.analysis_retrieval.hybrid_search', lambda *a, **k: SearchExecution([], True, None))
    diagnostics = {}
    assert collect_analysis_evidence(object(), uuid4(), '2026년 영업이익은?', 10, object(), diagnostics) == []
    assert diagnostics['coverage_complete'] is False
