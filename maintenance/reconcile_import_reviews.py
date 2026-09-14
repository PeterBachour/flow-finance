#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.imports import (
    accept_categorized_import_reviews,
    ensure_import_schema,
    refresh_review_counts,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Reconcile stale Flow import-review metadata with explicitly categorized transactions.'
    )
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()

    db = args.db.resolve()
    if not db.exists():
        print(f'error=db not found: {db}', file=sys.stderr)
        return 2

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        ensure_import_schema(conn)
        pending = int(conn.execute(
            "SELECT COUNT(*) n FROM transaction_import_meta WHERE review_status='needs_review'"
        ).fetchone()['n'])
        candidates = int(conn.execute(
            """SELECT COUNT(*) n
               FROM transaction_import_meta m
               JOIN transactions t ON t.id=m.transaction_id
               WHERE m.review_status='needs_review'
                 AND TRIM(COALESCE(t.category,''))<>''"""
        ).fetchone()['n'])
        unresolved = pending - candidates
        affected_imports = int(conn.execute(
            """SELECT COUNT(DISTINCT m.import_id) n
               FROM transaction_import_meta m
               JOIN transactions t ON t.id=m.transaction_id
               WHERE m.review_status='needs_review'
                 AND TRIM(COALESCE(t.category,''))<>''"""
        ).fetchone()['n'])

        accepted = 0
        verified = 0
        if args.apply:
            accepted = accept_categorized_import_reviews(conn)
            refresh_review_counts(conn)
            verified = int(conn.execute(
                "SELECT COUNT(*) n FROM imports WHERE quality_status='verified'"
            ).fetchone()['n'])
            conn.commit()
        else:
            conn.rollback()

        mode = 'apply' if args.apply else 'dry-run'
        print(
            f'mode={mode} pending={pending} categorized_candidates={candidates} '
            f'unresolved_without_category={unresolved} affected_imports={affected_imports} '
            f'accepted={accepted} verified_imports={verified}'
        )
        if not args.apply:
            print('No data changed. Re-run with --apply after checking these counts.')
    finally:
        conn.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
