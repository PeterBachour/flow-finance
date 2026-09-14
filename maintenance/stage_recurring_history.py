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

from app.data_intelligence import detect_recurring_transactions, ensure_intelligence_schema
from app.import_identity import ensure_identity_schema, import_rows_occurrence_safe
from app.imports import ensure_import_schema, parse_statement, statement_metadata


def _fresh_db(path: Path) -> None:
    old = os.environ.get('FLOW_DB_PATH')
    os.environ['FLOW_DB_PATH'] = str(path)
    try:
        if 'app.db' in sys.modules:
            del sys.modules['app.db']
        from app import db
        db.DB_PATH = path
        db.init_db()
    finally:
        if old is None:
            os.environ.pop('FLOW_DB_PATH', None)
        else:
            os.environ['FLOW_DB_PATH'] = old


def _pdfs(path: Path) -> list[Path]:
    if path.is_dir():
        return sorted(path.glob('*.pdf'))
    return [path] if path.suffix.lower() == '.pdf' else []


def main() -> int:
    parser = argparse.ArgumentParser(description='Stage recurring debit detection from bank statement history')
    parser.add_argument('--statements', type=Path, required=True)
    parser.add_argument('--min-confidence', type=float, default=0.52)
    parser.add_argument('--limit', type=int, default=100)
    args = parser.parse_args()

    statements = _pdfs(args.statements)
    if not statements:
        print('error=no bank statement PDFs found')
        return 2

    with tempfile.TemporaryDirectory(prefix='flow-recurring-stage-') as tmp:
        db_path = Path(tmp) / 'flow.db'
        _fresh_db(db_path)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys = ON')
        ensure_import_schema(conn)
        ensure_identity_schema(conn)
        ensure_intelligence_schema(conn)

        account_id = conn.execute(
            "INSERT INTO accounts(name,kind,is_active,include_in_safe_to_spend) VALUES('LCL staging','checking',1,1)"
        ).lastrowid

        imported_transactions = 0
        statement_errors = 0
        for path in statements:
            try:
                data = path.read_bytes()
                source_type, bank, rows = parse_statement(path.name, data)
                metadata = statement_metadata(data, bank, rows)
                cur = conn.execute(
                    '''INSERT INTO imports(account_id,filename,source_type,bank,status,total_rows,period_start,period_end,
                       opening_balance_cents,closing_balance_cents,debit_total_cents,credit_total_cents)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (account_id, path.name, source_type, bank, 'processing', len(rows), metadata.get('period_start'),
                     metadata.get('period_end'), metadata.get('opening_balance_cents'), metadata.get('closing_balance_cents'),
                     metadata.get('debit_total_cents') or 0, metadata.get('credit_total_cents') or 0),
                )
                result = import_rows_occurrence_safe(conn, cur.lastrowid, account_id, rows)
                conn.execute("UPDATE imports SET status='completed',imported_rows=?,duplicate_rows=?,review_rows=? WHERE id=?",
                             (result['imported'], result['duplicates'], result['review'], cur.lastrowid))
                imported_transactions += result['imported']
            except Exception as exc:
                statement_errors += 1
                print(f'statement_warning={path.name}: {exc}')

        conn.commit()
        result = detect_recurring_transactions(conn, account_id)
        conn.commit()

        rows = conn.execute('''
            SELECT r.id,r.label,r.merchant_key,r.amount_cents,r.usual_day,r.day_tolerance,
                   r.amount_min_cents,r.amount_max_cents,r.last_seen_date,r.next_expected_date,
                   r.occurrence_count,r.confidence,r.category,r.detection_status,r.is_active
            FROM recurring_transactions r
            WHERE r.account_id=?
              AND r.detection_status IN ('accepted','review_date','review_amount')
            ORDER BY CASE r.detection_status WHEN 'accepted' THEN 0 ELSE 1 END,
                     r.confidence DESC,r.occurrence_count DESC,r.label
            LIMIT ?
        ''', (account_id, max(1, args.limit))).fetchall()

        counts = {'accepted': 0, 'review_date': 0, 'review_amount': 0}
        shown = 0
        for row in rows:
            status = row['detection_status']
            confidence = float(row['confidence'] or 0)
            if status == 'accepted' and confidence < args.min_confidence:
                continue
            counts[status] += 1
            shown += 1
            spread = None
            spread_ratio = None
            if row['amount_min_cents'] is not None and row['amount_max_cents'] is not None:
                spread = row['amount_max_cents'] - row['amount_min_cents']
                spread_ratio = spread / max(1, int(row['amount_max_cents']))
            ratio_text = f'{spread_ratio:.4f}' if spread_ratio is not None else 'None'
            print(
                f"recurring={row['merchant_key']} status={status} active={row['is_active']} "
                f"occurrences={row['occurrence_count']} usual_day={row['usual_day']} day_tolerance={row['day_tolerance']} "
                f"amount={row['amount_cents']} amount_min={row['amount_min_cents']} amount_max={row['amount_max_cents']} "
                f"spread={spread} spread_ratio={ratio_text} confidence={row['confidence']} "
                f"last_seen={row['last_seen_date']} next_expected={row['next_expected_date']} category={row['category']}"
            )

        print(
            f"summary statements={len(statements)} statement_errors={statement_errors} transactions={imported_transactions} "
            f"recurring_detected={result['detected']} recurring_updated={result['updated']} recurring_rows={shown} "
            f"accepted={counts['accepted']} review_date={counts['review_date']} "
            f"review_amount={counts['review_amount']} excluded={result.get('excluded', 0)}"
        )
        conn.close()

        return 1 if statement_errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
