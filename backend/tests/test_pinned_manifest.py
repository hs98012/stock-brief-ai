"""Fail-closed source binding and cohort scoring for the pinned audit."""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import verify_pinned_shadow as verifier


def test_missing_manifest_fails():
    with pytest.raises(ValueError, match='Missing or changed'):
        verifier.validate_binding({'manifests': [], 'revisions': []}, {})


def test_fallback_cannot_be_paddle_success():
    hit = {'quote': '근거 문장', 'chunk_char_start': 0, 'chunk_char_end': 5,
           'table_evidence': [], 'numeric_evidence': []}
    page = {'provenance': {'paddle_fingerprint_sha256': 'fingerprint',
                          'selected_words': [{'char_start': 0, 'char_end': 5,
                                              'source': 'paddle_structure', 'bbox': [0, 0, 1, 1]}]}}
    gold = {'literal_conditions': ['근거 문장']}
    with pytest.raises(ValueError, match='Fallback'):
        verifier._paddle_proof(hit, page, gold,
                               {'ocr_source': 'tesseract_fallback', 'fallback': True}, 'fingerprint')


@pytest.mark.parametrize('field', ['worker_image_id', 'pip_freeze_sha256',
                                   'model_files', 'parser_version', 'pdf_sha256'])
def test_changed_provenance_rejects_old_verdict(field):
    fingerprint = {'pip_freeze_sha256': 'dependency', 'model_files': {'weight': 'hash'},
                   'sha256': 'fingerprint'}
    manifest = {'revision_id': 'revision', 'sha256': 'manifest', 'worker_image_id': 'sha256:image',
                'worker_fingerprint': fingerprint, 'parser_version': 'parser', 'pdf_sha256': 'pdf'}
    data = {'manifests': [manifest], 'revisions': [{}],
            'evaluation_code': {'git_head': 'head', 'working_tree_diff_sha256': 'diff'}}
    previous = verifier.binding_for(data)
    changed = copy.deepcopy(data)
    target = changed['manifests'][0]
    if field == 'model_files':
        target['worker_fingerprint'][field]['weight'] = 'changed'
    elif field == 'pip_freeze_sha256':
        target['worker_fingerprint'][field] = 'changed'
    else:
        target[field] = 'changed'
    with pytest.raises(ValueError, match='Missing or changed'):
        verifier.validate_binding(changed, previous)


def test_active_control_is_counted_separately(monkeypatch):
    monkeypatch.setattr(verifier, 'validate_binding', lambda *_: None)
    control = {'results': [{'page_number': 1, 'chunk_id': 'control-chunk',
                            'quote': '대조군', 'table_evidence': []}]}
    candidate_hit = {'rank': 1, 'page_number': 2, 'chunk_id': 'chunk',
                     'chunk_char_start': 0, 'chunk_char_end': 4,
                     'quote': '근거수치', 'table_evidence': [], 'numeric_evidence': []}
    page = {'id': 'page', 'page_number': 2, 'final_text': '근거수치',
            'provenance': {'paddle_fingerprint_sha256': 'fingerprint',
                'selected_words': [{'char_start': 0, 'char_end': 4,
                    'source': 'paddle_structure', 'bbox': [0, 0, 1, 1]}]}}
    data = {'active_before': {}, 'cases': [
        {'id': 'control', 'question': '대조군?', 'scope': 'unchanged_active_control', 'active': control,
         'shadow': control, 'document_id': 'control-doc'},
        {'id': 'candidate', 'question': '후보?', 'scope': 'shadow_revision', 'active': {'results': []},
         'shadow': {'results': [candidate_hit]}, 'document_id': 'candidate-doc'}],
        'revisions': [{'document_id': 'candidate-doc', 'pages': [page],
                       'chunks': [{'id': 'chunk', 'page_id': 'page', 'char_start': 0, 'char_end': 4}]}],
        'manifests': [{'worker_fingerprint': {'sha256': 'fingerprint'},
                       'pages': [{'page_number': 2, 'ocr_source': 'paddle', 'fallback': False}]}]}
    gold = {'units': [
        {'case': 'control', 'unit': 'control', 'source_scope': 'active_control', 'page_number': 1},
        {'case': 'candidate', 'unit': 'candidate', 'source_scope': 'paddle_candidate',
         'page_number': 2, 'literal_conditions': ['근거수치']}]}
    result = verifier.score(data, {}, gold)
    assert result['paddle_candidate_recall@5'] == [1, 1]
    assert result['invariant_control_recall@5'] == [1, 1]
    assert result['combined_comparison_recall@5'] == [2, 2]
    monkeypatch.setattr(verifier, 'binding_for', lambda *_: {})
    verifier.compare_runs(data, copy.deepcopy(data))
