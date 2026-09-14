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
from app.recurrence_aliases import alias_group_for_label


def month_index(value: str) -> int:
    y, m = (int(v) for v in value[:7].split('-', 1))
    return y * 12 + m


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
    if value.startswith('CB '):
        return 'card'
    if value.startswith(('PRET ', 'ECHEANCE PRET', 'MENSUALITE PRET')):
        return 'loan'
    return 'other'


def commitment_kind(key: str, label: str, rail: str) -> tuple[str, str]:
    value = normalize_label(label or '')
    key_value = normalize_label(key or '')

    # Explicitly known household/budget funding destination. It is not
    # consumption, but it is a recurring cash commitment and must be reserved
    # by Safe-to-spend when active.
    if 'COMPTE JOINT' in value or 'COMPTE JOINT' in key_value:
        return 'budget_transfer', 'joint-account funding commitment'

    if rail == 'direct_debit':
        return 'contractual', 'SEPA direct debit'
    if rail == 'bank_fee':
        return 'contractual', 'bank fee/subscription'
    if rail == 'standing_transfer':
        return 'contractual', 'standing transfer'
    if rail == 'loan':
        return 'contractual', 'loan payment'

    # Confirmed alias histories can represent subscriptions even when they were
    # historically paid by card. Keep them reviewable, never auto-activate.
    if key.startswith('ALIAS:'):
        return 'known_alias', 'confirmed recurring alias history'

    if rail == 'card':
        return 'spending_habit', 'card merchant repetition is not a contractual recurrence by itself'
    if rail == 'transfer':
        return 'person_transfer', 'ordinary transfer repetition is not contractual by itself'
    return 'uncertain', 'repeated outflow with no contractual payment rail'


def lifecycle(*, last_seen: date, latest_date: date, months: int, coverage: float) -> str:
    age = (latest_date - last_seen).days
    if age <= 45 and months >= 2:
        return 'active'
    if age <= 90 and months >= 2:
        return 'recent_review'
    if months >= 3 and coverage >= 0.55:
        return 'historical'
    return 'weak_history'


def main() -> int:
    parser = argparse.ArgumentParser(description='Audit recurring cash commitments separately from spending habits')
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
    excluded_internal = 0
    for row in rows:
        if row['is_internal_transfer']:
            excluded_internal += 1
            continue
        alias = alias_group_for_label(row['label'])
        key = f'ALIAS:{alias}' if alias else merchant_key(row['label'])
        grouped[key].append(row)

    records: list[dict] = []
    for key, items in grouped.items():
        if len(items) < args.min_occurrences:
            continue
        dates = [date.fromisoformat(r['booking_date']) for r in items]
        months_idx = sorted({month_index(r['booking_date']) for r in items})
        month_count = len(months_idx)
        span_months = months_idx[-1] - months_idx[0] + 1 if months_idx else 1
        coverage = month_count / max(1, span_months)
        amounts = [abs(int(r['amount_cents'])) for r in items]
        latest_item = max(items, key=lambda r: (r['booking_date'], r['id']))
        rail = rail_for(latest_item['label'])
        kind, reason = commitment_kind(key, latest_item['label'], rail)
        first_seen = min(dates)
        last_seen = max(dates)
        status = lifecycle(last_seen=last_seen, latest_date=latest_date, months=month_count, coverage=coverage)
        records.append({
            'key': key,
            'kind': kind,
            'rail': rail,
            'reason': reason,
            'lifecycle': status,
            'count': len(items),
            'months': month_count,
            'coverage': coverage,
            'first': first_seen,
            'last': last_seen,
            'age': (latest_date - last_seen).days,
            'median': int(round(median(amounts))),
            'min': min(amounts),
            'max': max(amounts),
            'label': latest_item['label'],
        })

    priority = {
        'contractual': 0,
        'budget_transfer': 1,
        'known_alias': 2,
        'uncertain': 3,
        'person_transfer': 4,
        'spending_habit': 5,
    }
    life_rank = {'active': 0, 'recent_review': 1, 'historical': 2, 'weak_history': 3}
    records.sort(key=lambda r: (priority.get(r['kind'], 9), life_rank[r['lifecycle']], -r['months'], -r['count'], r['key']))

    print(f'db={db_path} latest_transaction_date={latest_date.isoformat()}')
    print(f'excluded_internal_rows={excluded_internal}')
    print('--- recurring commitments ---')
    for r in records:
        if r['kind'] == 'spending_habit':
            continue
        print(
            f"commitment kind={r['kind']} lifecycle={r['lifecycle']} rail={r['rail']} key={r['key']} "
            f"count={r['count']} months={r['months']} coverage={r['coverage']:.3f} "
            f"first={r['first'].isoformat()} last={r['last'].isoformat()} age_days={r['age']} "
            f"median={r['median']/100:.2f} min={r['min']/100:.2f} max={r['max']/100:.2f} "
            f"reason={r['reason']} label={r['label']}"
        )

    counts = defaultdict(int)
    for r in records:
        counts[(r['kind'], r['lifecycle'])] += 1

    print('--- spending habits excluded from commitments ---')
    habits = [r for r in records if r['kind'] == 'spending_habit' and r['lifecycle'] in {'active', 'recent_review'}]
    for r in habits:
        print(
            f"habit lifecycle={r['lifecycle']} key={r['key']} count={r['count']} months={r['months']} "
            f"median={r['median']/100:.2f} last={r['last'].isoformat()} label={r['label']}"
        )

    active_contractual = sum(v for (kind, life), v in counts.items() if kind == 'contractual' and life == 'active')
    active_budget = sum(v for (kind, life), v in counts.items() if kind == 'budget_transfer' and life == 'active')
    recent_review = sum(v for (kind, life), v in counts.items() if kind in {'contractual', 'budget_transfer', 'known_alias', 'uncertain'} and life == 'recent_review')
    historical_contractual = sum(v for (kind, life), v in counts.items() if kind in {'contractual', 'budget_transfer', 'known_alias'} and life == 'historical')
    print(
        f'summary active_contractual={active_contractual} active_budget_transfers={active_budget} '
        f'recent_commitment_review={recent_review} historical_contractual={historical_contractual} '
        f'active_or_recent_spending_habits_excluded={len(habits)} integrity={conn.execute("PRAGMA integrity_check").fetchone()[0]}'
    )
    conn.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
