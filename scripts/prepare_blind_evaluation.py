#!/usr/bin/env python3
"""Freeze runtime identity only; does not load holdout questions or invoke RAG."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import httpx
from verify_sealed_holdout import ROOT, verify, digest
sys.path.insert(0, str(ROOT))
from scripts.blind_eval.ledger import exclusive_json

OUTPUT = ROOT/'evals/blind-evaluation-v1-lock.json'


def identity():
    paths = sorted((ROOT/'scripts/blind_eval').glob('*.py')) + [ROOT/'scripts/run_blind_evaluation.py',
        ROOT/'scripts/prepare_blind_evaluation.py']
    return {str(p.relative_to(ROOT)): digest(p) for p in paths}


def runtime(config):
    transport = config['transport']
    worker = httpx.get(transport['paddle_structure_url']+'/fingerprint', timeout=10)
    worker.raise_for_status()
    httpx.get(transport['paddle_structure_url']+'/health', timeout=10).raise_for_status()
    tags = httpx.get(transport['ollama_base_url']+'/api/tags', timeout=10)
    tags.raise_for_status()
    model = [m for m in tags.json()['models'] if m['name'] in {'bge-m3', 'bge-m3:latest'}]
    if len(model) != 1 or model[0]['digest'] != config['embedding']['digest']:
        raise ValueError('Embedding digest mismatch')
    image = subprocess.check_output(['docker', 'inspect', config['worker']['container_name'],
        '--format', '{{.Image}}'], text=True).strip()
    if image != config['worker']['image_id']:
        raise ValueError('Worker image mismatch')
    return {'worker_image': image, 'worker_fingerprint': worker.json(), 'embedding': model[0]}


def main():
    manifest_path = ROOT/'evals/sealed-holdout-v1-manifest.json'
    manifest = verify(manifest_path)
    config = json.loads((ROOT/manifest['bundle_path']/'configuration.json').read_text())
    runtime_data = runtime(config)
    lock = {'schema_version': 1, 'phase': 'retrieval_evidence',
        'generation_enabled': False, 'answer_metrics': 'NOT_VERIFIED',
        'manifest_sha256': digest(manifest_path), 'sealed_configuration_sha256': manifest['configuration_sha256'],
        'evaluation_policy_sha256': manifest['criteria_sha256'],
        'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'adapter_code': identity(), 'runtime': runtime_data, 'configuration': config,
        'prediction_schema': 'id/document_id/status/answer/search/results/evidence_pack/coverage_complete/errors',
        'scoring_schema': 'verdict/correct/hold_correct/factual_correctness/citation_accuracy/false_complete/false_hold/review_required',
        'generation_model_version': 'NOT_VERIFIED_NOT_USED: '+config['effective_environment']['GEMINI_MODEL'],
        'chunking': 'sealed structured_spans source SHA-256; 1200 chars; structural splitting, no overlap',
        'retrieval': 'BM25Okapi + isolated exact cosine + RRF k=60; candidate=max(top_k*4,20); top_k=5',
        'os_isolation': 'macOS sandbox-exec deny read evals/docs, prediction receives staged allowlisted input',
        'first_output': manifest['first_run_output'], 'automatic_retries': 0}
    exclusive_json(OUTPUT, lock)
    exclusive_json(OUTPUT.with_suffix('.sha256.json'), {'configuration_sha256': digest(OUTPUT)})
    print(json.dumps({'lock': str(OUTPUT), 'configuration_sha256': digest(OUTPUT), 'evaluation': 'NOT_RUN'}))


if __name__ == '__main__':
    main()
