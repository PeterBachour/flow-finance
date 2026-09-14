#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.imports import normalize_label


def tokens(label: str) -> set[str]:
    ignored = {'PRLV','SEPA','CB','VIR','VIREMENT','PERMANENT','COTISATION','MENSUELLE','CARTE'}
    return {t for t in re.findall(r'[A-Z0-9]{3,}', normalize_label(label or '')) if t not in ignored}


def sim(a: str, b: str) -> float:
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def main() -> int:
    p = argparse.ArgumentParser(description='Audit possible successor transactions for stale recurring profiles')
    p.add_argument('--db', type=Path, required=True)
    p.add_argument('--limit', type=int, default=8)
    args = p.parse_args()
    db = args.db.resolve()
    production = (PROJECT_ROOT / 'data' / 'flow.db').resolve()
    if db == production:
        print('error=refusing production db')
        return 2
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    profiles = conn.execute('''
        SELECT id,label,amount_cents,last_seen_date,category,confidence
        FROM recurring_transactions
        WHERE is_active=1 AND detection_status='accepted' AND amount_cents<0
        ORDER BY last_seen_date,label
    ''').fetchall()
    latest = conn.execute('SELECT MAX(booking_date) d FROM transactions').fetchone()['d']
    print(f'db={db} latest_transaction_date={latest}')
    for r in profiles:
        if not r['last_seen_date'] or (date.fromisoformat(latest) - date.fromisoformat(r['last_seen_date'])).days <= 45:
            continue
        candidates = []
        rows = conn.execute('''
            SELECT booking_date,amount_cents,label,category,transaction_type
            FROM transactions
            WHERE booking_date>? AND amount_cents<0 AND is_internal_transfer=0
            ORDER BY booking_date
        ''', (r['last_seen_date'],)).fetchall()
        base_amt = abs(int(r['amount_cents']))
        for tx in rows:
            s = sim(r['label'], tx['label'])
            amt = abs(int(tx['amount_cents']))
            amount_ratio = abs(amt-base_amt) / max(base_amt,1)
            category_match = bool(r['category'] and tx['category'] and r['category'] == tx['category'])
            if s < 0.25 and amount_ratio > 0.25 and not category_match:
                continue
            score = 0.55*s + 0.30*max(0.0, 1.0-min(amount_ratio,1.0)) + (0.15 if category_match else 0.0)
            candidates.append((score, tx))
        candidates.sort(key=lambda x: (-x[0], x[1]['booking_date']))
        print(f"profile label={r['label']} amount={base_amt/100:.2f} last_seen={r['last_seen_date']} confidence={r['confidence']}")
        if not candidates:
            print('  successor=none')
            continue
        for score, tx in candidates[:max(1,args.limit)]:
            print(f"  successor score={score:.3f} date={tx['booking_date']} amount={abs(int(tx['amount_cents']))/100:.2f} label={tx['label']} category={tx['category']}")
    conn.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
