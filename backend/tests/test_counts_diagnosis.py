"""Characterize HOLD boundaries; no new count admission contract is implemented."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts'))
from audit_counts_requirement import diagnose
from app.evidence_bundle import requirements_for
from app.evidence_requirements import fact_requirement_match, table_requirements


@pytest.fixture(scope='module')
def frozen_counts():
    directory = ROOT/'evals/results/paddle'
    paths = [directory/'graph-before-tables-20261002.json',
             directory/'graph-after-final-search-20261002.json']
    if not all(p.exists() for p in paths):
        pytest.skip('Immutable offline observations unavailable; never substitute synthetic source')
    observed, search = [next(c for c in json.loads(p.read_text())['cases']
                            if c['id'] == 'new-mixed-counts') for p in paths]
    return observed, search


def test_counts_query_and_source_are_independent_failures(frozen_counts):
    observed, frozen = frozen_counts
    result = diagnose(frozen['question'], observed)
    assert result['requirements'] == []
    assert result['query_predicates'] == {'period_present': False, 'supported_metric_present': False}
    assert result['stored_fact_count'] == result['rebuilt_fact_count'] == result['validated_fact_count'] == 0
    assert result['graph_node_count'] == result['chunk_count'] == 0
    assert result['primitive_trace'] and all(t['header_count'] == 0 and not t['passed']
                                            for t in result['primitive_trace'])
    assert result['completeness_proof'] is None and not result['automatic_pass_justified']
    assert frozen['coverage_complete'] is None and frozen['strict_pass'] is False


def test_bypassing_period_gate_does_not_supply_metric_identity(frozen_counts):
    observed, frozen = frozen_counts
    requirement = table_requirements(frozen['question'])[0]
    assert requirement['metric'] is None and not requirement['period_required']
    assert not fact_requirement_match(requirement, {})[0]


def test_observed_cells_are_not_population_proof(frozen_counts):
    observed, frozen = frozen_counts
    result = diagnose(frozen['question'], observed)
    assert result['observed_tables'] and result['observed_words']
    assert all(w['exact'] for w in result['observed_words'])
    assert result['source_period_tokens'] == []
    assert result['completeness_proof'] is None
    assert not result['automatic_pass_justified']


def test_deleted_source_cannot_gain_count_approval(frozen_counts):
    observed, frozen = frozen_counts
    damaged = deepcopy(observed)
    damaged['provenance']['selected_words'] = []
    damaged['provenance']['native_tables'] = []
    damaged['provenance']['paddle_tables'] = []
    result = diagnose(frozen['question'], damaged)
    assert result['observed_words'] == result['observed_tables'] == []
    assert result['completeness_proof'] is None and not result['automatic_pass_justified']


@pytest.mark.parametrize('question', [
    '표에 명시된 총개수를 알려줘.',
    '표의 항목은 몇 개인가?',
    '조건을 만족하는 항목은 몇 개인가?',
    '중복을 제외한 고유 항목은 몇 개인가?',
    '2025년 항목은 몇 개인가?',
    '여러 표에 분산된 항목은 총 몇 개인가?',
])
def test_count_expression_has_no_supported_typed_requirement(question):
    assert requirements_for(question) == []
