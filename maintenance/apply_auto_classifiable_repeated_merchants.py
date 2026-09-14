#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Only merchants explicitly validated as auto_classifiable by
# audit_repeated_merchant_classification.py on the 2026-09 staging review.
RULES = (
    ('APPLE.COM/BILL', 'Services numériques'),
    ('VELIB METROPOLE', 'Transport'),
    ('LOUBNANI', 'Restaurants'),
    ('LEROY MERLIN', 'Shopping'),
    ('RIE PEREIRE DEB', 'Restaurants'),
    ('KR POKE', 'Restaurants'),
    ('BRASSERIE BRD', 'Restaurants'),
    ('BEERHOUSE', 'Restaurants'),
    ('NEWREST WAGONS-L', 'Restaurants'),
    ('APPLI PAYBYPHONE', 'Transport'),
)


def normalize(value: str | None) -> str:
    return ' '.join((value or '').upper().split())


def main() -> int:
    parser = argparse.ArgumentParser(description='Apply validated auto-classifiable repeated merchant categories to a Flow staging DB')
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

    as_of = date.fromisoformat(args.as_of)
    start = conn_start = f'{as_of.year:04d}-{max(1, as_of.month - 6):02d}-01'

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')

    before_count = conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0]
    rows = conn.execute('''
        SELECT id,label,category,booking_date,amount_cents
        FROM transactions
        WHERE booking_date>=date(?, '-6 months', 'start of month')
          AND booking_date<date(?, 'start of month')
          AND amount_cents<0
          AND COALESCE(status,'confirmed')='confirmed'
          AND is_internal_transfer=0
          AND (category IS NULL OR trim(category)='')
        ORDER BY id
    ''', (as_of.isoformat(), as_of.isoformat())).fetchall()

    applied = 0
    applied_amount = 0
    by_rule: dict[str, dict[str, int]] = {pattern: {'rows': 0, 'amount': 0} for pattern, _ in RULES}

    for row in rows:
        text = normalize(row['label'])
        match = next(((pattern, category) for pattern, category in RULES if pattern in text), None)
        if not match:
            continue
        pattern, category = match
        conn.execute('UPDATE transactions SET category=? WHERE id=?', (category, row['id']))
        amount = abs(int(row['amount_cents']))
        applied += 1
        applied_amount += amount
        by_rule[pattern]['rows'] += 1
        by_rule[pattern]['amount'] += amount

    conn.commit()
    after_count = conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0]
    remaining = conn.execute('''
        SELECT COUNT(*) AS rows,COALESCE(SUM(ABS(amount_cents)),0) AS amount
        FROM transactions
        WHERE booking_date>=date(?, '-6 months', 'start of month')
          AND booking_date<date(?, 'start of month')
          AND amount_cents<0
          AND COALESCE(status,'confirmed')='confirmed'
          AND is_internal_transfer=0
          AND (category IS NULL OR trim(category)='')
    ''', (as_of.isoformat(), as_of.isoformat())).fetchone()
    integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]

    print(f'db={db_path}')
    print('--- applied merchant rules ---')
    for pattern, category in RULES:
        stats = by_rule[pattern]
        print(f'merchant={pattern} category={category} rows={stats["rows"]} amount={stats["amount"]/100:.2f}')
    print(
        f'applied={applied} applied_amount={applied_amount/100:.2f} '
        f'remaining_unclassified_rows={remaining["rows"]} remaining_unclassified_amount={int(remaining["amount"])/100:.2f}'
    )
    print(f'transactions_untouched_count before={before_count} after={after_count} unchanged={str(before_count == after_count).lower()}')
    print('rule=only_prevalidated_auto_classifiable_repeated_merchants_applied')
    print('rule=probable_review_and_ambiguous_merchants_remain_unmodified')
    print(f'summary integrity={integrity} mode=auto_classifiable_repeated_merchants_only')
    conn.close()

    return 0 if integrity == 'ok' and before_count == after_count else 5


if __name__ == '__main__':
    raise SystemExit(main())
