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


def normalize(label: str) -> str:
    return re.sub(r'\s+', ' ', (label or '').upper()).strip()


def classify(label: str, amount_cents: int) -> tuple[str, str, float]:
    text = normalize(label)
    amount = abs(int(amount_cents))

    fixed_patterns = [
        ('PRET IMMOBILIER', 'Crédits'),
        ('COTIS', 'Frais bancaires'),
        ('SFR', 'Télécom'),
        ('NAVIGO', 'Transport'),
        ('PREDICA', 'Investissement'),
        ('CACI', 'Assurances'),
        ('DGFIP', 'Impôts'),
    ]
    for pattern, category in fixed_patterns:
        if pattern in text:
            return 'fixed_or_reserved', category, 0.99

    transfer_patterns = ('VIR INST COMPTE JOINT', 'VIR SEPA M PETER BACHOUR', 'VIR INST PETER BACHOUR')
    if any(pattern in text for pattern in transfer_patterns):
        return 'fixed_or_reserved', 'Transfert interne', 0.99

    variable_patterns = [
        (('MONOPRIX', 'CARREFOUR', 'FRANPRIX', 'AUCHAN', 'LIDL', 'LECLERC', 'PICARD'), 'Alimentation'),
        (('UBER EATS', 'DELIVEROO', 'RESTAURANT', 'CAFE', 'BISTRO', 'FALSTAFF'), 'Restaurants'),
        (('UNIQLO', 'ZARA', 'H&M', 'HM ', 'MANGO', 'CELIO'), 'Shopping'),
        (('UBER', 'BOLT', 'G7 ', 'SNCF', 'RATP'), 'Transport'),
        (('CINEMA', 'UGC', 'PATHE', 'NETFLIX', 'SPOTIFY'), 'Loisirs'),
        (('PHARMAC', 'DOCTOLIB'), 'Santé'),
    ]
    for patterns, category in variable_patterns:
        if any(pattern in text for pattern in patterns):
            return 'variable_candidate', category, 0.90

    exceptional_patterns = (
        'DARTY', 'SIXT', 'CANADIAN EMBASSY', 'THEFRENCHYDENTIS', 'DENTIS', 'AIR FRANCE', 'HOTEL'
    )
    if any(pattern in text for pattern in exceptional_patterns) or amount >= 30000:
        return 'one_off_or_exceptional', 'À revoir', 0.85

    if text.startswith('VIR '):
        return 'review_transfer_or_person', 'À revoir', 0.70

    if text.startswith('CB ') and amount < 30000:
        return 'variable_candidate', 'Non classé variable', 0.55

    return 'needs_review', 'À revoir', 0.40


def main() -> int:
    parser = argparse.ArgumentParser(description='Audit classification candidates for unclassified spending without mutating Flow data')
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--as-of', required=True, help='YYYY-MM-DD')
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
        SELECT id,booking_date,amount_cents,label,category,transaction_type,is_internal_transfer,source_key
        FROM transactions
        WHERE booking_date>=date(?, '-6 months', 'start of month')
          AND booking_date<date(?, 'start of month')
          AND amount_cents<0
          AND status='confirmed'
          AND is_internal_transfer=0
          AND (category IS NULL OR trim(category)='')
        ORDER BY ABS(amount_cents) DESC,booking_date DESC,id DESC
    ''', (as_of.isoformat(), as_of.isoformat())).fetchall()

    groups: dict[str, dict] = defaultdict(lambda: {'rows': 0, 'amount': 0, 'categories': defaultdict(int)})
    proposals = []
    for row in rows:
        bucket, category, confidence = classify(row['label'], row['amount_cents'])
        amount = abs(int(row['amount_cents']))
        groups[bucket]['rows'] += 1
        groups[bucket]['amount'] += amount
        groups[bucket]['categories'][category] += amount
        proposals.append((row, bucket, category, confidence))

    print(f'db={db_path}')
    print(f'as_of={as_of.isoformat()} unclassified_rows={len(rows)} unclassified_amount={euros(sum(abs(int(r["amount_cents"])) for r in rows))}')
    print('--- classification summary ---')
    for bucket in sorted(groups):
        data = groups[bucket]
        print(f'bucket={bucket} rows={data["rows"]} amount={euros(data["amount"])}')
        for category, amount in sorted(data['categories'].items(), key=lambda kv: (-kv[1], kv[0])):
            print(f'  category={category} amount={euros(amount)}')

    print('--- high-confidence proposals ---')
    for row, bucket, category, confidence in proposals:
        if confidence < 0.85:
            continue
        print(
            f"tx id={row['id']} date={row['booking_date']} amount={euros(abs(int(row['amount_cents'])))} "
            f"bucket={bucket} proposed_category={category} confidence={confidence:.2f} label={row['label']}"
        )

    print('--- low-confidence variable candidates ---')
    shown = 0
    for row, bucket, category, confidence in proposals:
        if bucket != 'variable_candidate' or confidence >= 0.85:
            continue
        print(
            f"tx id={row['id']} date={row['booking_date']} amount={euros(abs(int(row['amount_cents'])))} "
            f"proposed_category={category} confidence={confidence:.2f} label={row['label']}"
        )
        shown += 1
        if shown >= 50:
            break

    high_conf_variable = sum(abs(int(row['amount_cents'])) for row, bucket, _cat, confidence in proposals if bucket == 'variable_candidate' and confidence >= 0.85)
    low_conf_variable = sum(abs(int(row['amount_cents'])) for row, bucket, _cat, confidence in proposals if bucket == 'variable_candidate' and confidence < 0.85)
    fixed = sum(abs(int(row['amount_cents'])) for row, bucket, _cat, _confidence in proposals if bucket == 'fixed_or_reserved')
    exceptional = sum(abs(int(row['amount_cents'])) for row, bucket, _cat, _confidence in proposals if bucket == 'one_off_or_exceptional')

    print('--- interpretation ---')
    print('rule=audit_only_no_database_mutation')
    print('rule=high_confidence_patterns_may_be_candidates_for_deterministic_rules_after_review')
    print('rule=generic_card_payments_remain_low_confidence_until merchant mapping is validated')
    print('rule=one_off_or_exceptional_is_excluded_from_recurring_daily_burn_prediction')
    print(
        f'summary high_conf_variable={euros(high_conf_variable)} low_conf_variable={euros(low_conf_variable)} '
        f'fixed_or_reserved={euros(fixed)} one_off_or_exceptional={euros(exceptional)} '
        f'integrity={conn.execute("PRAGMA integrity_check").fetchone()[0]}'
    )
    conn.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
