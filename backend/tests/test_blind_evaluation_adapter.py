"""Synthetic-only dry run: no sealed input, live model, OCR or DB access."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.blind_eval.isolation import validate_input
from scripts.blind_eval.prediction import predict
from scripts.blind_eval.scoring import score_case
from scripts.blind_eval.ledger import exclusive_json, freeze_artifacts, verify_artifacts

CONFIG = {'top_k': 5, 'rerank': True, 'diagnostics': True,
          'effective_environment': {}, 'transport': {'ollama_base_url': 'http://unused', 'paddle_structure_url': 'http://unused'}}
QUESTION = {'id': 'synthetic-1', 'document_id': 'synthetic-doc', 'question': '매출 수치는?'}
TEXT = '매출 2025년 연결 백만원 123 actual'
FACT = {'metric': '매출', 'period': '2025년', 'scope': '연결', 'unit': '백만원',
        'value': '123', 'value_status': 'actual', 'source_page': 1, 'estimate_version': None}
TOKENS = ['매출', '2025년', '연결', '백만원', '123', 'actual']
SPANS = [{'char_start': TEXT.index(t), 'char_end': TEXT.index(t)+len(t), 'quote': t,
          'bbox': [i*10, 0, i*10+9, 9]} for i, t in enumerate(TOKENS)]
GOLD = {'document_id': 'synthetic-doc', 'expected_response': None,
        'facts': [FACT | {'proof': [{'page': 1, 'quote': s['quote'],
                                   'bbox_pdf_points': s['bbox']} for s in SPANS]}]}
ITEM = {'document_id': 'synthetic-doc', 'page_number': 1,
        'table_evidence': [FACT | {'source_spans': SPANS}]}
PAGES = {1: {'final_text': TEXT}}


def rank(*args, **kwargs):
    return NS(results=[deepcopy(ITEM)], evidence_pack=[deepcopy(ITEM)],
              coverage_complete=True, vector_search_unavailable_reason=None)


def test_normal_answer_and_source_proof():
    prediction = predict(QUESTION, [], CONFIG, None, rank=rank,
                         generate=lambda question, pack: '합성 테스트 답변')
    assert prediction['answer'] == '합성 테스트 답변'
    assert score_case(prediction, GOLD, PAGES)['verdict'] == 'PASS'
    assert score_case(prediction, GOLD, PAGES)['factual_correctness'] == 'NOT_VERIFIED'


def test_insufficient_evidence_hold():
    def empty(*a, **k):
        return NS(results=[], evidence_pack=[], coverage_complete=False,
                  vector_search_unavailable_reason=None)
    prediction = predict(QUESTION, [], CONFIG, None, rank=empty, generate=lambda *a: pytest.fail())
    assert prediction['answer'] == '확인할 수 없습니다'
    assert score_case(prediction, {'facts': [], 'expected_response': '확인할 수 없습니다'}, {})['hold_correct']
    assert score_case(prediction, GOLD, PAGES)['false_hold']


@pytest.mark.parametrize('fault', ['page', 'document', 'unit', 'partial', 'span', 'bbox'])
def test_bad_citation_unit_and_partial_proof_never_pass(fault):
    prediction = predict(QUESTION, [], CONFIG, None, rank=rank)
    item = prediction['search']['evidence_pack'][0]
    if fault == 'page': item['page_number'] = 2
    elif fault == 'document': item['document_id'] = 'wrong'
    elif fault == 'unit': item['table_evidence'][0]['unit'] = '억원'
    elif fault == 'partial': item['table_evidence'][0]['source_spans'].pop()
    elif fault == 'span': item['table_evidence'][0]['source_spans'][0]['quote'] = '변조'
    else: item['table_evidence'][0]['source_spans'][0]['bbox'] = [999, 999, 1000, 1000]
    result = score_case(prediction, GOLD, PAGES)
    assert result['verdict'] == 'REVIEW'
    assert result['false_complete'] and not result['strict_evidence_validity']


@pytest.mark.parametrize('stage', ['model', 'ocr'])
def test_runtime_failure_is_error_not_hold(stage):
    def fail(*a, **k): raise RuntimeError(stage+' failed')
    result = predict(QUESTION, [], CONFIG, None, rank=fail if stage == 'ocr' else rank,
                     generate=fail if stage == 'model' else None)
    scored = score_case(result, GOLD, PAGES)
    assert result['status'] == 'ERROR' and scored['verdict'] == 'ERROR'
    assert not scored['hold_correct'] and not scored['false_hold']


@pytest.mark.parametrize('field', ['gold', 'expected_answer', 'expected_hold', 'scoring_metadata'])
def test_label_injection_blocked_before_any_stage(field):
    data = {'documents': [], 'questions': [QUESTION | {field: 'SECRET_SENTINEL'}], 'configuration': CONFIG}
    with pytest.raises(ValueError): validate_input(data)
    with pytest.raises(ValueError): predict(data['questions'][0], [], CONFIG, None,
        rank=lambda *a, **k: pytest.fail('retrieval was reached'))


@pytest.mark.parametrize('method', ['path', 'os_open', 'symlink'])
def test_direct_gold_file_access_blocked(tmp_path, method):
    sealed = tmp_path/'evals'; sealed.mkdir()
    secret = sealed/'gold.json'; secret.write_text('SECRET_SENTINEL')
    link = tmp_path/'alias'; link.symlink_to(secret)
    code = "from scripts.blind_eval.isolation import install_guard; import os; from pathlib import Path; "
    code += f"install_guard({str(tmp_path)!r}, {str(tmp_path/'stage')!r}); "
    code += (f"os.open({str(secret)!r}, os.O_RDONLY)" if method == 'os_open'
        else f"Path({str(link if method == 'symlink' else secret)!r}).read_text()")
    result = subprocess.run([sys.executable, '-c', code], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode != 0 and 'PermissionError' in result.stderr
    assert 'SECRET_SENTINEL' not in result.stdout


def test_artifacts_exclusive_and_tamper_evident(tmp_path):
    exclusive_json(tmp_path/'prediction.json', {'status': 'ERROR'})
    with pytest.raises(FileExistsError): exclusive_json(tmp_path/'prediction.json', {'status': 'PASS'})
    freeze_artifacts(tmp_path); verify_artifacts(tmp_path)
    path = tmp_path/'prediction.json'; path.chmod(0o644); path.write_text('{}')
    with pytest.raises(ValueError): verify_artifacts(tmp_path)


def test_real_production_retrieval_stages_have_no_gold_input(monkeypatch):
    from app import search
    from backend.tests.test_evidence_bundle import QUESTION as compound, row
    seen = []
    original = search.reciprocal_rank_fusion
    def rrf(*args, **kwargs):
        seen.append('rrf'); assert 'SECRET_SENTINEL' not in repr(args)
        return original(*args, **kwargs)
    monkeypatch.setattr(search, 'reciprocal_rank_fusion', rrf)
    class Provider:
        available = True
        provider_name = 'ollama'; model = 'bge-m3'; dimensions = 2; unavailable_reason = None
        def embed(self, texts):
            seen.append('embedding'); assert 'SECRET_SENTINEL' not in repr(texts)
            return [[1, 0] for _ in texts]
    chunk, page, document = row('소재 실적은 원가 하락 효과로 개선될 것으로 전망한다.', 1)
    chunk.embedding = [1, 0]; chunk.embedding_provider = 'ollama'
    chunk.embedding_model = 'bge-m3'; chunk.embedding_dimensions = 2
    result = search.rank_rows([(chunk, page, document)], compound, 5, Provider(), diagnostics=True)
    assert seen == ['embedding', 'rrf']
    assert result.results and result.requirements
    assert result.coverage_complete is False
    assert 'SECRET_SENTINEL' not in repr(result)
    assert 'scripts.blind_eval.scoring' not in (ROOT/'scripts/blind_eval/prediction.py').read_text()


def test_query_bm25_selector_prompt_receive_only_blind_data(monkeypatch):
    from app import search, evidence_bundle
    from backend.tests.test_evidence_bundle import QUESTION as compound, row
    touched = set()
    def observe(name, fn):
        def wrapped(*args, **kwargs):
            assert 'SECRET_SENTINEL' not in repr((args, kwargs))
            touched.add(name)
            return fn(*args, **kwargs)
        return wrapped
    monkeypatch.setattr(search, 'tokenize', observe('bm25', search.tokenize))
    monkeypatch.setattr(evidence_bundle, 'requirements_for', observe('query_parser', evidence_bundle.requirements_for))
    monkeypatch.setattr(evidence_bundle, 'build_evidence_pack', observe('selector', evidence_bundle.build_evidence_pack))
    class Provider:
        available = True; provider_name = 'ollama'; model = 'bge-m3'; dimensions = 2
        unavailable_reason = None
        def embed(self, texts):
            assert 'SECRET_SENTINEL' not in repr(texts)
            touched.add('embedding'); return [[1, 0] for _ in texts]
    chunk, page, doc = row('소재 실적은 원가 하락 효과로 개선될 것으로 전망한다.', 1)
    chunk.embedding = [1, 0]; chunk.embedding_provider = 'ollama'
    chunk.embedding_model = 'bge-m3'; chunk.embedding_dimensions = 2
    search.rank_rows([(chunk, page, doc)], compound, 5, Provider(), diagnostics=True)
    assert touched == {'bm25', 'query_parser', 'selector', 'embedding'}
    def generate(question, pack):
        assert 'SECRET_SENTINEL' not in repr((question, pack))
        touched.add('prompt_generation'); return 'synthetic'
    predict(QUESTION, [], CONFIG, None, rank=rank, generate=generate)
    assert 'prompt_generation' in touched


def test_os_file_sandbox_denies_native_gold_reads(tmp_path):
    executable = __import__('shutil').which('sandbox-exec')
    if executable is None:
        pytest.skip('macOS sandbox unavailable: real first-run is blocked')
    root = tmp_path/'evals'; root.mkdir()
    stage = root/'stage'; stage.mkdir()
    secret = root/'gold.json'; secret.write_text('SECRET_SENTINEL')
    allowed = stage/'input.json'; allowed.write_text('BLIND')
    profile = ('(version 1)(allow default)(deny file-read* (require-all (subpath '+json.dumps(str(root))+') '
               '(require-not (subpath '+json.dumps(str(stage))+'))))')
    code = f"from pathlib import Path; print(Path({str(allowed)!r}).read_text()); Path({str(secret)!r}).read_text()"
    result = subprocess.run([executable, '-p', profile, sys.executable, '-c', code], capture_output=True, text=True)
    assert result.stdout.strip() == 'BLIND'
    assert result.returncode != 0 and 'PermissionError' in result.stderr


def test_ocr_failure_preserves_each_question_error(tmp_path, monkeypatch):
    from scripts.blind_eval import prediction
    from app import embeddings, pdf_pipeline
    from uuid import uuid4
    import hashlib
    document_id = str(uuid4())
    source = tmp_path/'synthetic-source.txt'; source.write_text('synthetic extraction fixture')
    metadata = dict(document_id=document_id, company_name='합성 fixture', stock_code=None,
        issuer='fixture', published_at='2026-01-01', original_filename=source.name,
        pdf_path=str(source), sha256=hashlib.sha256(source.read_bytes()).hexdigest())
    questions = [QUESTION | {'id': 'ocr-'+str(i), 'document_id': document_id} for i in range(2)]
    exclusive_json(tmp_path/'input.json', {'documents': [metadata], 'questions': questions,
        'configuration': CONFIG | {'transport': {'ollama_base_url': 'http://unused',
                                                 'paddle_structure_url': 'http://unused'}}})
    monkeypatch.setattr(prediction, 'install_guard', lambda *a: None)
    monkeypatch.setattr(embeddings, 'OllamaEmbeddingProvider', lambda: None)
    def fail(*a): raise RuntimeError('Synthetic OCR worker failure')
    monkeypatch.setattr(pdf_pipeline, 'extract_pdf', fail)
    prediction.main(tmp_path)
    records = [json.loads(p.read_text()) for p in tmp_path.glob('*.prediction.json')]
    assert len(records) == 2 and all(r['status'] == 'ERROR' for r in records)
    assert all(r['errors'][0]['message'] == 'Synthetic OCR worker failure' for r in records)


def test_scoring_saved_synthetic_run_only(tmp_path, monkeypatch):
    from scripts.blind_eval.scoring import score_run
    from scripts import verify_sealed_holdout as verifier
    bundle = tmp_path/'bundle'; bundle.mkdir()
    policy = {'counts': {'total_cases': 1, 'answerable': 1, 'expected_hold': 0, 'factual_units': 1}}
    exclusive_json(bundle/'gold.json', [GOLD | {'question_id': QUESTION['id'], 'source_sha256': 'synthetic-hash'}])
    exclusive_json(bundle/'criteria.json', policy)
    manifest_path = tmp_path/'manifest.json'; manifest_path.write_text('synthetic manifest')
    run = tmp_path/'run'; run.mkdir(); stage = run/'predictions'; stage.mkdir()
    exclusive_json(run/'run.json', {'run_id': 'synthetic-only', 'manifest_sha256': verifier.digest(manifest_path)})
    exclusive_json(stage/'input.json', {'documents': [{'document_id': QUESTION['document_id'], 'sha256': 'synthetic-hash'}]})
    exclusive_json(stage/(QUESTION['document_id']+'-pages.json'), [PAGES[1] | {'page_number': 1}])
    exclusive_json(stage/(QUESTION['id']+'.prediction.json'), predict(QUESTION, [], CONFIG, None, rank=rank))
    freeze_artifacts(run)
    monkeypatch.setattr(verifier, 'ROOT', tmp_path)
    monkeypatch.setattr(verifier, 'verify', lambda _: {'bundle_path': 'bundle', 'criteria_sha256': 'synthetic-policy'})
    score_run(run, manifest_path)
    report = json.loads((run/'scoring.json').read_text())
    assert report['results'][0]['verdict'] == 'PASS' and report['false_complete'] == 0
    assert report['answer_metrics'] == 'NOT_VERIFIED'
    with pytest.raises(FileExistsError): score_run(run, manifest_path)
