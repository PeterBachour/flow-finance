#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from audit_unclassified_spending_candidates import classify

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def euros(cents: int | None) -> str:
    return f"{int(cents or 0) / 100:.2f}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Apply only deterministic/high-confidence categories to unclassified staging transactions.'
    )
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--as-of', required=True, help='YYYY-MM-DD')
    args = parser.parse_args()

    db_path = args.db.resolve()
    production = (PROJECT_ROOT / 'data' / 'flow.db').resolve()
    if db_path == production:
        print('error=refusing to modify production flow.db')
        return 2
    if not db_path.exists():
        print(f'error=db not found: {db_path}')
        return 3

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')

    before_count = conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0]
    rows = conn.execute('''
        SELECT id,booking_date,amount_cents,label,category,is_internal_transfer
        FROM transactions
        WHERE booking_date>=date(?, '-6 months', 'start of month')
          AND booking_date<date(?, 'start of month')
          AND amount_cents<0
          AND status='confirmed'
          AND (category IS NULL OR trim(category)='')
        ORDER BY id
    ''', (args.as_of, args.as_of)).fetchall()

    applied = 0
    fixed_rows = 0
    variable_rows = 0
    internal_rows = 0
    applied_amount = 0
    skipped = 0

    for row in rows:
        bucket, category, confidence = classify(row['label'], row['amount_cents'])

        # Only deterministic fixed/transfer patterns (0.99) and explicitly
        # recognised variable merchants (0.90) are applied. Exceptional and
        # generic-card proposals remain untouched for review.
        if bucket == 'fixed_or_reserved' and confidence >= 0.99:
            is_internal = 1 if category == 'Transfert interne' else int(row['is_internal_transfer'] or 0)
            conn.execute(
                'UPDATE transactions SET category=?, is_internal_transfer=? WHERE id=?',
                (category, is_internal, row['id']),
            )
            applied += 1
            fixed_rows += 1
            internal_rows += 1 if is_internal else 0
            applied_amount += abs(int(row['amount_cents']))
        elif bucket == 'variable_candidate' and confidence >= 0.90:
            conn.execute('UPDATE transactions SET category=? WHERE id=?', (category, row['id']))
            applied += 1
            variable_rows += 1
            applied_amount += abs(int(row['amount_cents']))
        else:
            skipped += 1

    conn.commit()

    after_count = conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0]
    remaining_unclassified = conn.execute('''
        SELECT COUNT(*), COALESCE(SUM(ABS(amount_cents)),0)
        FROM transactions
        WHERE booking_date>=date(?, '-6 months', 'start of month')
          AND booking_date<date(?, 'start of month')
          AND amount_cents<0
          AND status='confirmed'
          AND (category IS NULL OR trim(category)='')
    ''', (args.as_of, args.as_of)).fetchone()
    integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]

    print(f'db={db_path}')
    print(f'applied={applied} fixed_rows={fixed_rows} variable_rows={variable_rows} internal_rows={internal_rows} applied_amount={euros(applied_amount)}')
    print(f'skipped_for_review={skipped}')
    print(
        f'remaining_unclassified_rows={remaining_unclassified[0]} '
        f'remaining_unclassified_amount={euros(remaining_unclassified[1])}'
    )
    print(f'transactions_untouched_count before={before_count} after={after_count} unchanged={str(before_count == after_count).lower()}')
    print('rule=only_confidence_0.90_variable_and_0.99_fixed_patterns_applied')
    print('rule=generic_card_and_exceptional_transactions_remain_unmodified')
    print(f'summary integrity={integrity} mode=high_confidence_categorization_only')
    conn.close()
    return 0 if integrity == 'ok' and before_count == after_count else 5


if __name__ == '__main__':
    raise SystemExit(main())
