"""Seal integrity tests use temporary files, never sealed questions or RAG."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'scripts'))
from verify_sealed_holdout import bound_path, digest, verify


def sealed(root):
    bundle = root/'bundle'
    bundle.mkdir()
    (root/'code.py').write_text('baseline\n')
    (bundle/'gold.json').write_text('[]\n')
    (bundle/'baseline-code-hashes.json').write_text(json.dumps({'code.py': digest(root/'code.py')}))
    manifest = root/'manifest.json'
    manifest.write_text(json.dumps(dict(bundle_path='bundle', evaluation_tools={},
        files={p.name: digest(p) for p in bundle.iterdir()}, document_count=0, question_count=0)))
    manifest.with_suffix('.sha256').write_text(digest(manifest)+'\n')
    return manifest, bundle


def test_valid_seal(tmp_path):
    manifest, _ = sealed(tmp_path)
    assert verify(manifest, tmp_path)['question_count'] == 0


@pytest.mark.parametrize('target', ['gold', 'code', 'manifest', 'extra_file'])
def test_changed_inputs_fail_closed(tmp_path, target):
    manifest, bundle = sealed(tmp_path)
    path = {'gold': bundle/'gold.json', 'code': tmp_path/'code.py',
            'manifest': manifest, 'extra_file': bundle/'new.txt'}[target]
    path.write_text('changed\n')
    with pytest.raises(ValueError):
        verify(manifest, tmp_path)


@pytest.mark.parametrize('path', ['../outside', '/private/tmp/outside'])
def test_manifest_path_escape_rejected(tmp_path, path):
    with pytest.raises(ValueError, match='Unsafe'):
        bound_path(tmp_path, path)
