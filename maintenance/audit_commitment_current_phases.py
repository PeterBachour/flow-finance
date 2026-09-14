#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import median

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.data_intelligence import merchant_key
from app.imports import normalize_label


def rail_for(label: str) -> str:
    value = normalize_label(label or '')
    if value.startswith('PRLV'):
        return 'direct_debit'
    if value.startswith('COTISATION'):
        return 'bank_fee'
    if value.startswith(('VIR.PERMANENT', 'VIR PERMANENT')):
        return 'standing_transfer'
    if value.startswith(('VIR ', 'VIREMENT')):
        return 'transfer'
    if value.startswith(('PRET ', 'ECHEANCE PRET', 'MENSUALITE PRET')):
        return 'loan'
    return 'other'


def is_commitment(label: str) -> bool:
    value = normalize_label(label or '')
    if 'COMPTE JOINT' in value:
        return True
    return rail_for(label) in {'direct_debit', 'bank_fee', 'standing_transfer', 'loan'}


def main() -> int:
    parser = argparse.ArgumentParser(description='Audit current phases of recurring commitments in Flow staging')
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--months', type=int, default=6, help='Recent months to inspect for phase detection')
    args = parser.parse_args()

    db_path = args.db.resolve()
    production = (PROJECT_ROOT / 'data' / 'flow.db').resolve()
    if db_path == production:
        print('error=refusing to audit production flow.db')
        return 2
    if not db_path.exists():
        print(f'error=db not found: {db_path}')
        return 3

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')

    latest_raw = conn.execute("SELECT MAX(booking_date) FROM transactions WHERE source_type='bank_statement'").fetchone()[0]
    if not latest_raw:
        print('error=no bank transactions found')
        return 4
    latest_date = date.fromisoformat(latest_raw)

    rows = conn.execute('''
        SELECT id,booking_date,amount_cents,label,is_internal_transfer,source_id
        FROM transactions
        WHERE amount_cents < 0
          AND source_type='bank_statement'
        ORDER BY booking_date,id
    ''').fetchall()

    grouped = defaultdict(list)
    for row in rows:
        if row['is_internal_transfer']:
            continue
        if not is_commitment(row['label']):
            continue
        key = 'VIR INST COMPTE JOINT' if 'COMPTE JOINT' in normalize_label(row['label']) else merchant_key(row['label'])
        grouped[key].append(row)

    print(f'db={db_path} latest_transaction_date={latest_date.isoformat()} recent_months={args.months}')
    print('--- commitment current phases ---')

    for key in sorted(grouped):
        items = grouped[key]
        dates = [date.fromisoformat(r['booking_date']) for r in items]
        last_seen = max(dates)
        age_days = (latest_date - last_seen).days
        if age_days > 90:
            lifecycle = 'historical'
        elif age_days > 45:
            lifecycle = 'recent_review'
        else:
            lifecycle = 'active'

        recent_cutoff_index = latest_date.year * 12 + latest_date.month - max(1, args.months) + 1
        recent = []
        for r in items:
            d = date.fromisoformat(r['booking_date'])
            idx = d.year * 12 + d.month
            if idx >= recent_cutoff_index:
                recent.append(r)
        if not recent:
            recent = items[-min(len(items), 3):]

        recent_amounts = [abs(int(r['amount_cents'])) for r in recent]
        last3 = items[-3:]
        last3_amounts = [abs(int(r['amount_cents'])) for r in last3]
        current_candidate = int(round(median(last3_amounts))) if last3_amounts else 0
        if len(last3_amounts) >= 2 and len(set(last3_amounts)) == 1:
            phase_confidence = 'high'
            phase_reason = 'last occurrences stable'
        elif len(last3_amounts) >= 2 and max(last3_amounts) - min(last3_amounts) <= max(100, int(current_candidate * 0.10)):
            phase_confidence = 'medium'
            phase_reason = 'last occurrences within 10% band'
        else:
            phase_confidence = 'review'
            phase_reason = 'recent amounts vary materially'

        print(
            f"commitment lifecycle={lifecycle} key={key} count={len(items)} last={last_seen.isoformat()} age_days={age_days} "
            f"recent_count={len(recent)} recent_median={median(recent_amounts)/100:.2f} "
            f"current_candidate={current_candidate/100:.2f} phase_confidence={phase_confidence} "
            f"reason={phase_reason} label={items[-1]['label']}"
        )
        for r in items[-6:]:
            print(
                f"  occurrence date={r['booking_date']} amount={abs(int(r['amount_cents']))/100:.2f} "
                f"label={r['label']} source={r['source_id']}"
            )

    print('integrity=' + conn.execute('PRAGMA integrity_check').fetchone()[0])
    conn.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
