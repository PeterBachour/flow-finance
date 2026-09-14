#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sqlite3
from collections import defaultdict
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def euros(cents: int | None) -> str:
    return f"{int(cents or 0) / 100:.2f}"


def normalize_merchant(label: str | None) -> str:
    text = ' '.join((label or '').upper().split())
    text = re.sub(r'^CB\s+', '', text)
    text = re.sub(r'\s+\d{2}/\d{2}/\d{2}$', '', text)
    text = re.sub(r'\s+\d+$', '', text)
    text = re.sub(r'\s{2,}', ' ', text).strip()
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description='Audit unknown historical outflows by repeated merchant and high-value singleton.')
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--as-of', required=True, help='YYYY-MM-DD')
    parser.add_argument('--months', type=int, default=12)
    args = parser.parse_args()

    db_path = args.db.resolve()
    production = (PROJECT_ROOT / 'data' / 'flow.db').resolve()
    if db_path == production:
        print('error=refusing to audit production flow.db')
        return 2
    if not db_path.exists():
        print(f'error=db not found: {db_path}')
        return 3

    as_of = date.fromisoformat(args.as_of)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')

    rows = conn.execute('''
        SELECT id,booking_date,amount_cents,label,transaction_type,is_internal_transfer,source_type
        FROM transactions
        WHERE booking_date>=date(?, ?, 'start of month')
          AND booking_date<date(?, 'start of month')
          AND amount_cents<0
          AND COALESCE(status,'confirmed')='confirmed'
          AND is_internal_transfer=0
          AND (category IS NULL OR trim(category)='')
        ORDER BY booking_date,id
    ''', (as_of.isoformat(), f'-{int(args.months)} months', as_of.isoformat())).fetchall()

    groups: dict[str, dict] = defaultdict(lambda: {'rows': 0, 'amount': 0, 'first': None, 'last': None, 'samples': []})
    for row in rows:
        merchant = normalize_merchant(row['label']) or '(blank)'
        g = groups[merchant]
        amount = abs(int(row['amount_cents']))
        g['rows'] += 1
        g['amount'] += amount
        g['first'] = row['booking_date'] if g['first'] is None else min(g['first'], row['booking_date'])
        g['last'] = row['booking_date'] if g['last'] is None else max(g['last'], row['booking_date'])
        if len(g['samples']) < 3 and row['label'] not in g['samples']:
            g['samples'].append(row['label'])

    repeated = [(m, g) for m, g in groups.items() if g['rows'] >= 2]
    repeated.sort(key=lambda item: (-item[1]['amount'], -item[1]['rows'], item[0]))
    singletons = [(m, g) for m, g in groups.items() if g['rows'] == 1]
    singletons.sort(key=lambda item: (-item[1]['amount'], item[0]))

    total_amount = sum(abs(int(r['amount_cents'])) for r in rows)
    repeated_amount = sum(g['amount'] for _, g in repeated)
    singleton_amount = sum(g['amount'] for _, g in singletons)

    print(f'db={db_path}')
    print(f'as_of={as_of.isoformat()} months={args.months} unknown_rows={len(rows)} unknown_amount={euros(total_amount)} groups={len(groups)}')
    print('--- repeated unknown merchants ---')
    for merchant, g in repeated[:80]:
        print(
            f"merchant={merchant} rows={g['rows']} amount={euros(g['amount'])} first={g['first']} last={g['last']} "
            f"samples={' | '.join(g['samples'])}"
        )

    print('--- high-value unknown singletons ---')
    for merchant, g in singletons[:40]:
        print(
            f"merchant={merchant} amount={euros(g['amount'])} date={g['first']} samples={' | '.join(g['samples'])}"
        )

    print('--- interpretation ---')
    print('rule=audit_only_no_database_mutation')
    print('rule=repeated_unknown_merchants_are_best_candidates_for_reusable_historical_rules')
    print('rule=high_value_singletons_should_be_reviewed_as_exceptional_or_specific_before_any_trend_use')
    print(
        f'summary repeated_groups={len(repeated)} repeated_rows={sum(g["rows"] for _, g in repeated)} '
        f'repeated_amount={euros(repeated_amount)} singleton_rows={len(singletons)} singleton_amount={euros(singleton_amount)} '
        f'integrity={conn.execute("PRAGMA integrity_check").fetchone()[0]}'
    )
    conn.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
