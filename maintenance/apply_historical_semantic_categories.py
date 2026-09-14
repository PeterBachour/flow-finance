#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Deterministic merchant rules only. These are used to improve historical
# reporting quality without guessing ambiguous merchants.
RULES = (
    # Historical fixed commitments / subscriptions.
    ('PRLV SEPA SARL MAP GESTION', 'Logement'),
    ('PRLV SEPA BNP PARIBAS PERSONAL FINANCE', 'Crédits'),
    ('CANAL PLUS FR', 'Services numériques'),
    ('PRLV SEPA CANAL+ FRANCE', 'Services numériques'),

    # Shopping / retail.
    ('FNAC TERNES', 'Shopping'),
    ('FNAC BEAUGRENELL', 'Shopping'),
    ('IKEA ITALIE', 'Shopping'),
    ('AMAZON EU SARL', 'Shopping'),
    ('AMAZON PAYMENTS', 'Shopping'),
    ('BOULANGER.COM', 'Shopping'),
    ('ZALANDO', 'Shopping'),
    ('RHINOSHIELD', 'Shopping'),
    ('ACTION ', 'Shopping'),

    # Food / restaurants.
    ('INTERMARCHE', 'Alimentation'),
    ('MCDONALDS', 'Restaurants'),
    ('MC DO ', 'Restaurants'),
    ('STARBUCKS', 'Restaurants'),
    ('SUSHI ETOILE', 'Restaurants'),
    ('ENJOY TACOS', 'Restaurants'),
    ('EUREST DELOITTE', 'Restaurants'),
    ('PEPEGUSTO', 'Restaurants'),
    ('SALABAO', 'Restaurants'),
    ('LA FELICITA', 'Restaurants'),
    ('LA TAVERNE PAILL', 'Restaurants'),
    ('GP FOOD AND BEV', 'Restaurants'),
    ('LES NAUTES', 'Restaurants'),
    ('DELICES D\'ORIENT', 'Restaurants'),
    ('L\'EMBARCADERE', 'Restaurants'),

    # Transport.
    ('TRAINLINE', 'Transport'),
    ('IZIVIA', 'Transport'),
    ('BIRD* CAUTION', 'Transport'),

    # Leisure.
    ('SHOTGUN*', 'Loisirs'),
    ('GAITE LYRIQUE', 'Loisirs'),
    ('FVTVR', 'Loisirs'),
    ('LOISIR EPHEMERE', 'Loisirs'),

    # Health providers. Large health transactions are later separated from
    # routine variable spend by the exceptional-value rule below.
    ('THEFRENCHYDENTIS', 'Santé'),
    ('DR KARAM STEPHA', 'Santé'),
    ('DOCTEUR HALOUA', 'Santé'),

    # Travel merchants are tracked separately from routine variable spend.
    ('AIR FRANCE', 'Voyage'),
    ('AIRBNB', 'Voyage'),
    ('BB HOTELS LUXEMB', 'Voyage'),
    ('PARK INN LUXEMBO', 'Voyage'),
    ('AVIS RENT-A-CAR', 'Voyage'),
    ('SIXT', 'Voyage'),
    ('BOOKING.COM', 'Voyage'),
)

# Explicit, known one-off transactions that must not drive the monthly routine
# spending model. We use merchant pattern + minimum amount to avoid broad rules.
EXCEPTIONAL_RULES = (
    ('VIR SEPA SNC COGEDIM PARIS METR', 1_000_000),  # >= 10,000 EUR
    ('DARTY IDF', 100_000),                          # >= 1,000 EUR
    ('THEFRENCHYDENTIS', 50_000),                   # >= 500 EUR
)


def normalize(value: str | None) -> str:
    return ' '.join((value or '').upper().split())


def euros(cents: int | None) -> str:
    return f'{int(cents or 0) / 100:.2f}'


def main() -> int:
    parser = argparse.ArgumentParser(description='Apply deterministic historical semantic categories to a Flow staging DB.')
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
        SELECT id,label,category,amount_cents,booking_date
        FROM transactions
        WHERE amount_cents<0
          AND COALESCE(status,'confirmed')='confirmed'
          AND is_internal_transfer=0
          AND (category IS NULL OR trim(category)='')
        ORDER BY booking_date,id
    ''').fetchall()

    applied = 0
    applied_amount = 0
    exceptional_rows = 0
    exceptional_amount = 0
    by_category: dict[str, dict[str, int]] = {}

    for row in rows:
        label = normalize(row['label'])
        amount_abs = abs(int(row['amount_cents']))

        exceptional = next(
            (pattern for pattern, minimum in EXCEPTIONAL_RULES if pattern in label and amount_abs >= minimum),
            None,
        )
        if exceptional:
            category = 'Dépense exceptionnelle'
            conn.execute('UPDATE transactions SET category=? WHERE id=?', (category, row['id']))
            applied += 1
            applied_amount += amount_abs
            exceptional_rows += 1
            exceptional_amount += amount_abs
            stats = by_category.setdefault(category, {'rows': 0, 'amount': 0})
            stats['rows'] += 1
            stats['amount'] += amount_abs
            continue

        match = next(((pattern, category) for pattern, category in RULES if pattern in label), None)
        if not match:
            continue
        _, category = match
        conn.execute('UPDATE transactions SET category=? WHERE id=?', (category, row['id']))
        applied += 1
        applied_amount += amount_abs
        stats = by_category.setdefault(category, {'rows': 0, 'amount': 0})
        stats['rows'] += 1
        stats['amount'] += amount_abs

    conn.commit()
    after_count = conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0]
    remaining = conn.execute('''
        SELECT COUNT(*) AS rows,COALESCE(SUM(ABS(amount_cents)),0) AS amount
        FROM transactions
        WHERE amount_cents<0
          AND COALESCE(status,'confirmed')='confirmed'
          AND is_internal_transfer=0
          AND (category IS NULL OR trim(category)='')
    ''').fetchone()
    integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]

    print(f'db={db_path}')
    print('--- applied semantic categories ---')
    for category, stats in sorted(by_category.items(), key=lambda item: (-item[1]['amount'], item[0])):
        print(f'category={category} rows={stats["rows"]} amount={euros(stats["amount"])}')
    print(
        f'applied={applied} applied_amount={euros(applied_amount)} '
        f'exceptional_rows={exceptional_rows} exceptional_amount={euros(exceptional_amount)}'
    )
    print(
        f'remaining_unclassified_rows={remaining["rows"]} '
        f'remaining_unclassified_amount={euros(remaining["amount"])}'
    )
    print(f'transactions_untouched_count before={before_count} after={after_count} unchanged={str(before_count == after_count).lower()}')
    print('rule=deterministic_merchants_only')
    print('rule=explicit_high_value_one_offs_are_separated_from_routine_spending')
    print('rule=ambiguous_person_transfers_and_opaque_merchants_remain_unclassified')
    print(f'summary integrity={integrity} mode=historical_semantic_categories')
    conn.close()
    return 0 if integrity == 'ok' and before_count == after_count else 5


if __name__ == '__main__':
    raise SystemExit(main())
