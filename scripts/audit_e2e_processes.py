"""Read-only E2E process observations. Never infer ownership from a PID or port."""
import json
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def classify(command):
    try:
        argv = shlex.split(command)
    except ValueError:
        return None
    if not argv:
        return None
    executable = Path(argv[0]).name
    if executable == 'replicatord':
        return 'system_protected'
    if executable.startswith('python') and len(argv) > 1:
        if argv[1] in ('scripts/run_service_e2e_api.py', str(ROOT / 'scripts/run_service_e2e_api.py')):
            return 'e2e_candidate'
    return None


def observations(output):
    rows = []
    for line in output.splitlines():
        # ps lstart has five fields (weekday, month, day, time, year).
        parts = line.split(None, 8)
        if len(parts) != 9 or not parts[0].isdigit() or not parts[1].isdigit():
            continue
        category = classify(parts[8])
        if category:
            rows.append(dict(pid=int(parts[0]), ppid=int(parts[1]), user=parts[2],
                started_at=' '.join(parts[3:8]), command=parts[8], category=category,
                cleanup_status='BLOCKED', ownership_verified=False,
                reason='System process' if category == 'system_protected' else
                    'Read-only observation cannot prove this session launched the process'))
    return rows


def main():
    result = subprocess.run(['ps', '-axo', 'pid,ppid,user,lstart,command'],
        capture_output=True, text=True)
    report = dict(observed_at=datetime.now(timezone.utc).isoformat(),
        observation_status='OBSERVED' if result.returncode == 0 else 'NOT_VERIFIED',
        processes=observations(result.stdout) if result.returncode == 0 else [],
        termination_supported=False)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
