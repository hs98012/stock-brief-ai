"""Process safety fixtures do not start or signal any process."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('audit_e2e_processes',
    Path(__file__).resolve().parents[2] / 'scripts/audit_e2e_processes.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def test_reused_pid_is_system_protected_and_never_owned():
    output = '12080 1 user Tue Oct 13 16:24:16 2026 /System/Library/PrivateFrameworks/ReplicatorCore.framework/Support/replicatord'
    row, = audit.observations(output)
    assert row['category'] == 'system_protected'
    assert row['cleanup_status'] == 'BLOCKED' and not row['ownership_verified']


def test_matching_development_command_is_not_ownership_proof():
    row, = audit.observations('123 1 user Tue Oct 13 16:24:16 2026 /usr/bin/python3 scripts/run_service_e2e_api.py --low-memory')
    assert row['category'] == 'e2e_candidate'
    assert row['cleanup_status'] == 'BLOCKED' and not row['ownership_verified']


def test_shell_search_and_unrelated_same_basename_are_not_candidates():
    assert audit.classify('/bin/zsh -c "python scripts/run_service_e2e_api.py"') is None
    assert audit.classify('/usr/bin/python3 /another/project/run_service_e2e_api.py') is None
    assert audit.observations('PID PPID USER STARTED COMMAND') == []
