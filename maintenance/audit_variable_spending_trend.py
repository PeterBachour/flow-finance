#!/usr/bin/env python3
from __future__ import annotations

import argparse
import calendar
import sqlite3
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import mean, median, pstdev

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.safe_to_spend import predict_next_salary_date

VARIABLE_CATEGORIES = {
    'Alimentation',
    'Restaurants',
    'Shopping',
    'Loisirs',
    'Santé',
    'Transport',
}
EXCLUDED_CATEGORIES = {
    'Salaire',
    'Remboursement',
    'Logement',
    'Télécom',
    'Assurances',
    'Crédits',
    'Impôts',
    'Épargne',
    'Investissement',
    'Transfert interne',
    'Frais professionnel remboursé',
    'Frais bancaires',
    'Services numériques',
}
NON_ROUTINE_CATEGORIES = {'Voyage', 'Dépense exceptionnelle'}

FIXED_VARIABLE_CATEGORY_PATTERNS = {
    'Transport': ('NAVIGO', 'COMUTITRES', 'VELIB', 'VÉLIB'),
}


def euros(cents: int | float | None) -> str:
    return f'{float(cents or 0) / 100:.2f}'


def previous_month(year: int, month: int) -> tuple[int, int]:
    if month == 1:
        return year - 1, 12
    return year, month - 1


def month_range_before(as_of: date, count: int) -> list[str]:
    year, month = previous_month(as_of.year, as_of.month)
    result: list[str] = []
    for _ in range(max(1, count)):
        result.append(f'{year:04d}-{month:02d}')
        year, month = previous_month(year, month)
    return list(reversed(result))


def normalize(value: str | None) -> str:
    return ' '.join((value or '').upper().split())


def _matches_validated_recurrence(label_norm: str, recurring_labels: set[str]) -> bool:
    if not label_norm:
        return False
    if label_norm in recurring_labels:
        return True
    return any(len(recurring) >= 5 and recurring in label_norm for recurring in recurring_labels)


def _matches_fixed_variable_pattern(category: str, label_norm: str) -> bool:
    return any(pattern in label_norm for pattern in FIXED_VARIABLE_CATEGORY_PATTERNS.get(category, ()))


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Audit historical variable spending before integrating it into Flow predictive forecast.'
    )
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--as-of', required=True, help='YYYY-MM-DD')
    parser.add_argument('--months', type=int, default=6)
    args = parser.parse_args()

    db_path = args.db.resolve()
    if not db_path.exists():
        print(f'error=db not found: {db_path}')
        return 3

    as_of = date.fromisoformat(args.as_of)
    months = month_range_before(as_of, args.months)
    start = f'{months[0]}-01'
    end_year, end_month = map(int, months[-1].split('-'))
    end = date(end_year, end_month, calendar.monthrange(end_year, end_month)[1]).isoformat()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')

    recurring_labels = {
        normalize(row['label'])
        for row in conn.execute('''
            SELECT label FROM recurring_transactions
            WHERE detection_status='accepted'
              AND amount_cents<0
        ''').fetchall()
        if row['label']
    }

    rows = conn.execute('''
        SELECT id,booking_date,amount_cents,label,category,transaction_type,is_internal_transfer,source_type
        FROM transactions
        WHERE booking_date>=? AND booking_date<=?
          AND amount_cents<0
          AND COALESCE(status,'confirmed')='confirmed'
        ORDER BY booking_date,id
    ''', (start, end)).fetchall()

    included: list[sqlite3.Row] = []
    excluded_counts: defaultdict[str, int] = defaultdict(int)
    excluded_amounts: defaultdict[str, int] = defaultdict(int)
    non_routine: list[sqlite3.Row] = []
    other_classified: list[sqlite3.Row] = []
    truly_unclassified: list[sqlite3.Row] = []

    for row in rows:
        amount = abs(int(row['amount_cents']))
        category = (row['category'] or '').strip()
        label_norm = normalize(row['label'])
        tx_type = normalize(row['transaction_type'])

        if int(row['is_internal_transfer'] or 0) == 1:
            excluded_counts['internal_transfer'] += 1
            excluded_amounts['internal_transfer'] += amount
            continue
        if category in EXCLUDED_CATEGORIES:
            excluded_counts[f'category:{category}'] += 1
            excluded_amounts[f'category:{category}'] += amount
            continue
        if tx_type in {'INCOME', 'REFUND', 'TRANSFER', 'SAVING', 'INVESTMENT'}:
            excluded_counts[f'transaction_type:{tx_type.lower()}'] += 1
            excluded_amounts[f'transaction_type:{tx_type.lower()}'] += amount
            continue
        if _matches_validated_recurrence(label_norm, recurring_labels):
            excluded_counts['validated_recurring_label'] += 1
            excluded_amounts['validated_recurring_label'] += amount
            continue
        if _matches_fixed_variable_pattern(category, label_norm):
            excluded_counts[f'fixed_pattern_in_variable_category:{category}'] += 1
            excluded_amounts[f'fixed_pattern_in_variable_category:{category}'] += amount
            continue
        if category in VARIABLE_CATEGORIES:
            included.append(row)
        elif category in NON_ROUTINE_CATEGORIES:
            non_routine.append(row)
        elif category:
            other_classified.append(row)
        else:
            truly_unclassified.append(row)

    by_month: dict[str, list[sqlite3.Row]] = {m: [] for m in months}
    for row in included:
        by_month[row['booking_date'][:7]].append(row)

    month_totals: list[int] = []
    month_daily_rates: list[float] = []
    print(f'db={db_path}')
    print(f'as_of={as_of.isoformat()} history={start}->{end} complete_months={len(months)}')
    print('--- monthly variable spending ---')
    for m in months:
        year, month = map(int, m.split('-'))
        days = calendar.monthrange(year, month)[1]
        total = sum(abs(int(row['amount_cents'])) for row in by_month[m])
        count = len(by_month[m])
        daily = total / days if days else 0
        month_totals.append(total)
        month_daily_rates.append(daily)
        print(f'month={m} amount={euros(total)} transactions={count} daily_rate={euros(daily)}')

    avg_month = mean(month_totals) if month_totals else 0
    med_month = median(month_totals) if month_totals else 0
    std_month = pstdev(month_totals) if len(month_totals) > 1 else 0
    avg_daily = mean(month_daily_rates) if month_daily_rates else 0
    med_daily = median(month_daily_rates) if month_daily_rates else 0

    predictive_daily = med_daily
    next_salary, salary_mode = predict_next_salary_date(conn, as_of)
    days_to_horizon = max(0, (next_salary - as_of).days - 1) if next_salary else 0
    projected_variable = int(round(predictive_daily * days_to_horizon))

    print('--- category breakdown ---')
    by_category: defaultdict[str, int] = defaultdict(int)
    for row in included:
        by_category[row['category'] or 'Uncategorized'] += abs(int(row['amount_cents']))
    for category, amount in sorted(by_category.items(), key=lambda item: (-item[1], item[0])):
        print(f'category={category} amount={euros(amount)}')

    print('--- exclusions ---')
    for reason in sorted(excluded_counts):
        print(f'excluded reason={reason} rows={excluded_counts[reason]} amount={euros(excluded_amounts[reason])}')

    non_routine_total = sum(abs(int(row['amount_cents'])) for row in non_routine)
    print('--- categorized non-routine spend excluded from predictive model ---')
    for row in sorted(non_routine, key=lambda r: abs(int(r['amount_cents'])), reverse=True)[:20]:
        print(
            f"non_routine date={row['booking_date']} amount={euros(abs(int(row['amount_cents'])))} "
            f"category={row['category']} label={row['label']}"
        )

    other_classified_total = sum(abs(int(row['amount_cents'])) for row in other_classified)
    if other_classified:
        print('--- other categorized spend excluded from variable model ---')
        for row in sorted(other_classified, key=lambda r: abs(int(r['amount_cents'])), reverse=True)[:20]:
            print(
                f"classified_outside_model date={row['booking_date']} amount={euros(abs(int(row['amount_cents'])))} "
                f"category={row['category']} label={row['label']}"
            )

    truly_unclassified_total = sum(abs(int(row['amount_cents'])) for row in truly_unclassified)
    print('--- truly unclassified negative transactions requiring review ---')
    for row in sorted(truly_unclassified, key=lambda r: abs(int(r['amount_cents'])), reverse=True)[:20]:
        print(
            f"unclassified date={row['booking_date']} amount={euros(abs(int(row['amount_cents'])))} "
            f"type={row['transaction_type']} label={row['label']}"
        )

    cv = (std_month / avg_month) if avg_month else 0
    confidence = 'high' if len(months) >= 6 and cv <= 0.35 and len(truly_unclassified) == 0 else (
        'medium' if len(months) >= 4 and cv <= 0.60 else 'low'
    )

    print('--- interpretation ---')
    print('rule=variable_model_uses_only_confirmed_negative_non_internal_transactions_in_validated_variable_categories')
    print('rule=non_routine_categories_are_known_but_intentionally_excluded_from_routine_prediction')
    print('rule=only_blank_category_rows_are_reported_as_unclassified')
    print('rule=predictive_daily_rate_uses_median_complete_month_daily_rate_to_reduce_one_off_outlier_effects')
    print(
        f'summary avg_monthly={euros(avg_month)} median_monthly={euros(med_month)} '
        f'std_monthly={euros(std_month)} avg_daily={euros(avg_daily)} median_daily={euros(med_daily)} '
        f'predictive_daily={euros(predictive_daily)} projected_to_salary={euros(projected_variable)} '
        f'days_to_horizon={days_to_horizon} next_salary={next_salary.isoformat() if next_salary else None} '
        f'salary_mode={salary_mode} variable_rows={len(included)} '
        f'non_routine_rows={len(non_routine)} non_routine_amount={euros(non_routine_total)} '
        f'other_classified_rows={len(other_classified)} other_classified_amount={euros(other_classified_total)} '
        f'unclassified_rows={len(truly_unclassified)} unclassified_amount={euros(truly_unclassified_total)} '
        f'confidence={confidence} integrity={conn.execute("PRAGMA integrity_check").fetchone()[0]}'
    )
    conn.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
