"""Exclusive first-attempt records with independent checksums."""
import hashlib
import json
from pathlib import Path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def exclusive_json(path, data):
    with Path(path).open('x') as stream:
        json.dump(data, stream, ensure_ascii=False, sort_keys=True, indent=2, default=str)
        stream.write('\n')


def freeze_artifacts(run):
    paths = [p for p in run.rglob('*') if p.is_file() and p.name != 'artifacts.sha256.json']
    exclusive_json(run/'artifacts.sha256.json', {str(p.relative_to(run)): digest(p) for p in sorted(paths)})
    for path in paths + [run/'artifacts.sha256.json']:
        path.chmod(0o444)


def verify_artifacts(run):
    expected = json.loads((run/'artifacts.sha256.json').read_text())
    actual = {str(p.relative_to(run)) for p in run.rglob('*') if p.is_file()
        and p.name not in {'artifacts.sha256.json', 'scoring.json', 'scoring.sha256.json'}}
    if actual != set(expected):
        raise ValueError('Artifact inventory changed')
    for name, sha in expected.items():
        path = (run/name).resolve()
        if not path.is_relative_to(run.resolve()) or digest(path) != sha:
            raise ValueError('Artifact hash mismatch')
