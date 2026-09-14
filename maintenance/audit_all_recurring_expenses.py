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
from app.recurrence_aliases import alias_group_for_label


def month_index(value: str) -> int:
    y, m = (int(v) for v in value[:7].split('-', 1))
    return y * 12 + m


def suggested_status(*, count: int, month_count: int, last_seen: date, latest_date: date, coverage_ratio: float) -> str:
    age = (latest_date - last_seen).days
    if age <= 45 and count >= 2 and month_count >= 2:
        return 'active_candidate'
    if age <= 90 and count >= 2:
        return 'review_recent'
    if coverage_ratio >= 0.55 and month_count >= 3:
        return 'historical_recurring'
    return 'occasional'


def main() -> int:
    parser = argparse.ArgumentParser(description='Audit all recurring-expense candidates in a Flow staging database')
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--min-occurrences', type=int, default=2)
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
        SELECT id,booking_date,amount_cents,label,category,transaction_type,is_internal_transfer
        FROM transactions
        WHERE amount_cents < 0
        ORDER BY booking_date,id
    ''').fetchall()

    grouped: dict[str, list[sqlite3.Row]] = defaultdict(list)
    internal = 0
    for row in rows:
        if row['is_internal_transfer']:
            internal += 1
            continue
        alias = alias_group_for_label(row['label'])
        key = f'ALIAS:{alias}' if alias else merchant_key(row['label'])
        grouped[key].append(row)

    candidates = []
    for key, items in grouped.items():
        if len(items) < args.min_occurrences:
            continue
        dates = [date.fromisoformat(r['booking_date']) for r in items]
        months = sorted({month_index(r['booking_date']) for r in items})
        month_count = len(months)
        span_months = months[-1] - months[0] + 1 if months else 1
        coverage_ratio = month_count / max(1, span_months)
        amounts = [abs(int(r['amount_cents'])) for r in items]
        days = [d.day for d in dates]
        med_day = int(round(median(days)))
        day_tolerance = max(abs(day - med_day) for day in days)
        last_seen = max(dates)
        first_seen = min(dates)
        status = suggested_status(
            count=len(items), month_count=month_count, last_seen=last_seen,
            latest_date=latest_date, coverage_ratio=coverage_ratio,
        )
        candidates.append({
            'key': key,
            'count': len(items),
            'months': month_count,
            'coverage': coverage_ratio,
            'first_seen': first_seen,
            'last_seen': last_seen,
            'age_days': (latest_date - last_seen).days,
            'median_amount': int(round(median(amounts))),
            'min_amount': min(amounts),
            'max_amount': max(amounts),
            'median_day': med_day,
            'day_tolerance': day_tolerance,
            'status': status,
            'sample_label': items[-1]['label'],
            'category': next((r['category'] for r in reversed(items) if r['category']), None),
        })

    rank = {'active_candidate': 0, 'review_recent': 1, 'historical_recurring': 2, 'occasional': 3}
    candidates.sort(key=lambda c: (rank[c['status']], -c['months'], -c['count'], c['key']))

    print(f'db={db_path} latest_transaction_date={latest_date.isoformat()}')
    print(f'excluded_internal_rows={internal}')
    print('--- recurring expense audit ---')
    for c in candidates:
        print(
            f"candidate status={c['status']} key={c['key']} count={c['count']} months={c['months']} "
            f"coverage={c['coverage']:.3f} first={c['first_seen'].isoformat()} last={c['last_seen'].isoformat()} "
            f"age_days={c['age_days']} median={c['median_amount']/100:.2f} min={c['min_amount']/100:.2f} "
            f"max={c['max_amount']/100:.2f} day={c['median_day']} tolerance={c['day_tolerance']} "
            f"category={c['category']} label={c['sample_label']}"
        )

    counts = defaultdict(int)
    for c in candidates:
        counts[c['status']] += 1
    print(
        'summary '
        f"candidates={len(candidates)} active_candidate={counts['active_candidate']} "
        f"review_recent={counts['review_recent']} historical_recurring={counts['historical_recurring']} "
        f"occasional={counts['occasional']} integrity={conn.execute('PRAGMA integrity_check').fetchone()[0]}"
    )
    conn.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
