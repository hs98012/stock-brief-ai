#!/usr/bin/env python3
"""Explicit future first attempt; reserved output prevents repeat attempts."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
from uuid import uuid4

from verify_sealed_holdout import ROOT, bound_path, verify, digest
sys.path.insert(0, str(ROOT))
from scripts.blind_eval.isolation import validate_input
from scripts.blind_eval.ledger import exclusive_json, freeze_artifacts
from prepare_blind_evaluation import OUTPUT, identity, runtime


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--manifest', type=Path, required=True)
    cli.add_argument('--execute-first-run', action='store_true')
    args = cli.parse_args()
    manifest = verify(args.manifest)
    lock = json.loads(OUTPUT.read_text())
    if digest(OUTPUT) != json.loads(OUTPUT.with_suffix('.sha256.json').read_text())['configuration_sha256']:
        raise ValueError('Evaluation lock changed')
    if lock['adapter_code'] != identity() or lock['manifest_sha256'] != digest(args.manifest):
        raise ValueError('Adapter code or manifest changed')
    if not args.execute_first_run:
        print('VERIFIED; prediction/retrieval/scoring NOT_RUN')
        return
    if not shutil.which('sandbox-exec'):
        raise RuntimeError('OS file sandbox unavailable; prediction must not run')
    output = bound_path(ROOT, manifest['first_run_output'])
    output.mkdir(parents=True, exist_ok=False)
    metadata = {'run_id': str(uuid4()), 'timestamp': datetime.now(timezone.utc).isoformat(),
        'code_commit': lock['commit'], 'configuration_sha256': digest(OUTPUT),
        'manifest_sha256': digest(args.manifest), 'phase': lock['phase']}
    exclusive_json(output/'run.json', metadata)
    stage = output/'predictions'
    stage.mkdir()
    status = {'status': 'ERROR', 'error': 'First attempt interrupted before completion'}
    questions = []
    try:
        current = runtime(lock['configuration'])
        if current != lock['runtime']:
            raise ValueError('Runtime fingerprints changed')
        if subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip() != lock['commit']:
            raise ValueError('Code commit changed')
        bundle = ROOT/manifest['bundle_path']
        questions = json.loads((bundle/'questions.json').read_text())
        if len(questions) != manifest['question_count'] or len({q['id'] for q in questions}) != len(questions):
            raise ValueError('Question inventory mismatch')
        documents = []
        for index, metadata in enumerate(json.loads((bundle/'documents.json').read_text())):
            source = bound_path(ROOT, metadata['path'])
            if digest(source) != metadata['sha256']:
                raise ValueError('PDF fingerprint mismatch')
            target = stage/(str(index)+'.pdf')
            shutil.copyfile(source, target)
            documents.append({key: metadata[key] for key in ('document_id', 'company_name',
                'stock_code', 'issuer', 'published_at', 'original_filename', 'sha256')} | {'pdf_path': str(target)})
        config = lock['configuration']
        data = {'documents': documents, 'questions': questions,
            'configuration': {key: config[key] for key in
                ('effective_environment', 'top_k', 'rerank', 'diagnostics', 'transport')}}
        validate_input(data)
        exclusive_json(stage/'input.json', data)
        # Deny label/review reads at the OS layer, including child native code.
        profile = ('(version 1)(allow default)(deny file-read* (require-any '
            '(require-all (subpath '+json.dumps(str(ROOT/'evals'))+') '
            '(require-not (subpath '+json.dumps(str(output))+'))) '
            '(subpath '+json.dumps(str(ROOT/'docs'))+')))')
        completed = subprocess.run(['sandbox-exec', '-p', profile, sys.executable,
            '-m', 'scripts.blind_eval.prediction', str(stage)], cwd=ROOT,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        exclusive_json(output/'worker.json', {'returncode': completed.returncode,
            'stdout': completed.stdout[-4000:], 'stderr': completed.stderr[-4000:]})
        status = {'status': 'COLLECTED_NOT_SCORED' if completed.returncode == 0 else 'ERROR',
                  'worker_returncode': completed.returncode}
    except Exception as exc:
        status = {'status': 'ERROR', 'error': type(exc).__name__+': '+str(exc)}
    finally:
        for question in questions:
            target = stage/(question['id']+'.prediction.json')
            if not target.exists():
                exclusive_json(target, {'id': question['id'], 'document_id': question['document_id'],
                    'status': 'ERROR', 'answer': None, 'search': None,
                    'errors': [{'type': 'WorkerFailure', 'message': status.get('error', 'No worker result')}],
                    'answer_metrics': 'NOT_VERIFIED'})
        status['finished_at'] = datetime.now(timezone.utc).isoformat()
        exclusive_json(output/'completion.json', status)
        freeze_artifacts(output)
    if status['status'] == 'ERROR':
        raise RuntimeError('First attempt failed; preserved, do not retry')


if __name__ == '__main__':
    main()
