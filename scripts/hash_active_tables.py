#!/usr/bin/env python3
"""Hash existing active tables in an enforced read-only snapshot transaction."""
import argparse
import json
from pathlib import Path

from sqlalchemy import text

# Reuse the audit's local-host database configuration and canonical hash format.
from audit_unseen_table import SessionLocal
from audit_shadow import snapshot


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--output', type=Path, required=True)
    args = cli.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    with SessionLocal() as db:
        db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
        result = snapshot(db)
        db.rollback()
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print({name: record['count'] for name, record in result.items()})


if __name__ == '__main__':
    main()
