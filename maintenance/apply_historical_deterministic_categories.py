#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from audit_unclassified_spending_candidates import classify
from apply_auto_classifiable_repeated_merchants import RULES as MERCHANT_RULES, normalize

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def euros(cents: int | None) -> str:
    return f"{int(cents or 0) / 100:.2f}"


def main() -> int:
    parser = argparse.ArgumentParser(description='Apply already validated deterministic categorization rules across full bank history in staging.')
    parser.add_argument('--db', type=Path, required=True)
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
        WHERE amount_cents<0
          AND COALESCE(status,'confirmed')='confirmed'
          AND (category IS NULL OR trim(category)='')
        ORDER BY id
    ''').fetchall()

    applied = 0
    fixed_rows = 0
    variable_rows = 0
    merchant_rows = 0
    internal_rows = 0
    applied_amount = 0

    for row in rows:
        bucket, category, confidence = classify(row['label'], row['amount_cents'])
        applied_here = False
        is_internal = int(row['is_internal_transfer'] or 0)

        if bucket == 'fixed_or_reserved' and confidence >= 0.99:
            is_internal = 1 if category == 'Transfert interne' else is_internal
            conn.execute(
                'UPDATE transactions SET category=?, is_internal_transfer=? WHERE id=?',
                (category, is_internal, row['id']),
            )
            fixed_rows += 1
            internal_rows += 1 if is_internal else 0
            applied_here = True
        elif bucket == 'variable_candidate' and confidence >= 0.90:
            conn.execute('UPDATE transactions SET category=? WHERE id=?', (category, row['id']))
            variable_rows += 1
            applied_here = True
        else:
            text = normalize(row['label'])
            match = next(((pattern, cat) for pattern, cat in MERCHANT_RULES if pattern in text), None)
            if match:
                _, merchant_category = match
                conn.execute('UPDATE transactions SET category=? WHERE id=?', (merchant_category, row['id']))
                merchant_rows += 1
                applied_here = True

        if applied_here:
            applied += 1
            applied_amount += abs(int(row['amount_cents']))

    conn.commit()
    after_count = conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0]
    remaining = conn.execute('''
        SELECT COUNT(*) AS rows,COALESCE(SUM(ABS(amount_cents)),0) AS amount
        FROM transactions
        WHERE amount_cents<0
          AND COALESCE(status,'confirmed')='confirmed'
          AND (category IS NULL OR trim(category)='')
    ''').fetchone()
    integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]

    print(f'db={db_path}')
    print(
        f'applied={applied} fixed_rows={fixed_rows} variable_rows={variable_rows} '
        f'merchant_rows={merchant_rows} internal_rows={internal_rows} applied_amount={euros(applied_amount)}'
    )
    print(f'remaining_unclassified_rows={remaining["rows"]} remaining_unclassified_amount={euros(remaining["amount"])}')
    print(f'transactions_untouched_count before={before_count} after={after_count} unchanged={str(before_count == after_count).lower()}')
    print('rule=only_prevalidated_deterministic_rules_applied_across_full_history')
    print('rule=ambiguous_and_probable_review_merchants_remain_unmodified')
    print(f'summary integrity={integrity} mode=historical_deterministic_categorization_only')
    conn.close()
    return 0 if integrity == 'ok' and before_count == after_count else 5


if __name__ == '__main__':
    raise SystemExit(main())
