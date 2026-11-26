"""Immutable, source-bound manifests for shadow-only Paddle evaluations."""
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), default=str).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def command(*args):
    return subprocess.check_output(args, cwd=ROOT, text=True).strip()


def code_identity():
    head = command('git', 'rev-parse', 'HEAD')
    changes = subprocess.check_output(['git', 'diff', '--binary', 'HEAD'], cwd=ROOT)
    untracked = subprocess.check_output(
        ['git', 'ls-files', '--others', '--exclude-standard', '-z'], cwd=ROOT).split(b'\0')
    extra = {name.decode(): file_hash(ROOT / name.decode()) for name in untracked if name}
    return head, digest({'tracked_diff_sha256': hashlib.sha256(changes).hexdigest(),
                         'untracked_files': extra})


def worker_identity():
    container = command('docker', 'compose', 'ps', '-q', 'ocr-worker')
    if not container:
        raise RuntimeError('OCR worker container is not running')
    image = command('docker', 'inspect', '--format', '{{.Image}}', container)
    raw = command('docker', 'compose', 'exec', '-T', 'ocr-worker', 'python', '-c',
                  "import urllib.request; print(urllib.request.urlopen('http://localhost:8090/fingerprint').read().decode())")
    fingerprint = json.loads(raw)
    claimed = fingerprint.pop('sha256')
    if digest(fingerprint) != claimed:
        raise RuntimeError('Worker fingerprint is not self-consistent')
    fingerprint['sha256'] = claimed
    if not fingerprint.get('model_files') or not fingerprint.get('pip_freeze_sha256'):
        raise RuntimeError('Worker model/dependency hashes missing')
    return {'container_id': container, 'image_id': image, 'fingerprint': fingerprint}


def _span(text, raw):
    start, end = raw['char_start'], raw['char_end']
    if not (0 <= start < end <= len(text)):
        raise ValueError('Invalid evidence span')
    boxes = raw.get('boxes') or [raw.get('bbox')]
    if not boxes or any(not box or len(box) != 4 for box in boxes):
        raise ValueError('Evidence location missing')
    if raw.get('quote') is not None and text[start:end] != raw['quote']:
        raise ValueError('Evidence quote does not match page')
    return {'role': raw.get('role'), 'char_start': start, 'char_end': end,
            'text_sha256': hashlib.sha256(text[start:end].encode()).hexdigest(),
            'boxes': boxes, 'source': raw.get('source') or raw.get('sources')}


def revision_manifest(revision, *, run_id, worker, git_head, diff_hash,
                      cases_sha256, gold_sha256):
    pages = []
    fingerprint = worker['fingerprint']
    for page in revision['pages']:
        text = page['final_text']
        provenance = page['provenance']
        raw = provenance.get('paddle_structure')
        used_paddle = provenance.get('primary_engine') == 'paddle_structure'
        if used_paddle and (raw is None or
                provenance.get('paddle_fingerprint_sha256') != fingerprint['sha256']):
            raise ValueError('Paddle observation not bound to current worker fingerprint')
        evidence = []
        for kind, items in (('index', provenance.get('index_segments', [])),
                            ('numeric', provenance.get('numeric_evidence', [])),
                            ('table', page['table_facts'])):
            for fact in items:
                spans = fact.get('source_spans') or [fact]
                evidence.append({'kind': kind, 'page_number': page['page_number'],
                    'source': fact['source'], 'bbox': fact['bbox'],
                    'source_spans': [_span(text, span) for span in spans],
                    'fact_sha256': digest(fact)})
        pages.append({'page_number': page['page_number'],
            'pdf_sha256': revision['file_hash'], 'final_text_sha256': page['final_text_sha256'],
            'raw_paddle_sha256': digest(raw) if raw is not None else None,
            'ocr_source': 'paddle' if used_paddle else provenance.get('primary_engine'),
            'fallback': provenance.get('primary_engine') == 'tesseract_fallback',
            'fallback_reason': provenance.get('paddle_error') or page.get('ocr_error'),
            'ocr_dpi': provenance.get('ocr_dpi'), 'evidence': evidence})
    manifest = {'revision_id': revision['id'], 'created_at': str(revision['created_at']),
        'run_id': run_id, 'document_id': revision['document_id'],
        'pdf_sha256': revision['file_hash'], 'parser_version': revision['parser_version'].split('+pin-')[0],
        'revision_version': revision['parser_version'], 'git_head': git_head,
        'working_tree_diff_sha256': diff_hash, 'worker_image_id': worker['image_id'],
        'worker_container_id': worker['container_id'], 'worker_fingerprint': fingerprint,
        'cases_sha256': cases_sha256, 'gold_sha256': gold_sha256, 'pages': pages}
    manifest['sha256'] = digest(manifest)
    return manifest


def verify_manifest(revision, manifest):
    expected = manifest['sha256']
    if digest({key: value for key, value in manifest.items() if key != 'sha256'}) != expected:
        raise ValueError('Manifest hash mismatch')
    worker = {'image_id': manifest['worker_image_id'],
              'container_id': manifest['worker_container_id'],
              'fingerprint': manifest['worker_fingerprint']}
    fresh = revision_manifest(revision, run_id=manifest['run_id'], worker=worker,
        git_head=manifest['git_head'], diff_hash=manifest['working_tree_diff_sha256'],
        cases_sha256=manifest['cases_sha256'], gold_sha256=manifest['gold_sha256'])
    if fresh != manifest:
        raise ValueError('Revision contents differ from pinned manifest')
