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
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def classify_merchant(merchant: str) -> tuple[str, str | None, float, str]:
    text = merchant.upper()

    # Deterministic / near-deterministic merchant families. Only descriptors
    # whose financial semantic is explicit enough for direct automation belong
    # in auto_classifiable.
    rules = [
        ('DIRECTION GENERALE DES FINANCES PUBLIQUE', 'auto_classifiable', 'Impôts', 0.99, 'explicit French tax authority debit'),
        ('TCL 69 LYO', 'auto_classifiable', 'Transport', 0.99, 'explicit Lyon public transport descriptor'),
        ('APPLE.COM/BILL', 'auto_classifiable', 'Services numériques', 0.95, 'explicit Apple billing descriptor'),
        ('VELIB METROPOLE', 'auto_classifiable', 'Transport', 0.99, 'explicit Vélib merchant'),
        ('RIE PEREIRE', 'auto_classifiable', 'Restaurants', 0.97, 'company restaurant descriptor'),
        ('LOUBNANI', 'auto_classifiable', 'Restaurants', 0.95, 'restaurant merchant identity'),
        ('KR POKE', 'auto_classifiable', 'Restaurants', 0.95, 'restaurant merchant identity'),
        ('BRASSERIE', 'auto_classifiable', 'Restaurants', 0.95, 'brasserie merchant identity'),
        ('BEERHOUSE', 'auto_classifiable', 'Restaurants', 0.92, 'food and beverage merchant identity'),
        ('FIVE GUYS', 'auto_classifiable', 'Restaurants', 0.99, 'known restaurant chain'),
        ('POKAWA', 'auto_classifiable', 'Restaurants', 0.99, 'known restaurant chain'),
        ('NEWREST WAGONS', 'auto_classifiable', 'Restaurants', 0.95, 'on-board catering merchant'),
        ('PAYBYPHONE', 'auto_classifiable', 'Transport', 0.99, 'parking payment service'),
        ('LEROY MERLIN', 'auto_classifiable', 'Shopping', 0.99, 'home improvement retailer'),
        ('AREAS PARIS', 'probable_review', 'Restaurants', 0.88, 'station catering operator descriptor but purchase nature may vary'),
        ('AREAS ANGERS', 'probable_review', 'Restaurants', 0.88, 'station catering operator descriptor but purchase nature may vary'),
        ('FRESHFOO', 'probable_review', 'Restaurants', 0.88, 'food merchant descriptor'),
        ('TASTER SAS', 'probable_review', 'Restaurants', 0.88, 'food merchant descriptor'),
        ('DOLE OPTIC', 'probable_review', 'Santé', 0.90, 'optician descriptor but reimbursement context may matter'),
        ('JOE FLEURS', 'probable_review', 'Shopping', 0.85, 'florist descriptor'),
        ('AMAZON PAYMENTS', 'probable_review', 'Shopping', 0.85, 'merchant family clear but purchase nature may vary'),
        ('THEFRENCHYDENTIS', 'probable_review', 'Santé', 0.90, 'health provider descriptor but high-value exceptional treatment possible'),
        ('SIXT', 'probable_review', 'Transport', 0.90, 'car rental merchant; likely exceptional travel spend'),
        ('HOTEL', 'probable_review', 'Voyage', 0.88, 'hotel descriptor; travel vs exceptional classification depends on model policy'),
        ('AIRBNB', 'probable_review', 'Voyage', 0.90, 'lodging platform'),
        ('SHOTGUN', 'probable_review', 'Loisirs', 0.90, 'event ticketing descriptor'),
        ('SPORT TICKETING', 'probable_review', 'Loisirs', 0.90, 'ticketing descriptor'),
        ('FNAC', 'probable_review', 'Shopping', 0.88, 'retail category broad'),
        ('LDLC', 'probable_review', 'Shopping', 0.90, 'electronics retailer'),
        ('ZALANDO', 'probable_review', 'Shopping', 0.95, 'fashion retailer'),
    ]
    for pattern, tier, category, confidence, reason in rules:
        if pattern in text:
            return tier, category, confidence, reason

    probable_restaurant_tokens = (
        'CAFE', 'BAR ', 'BRASSERIE', 'DELICES', 'TAVERNE', 'NAUTES', 'FELICITA', 'EMBARCADERE',
        'FOOD AND BEV', 'POKE', 'RESTAURANT', 'MEAT ', 'PERLE', 'CHEZ ', 'FRESHFOO', 'TASTER',
    )
    if any(token in f' {text} ' for token in probable_restaurant_tokens):
        return 'probable_review', 'Restaurants', 0.82, 'merchant name strongly suggests food/beverage but is not deterministic enough'

    return 'ambiguous', None, 0.50, 'merchant identity insufficient for safe automatic categorization'


def main() -> int:
    parser = argparse.ArgumentParser(description='Review repeated unclassified merchant groups by automation safety tier')
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--as-of', required=True, help='YYYY-MM-DD')
    args = parser.parse_args()

    db_path = args.db.resolve()
    if not db_path.exists():
        print(f'error=db not found: {db_path}')
        return 3

    as_of = date.fromisoformat(args.as_of)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    rows = conn.execute('''
        SELECT id,booking_date,amount_cents,label
        FROM transactions
        WHERE booking_date>=date(?, '-6 months', 'start of month')
          AND booking_date<date(?, 'start of month')
          AND amount_cents<0
          AND COALESCE(status,'confirmed')='confirmed'
          AND COALESCE(is_internal_transfer,0)=0
          AND (category IS NULL OR trim(category)='')
        ORDER BY booking_date,id
    ''', (as_of.isoformat(), as_of.isoformat())).fetchall()

    groups: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        groups[normalize_merchant(row['label'])].append(row)

    repeated = [(merchant, txs) for merchant, txs in groups.items() if len(txs) >= 2]
    repeated.sort(key=lambda item: -sum(abs(int(r['amount_cents'])) for r in item[1]))

    totals = defaultdict(lambda: {'rows': 0, 'amount': 0, 'groups': 0})
    print(f'db={db_path}')
    print(f'as_of={as_of.isoformat()} repeated_groups={len(repeated)}')
    print('--- repeated merchant review tiers ---')
    for merchant, txs in repeated:
        tier, category, confidence, reason = classify_merchant(merchant)
        amount = sum(abs(int(r['amount_cents'])) for r in txs)
        totals[tier]['rows'] += len(txs)
        totals[tier]['amount'] += amount
        totals[tier]['groups'] += 1
        sample = ' | '.join(sorted({r['label'] for r in txs})[:3])
        print(
            f'merchant={merchant} tier={tier} proposed_category={category} confidence={confidence:.2f} '
            f'rows={len(txs)} amount={euros(amount)} first={min(r["booking_date"] for r in txs)} '
            f'last={max(r["booking_date"] for r in txs)} reason={reason} samples={sample}'
        )

    print('--- tier summary ---')
    for tier in ('auto_classifiable', 'probable_review', 'ambiguous'):
        data = totals[tier]
        print(f'tier={tier} groups={data["groups"]} rows={data["rows"]} amount={euros(data["amount"])}')

    auto = totals['auto_classifiable']
    probable = totals['probable_review']
    ambiguous = totals['ambiguous']
    print('--- interpretation ---')
    print('rule=audit_only_no_database_mutation')
    print('rule=only_auto_classifiable_is_candidate_for_direct_deterministic_application')
    print('rule=probable_review_must_not_be_auto_applied_without_explicit_validation_or_stronger_merchant_evidence')
    print('rule=ambiguous_remains_unclassified')
    print(
        f'summary auto_groups={auto["groups"]} auto_rows={auto["rows"]} auto_amount={euros(auto["amount"])} '
        f'probable_groups={probable["groups"]} probable_rows={probable["rows"]} probable_amount={euros(probable["amount"])} '
        f'ambiguous_groups={ambiguous["groups"]} ambiguous_rows={ambiguous["rows"]} ambiguous_amount={euros(ambiguous["amount"])} '
        f'integrity={conn.execute("PRAGMA integrity_check").fetchone()[0]}'
    )
    conn.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
