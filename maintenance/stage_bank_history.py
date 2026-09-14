#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from maintenance.data_admin import build_fresh_database
from app.bulk_import import commit_batch, ensure_bulk_schema, stage_document
from app.import_identity import ensure_identity_schema
from app.imports import ensure_import_schema


def run_stage(statement_dir: Path) -> int:
    files = sorted(statement_dir.glob('*.pdf'))
    if not files:
        print('error=no PDF statements found')
        return 2

    with tempfile.TemporaryDirectory(prefix='flow-bank-stage-') as tmp:
        db_path = Path(tmp) / 'flow-staging.db'
        build_fresh_database(db_path)

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys = ON')
        try:
            ensure_import_schema(conn)
            ensure_identity_schema(conn)
            ensure_bulk_schema(conn)
            account_id = conn.execute(
                "INSERT INTO accounts(name,kind,current_balance_cents,is_active,include_in_safe_to_spend) VALUES(?,?,?,?,?)",
                ('Compte courant LCL - staging', 'checking', 0, 1, 1),
            ).lastrowid
            batch_id = conn.execute(
                'INSERT INTO bulk_import_batches(account_id,total_files) VALUES(?,?)',
                (account_id, len(files)),
            ).lastrowid

            stage_warnings = 0
            for path in files:
                doc = stage_document(conn, batch_id, account_id, path.name, path.read_bytes())
                warning = doc.get('warning')
                status = doc.get('status')
                if warning or status == 'warning':
                    stage_warnings += 1
                print(
                    f"stage {path.name}: type={doc.get('document_type')} status={status} "
                    f"tx={(doc.get('summary') or {}).get('transactions')} warning={warning or '-'}"
                )

            conn.commit()
            result = commit_batch(conn, batch_id)
            conn.commit()

            imports = conn.execute(
                '''SELECT filename,status,total_rows,imported_rows,duplicate_rows,review_rows,
                          quality_status,quality_message,period_start,period_end,
                          opening_balance_cents,closing_balance_cents
                   FROM imports ORDER BY period_end,id'''
            ).fetchall()
            bad_quality = 0
            for row in imports:
                ok = row['quality_status'] in ('ok', 'review') and row['status'] == 'completed'
                if not ok:
                    bad_quality += 1
                print(
                    f"import {row['filename']}: status={row['status']} quality={row['quality_status']} "
                    f"rows={row['total_rows']} imported={row['imported_rows']} dup={row['duplicate_rows']} "
                    f"review={row['review_rows']} period={row['period_start']}->{row['period_end']}"
                )

            tx_count = conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0]
            import_count = len(imports)
            duplicate_docs = conn.execute(
                "SELECT COUNT(*) FROM bulk_import_documents WHERE batch_id=? AND status='duplicate'",
                (batch_id,),
            ).fetchone()[0]

            print(
                'summary '
                f'files={len(files)} imports={import_count} transactions={tx_count} '
                f'stage_warnings={stage_warnings} bad_quality={bad_quality} '
                f'duplicate_docs={duplicate_docs} commit={result}'
            )

            if import_count != len(files):
                return 3
            if bad_quality:
                return 4
            if duplicate_docs:
                return 5
            return 0
        finally:
            conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description='Stage all LCL statements in an isolated temporary Flow database')
    parser.add_argument('statement_dir', type=Path)
    args = parser.parse_args()
    return run_stage(args.statement_dir)


if __name__ == '__main__':
    raise SystemExit(main())
