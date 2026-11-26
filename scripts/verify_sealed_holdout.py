#!/usr/bin/env python3
"""Verify a sealed evaluation bundle without reading gold answers or running RAG."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bound_path(root, relative):
    path = Path(relative)
    if path.is_absolute() or '..' in path.parts:
        raise ValueError('Unsafe manifest path')
    resolved = (root/path).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError('Manifest path escapes bundle')
    return resolved


def verify(manifest_path, code_root=ROOT):
    manifest_path = manifest_path.resolve()
    expected = manifest_path.with_suffix('.sha256').read_text().split()[0]
    if digest(manifest_path) != expected:
        raise ValueError('Manifest seal mismatch')
    manifest = json.loads(manifest_path.read_text())
    bundle = bound_path(code_root, manifest['bundle_path'])
    for relative, expected_hash in manifest['files'].items():
        if digest(bound_path(bundle, relative)) != expected_hash:
            raise ValueError('Sealed file changed: '+relative)
    actual = {str(p.relative_to(bundle)) for p in bundle.rglob('*') if p.is_file()}
    if actual != set(manifest['files']):
        raise ValueError('Sealed bundle file inventory changed')
    code = json.loads((bundle/'baseline-code-hashes.json').read_text())
    for relative, expected_hash in code.items():
        if digest(bound_path(code_root, relative)) != expected_hash:
            raise ValueError('Baseline code/config changed: '+relative)
    for relative, expected_hash in manifest['evaluation_tools'].items():
        if digest(bound_path(code_root, relative)) != expected_hash:
            raise ValueError('Evaluation tool changed: '+relative)
    for relative, expected_hash in manifest.get('external_worker_code', {}).items():
        if digest(bound_path(code_root, relative)) != expected_hash:
            raise ValueError('Worker source changed: '+relative)
    return manifest


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--manifest', type=Path, required=True)
    args = cli.parse_args()
    manifest = verify(args.manifest)
    print(json.dumps(dict(seal='VERIFIED', documents=manifest['document_count'],
        questions=manifest['question_count'], gold_answers_read=False,
        retrieval_called=False, generation_called=False)))


if __name__ == '__main__':
    main()
