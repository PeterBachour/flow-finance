#!/usr/bin/env python3
from __future__ import annotations

import argparse
import calendar
import sqlite3
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import mean, median

PROJECT_ROOT = Path(__file__).resolve().parents[1]

VARIABLE_CATEGORIES = {
    'Alimentation', 'Restaurants', 'Shopping', 'Loisirs', 'Santé', 'Transport'
}
FIXED_CATEGORIES = {
    'Logement', 'Télécom', 'Assurances', 'Crédits', 'Impôts', 'Frais bancaires'
}
SAVINGS_CATEGORIES = {'Épargne', 'Investissement'}
NON_SPEND_CATEGORIES = {
    'Salaire', 'Remboursement', 'Transfert interne', 'Frais professionnel remboursé',
    'Services numériques'
}
NON_ROUTINE_CATEGORIES = {'Voyage', 'Dépense exceptionnelle'}
FIXED_VARIABLE_CATEGORY_PATTERNS = {
    'Transport': ('NAVIGO', 'COMUTITRES', 'VELIB', 'VÉLIB'),
}


def euros(cents: int | float | None) -> str:
    return f'{float(cents or 0) / 100:.2f}'


def normalize(value: str | None) -> str:
    return ' '.join((value or '').upper().split())


def previous_month(year: int, month: int) -> tuple[int, int]:
    if month == 1:
        return year - 1, 12
    return year, month - 1


def next_month_key(period: str) -> str | None:
    try:
        year, month = (int(v) for v in period.split('-', 1))
    except Exception:
        return None
    if month == 12:
        return f'{year + 1:04d}-01'
    return f'{year:04d}-{month + 1:02d}'


def complete_months_before(as_of: date, count: int) -> list[str]:
    y, m = previous_month(as_of.year, as_of.month)
    out = []
    for _ in range(max(1, count)):
        out.append(f'{y:04d}-{m:02d}')
        y, m = previous_month(y, m)
    return list(reversed(out))


def matches_fixed_variable_pattern(category: str, label_norm: str) -> bool:
    return any(p in label_norm for p in FIXED_VARIABLE_CATEGORY_PATTERNS.get(category, ()))


def classify_row(row: sqlite3.Row, matched_salary_ids: set[int]) -> str:
    amount = int(row['amount_cents'])
    category = (row['category'] or '').strip()
    tx_type = normalize(row['transaction_type'])
    label_norm = normalize(row['label'])

    if int(row['is_internal_transfer'] or 0) == 1 or category == 'Transfert interne':
        return 'internal_transfer'
    if amount > 0:
        if int(row['id']) in matched_salary_ids or category == 'Salaire':
            return 'salary_income'
        return 'other_income'
    if category in FIXED_CATEGORIES:
        return 'fixed_outflow'
    if category in SAVINGS_CATEGORIES or tx_type in {'SAVING', 'INVESTMENT'}:
        return 'savings_outflow'
    if category in VARIABLE_CATEGORIES:
        if matches_fixed_variable_pattern(category, label_norm):
            return 'fixed_outflow'
        return 'variable_outflow'
    if category in NON_ROUTINE_CATEGORIES:
        return 'non_routine_outflow'
    if category in NON_SPEND_CATEGORIES:
        return 'excluded_outflow'
    if not category:
        return 'unknown_outflow'
    return 'other_classified_outflow'


def pct(num: int, den: int) -> float:
    return (100.0 * num / den) if den else 0.0


def main() -> int:
    parser = argparse.ArgumentParser(description='Audit normalized complete-month historical trends for Flow staging.')
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
    months = complete_months_before(as_of, args.months)
    start = f'{months[0]}-01'
    start_y, start_m = map(int, months[0].split('-'))
    prev_y, prev_m = previous_month(start_y, start_m)
    scan_start = f'{prev_y:04d}-{prev_m:02d}-01'
    y, m = map(int, months[-1].split('-'))
    end = date(y, m, calendar.monthrange(y, m)[1]).isoformat()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')

    salary_matches = conn.execute('''
        SELECT t.id AS transaction_id,t.booking_date,t.amount_cents,p.period AS payroll_period
        FROM payroll_transaction_matches m
        JOIN transactions t ON t.id=m.transaction_id
        JOIN payroll_records p ON p.id=m.payroll_record_id
        WHERE t.booking_date>=? AND t.booking_date<=?
        ORDER BY t.booking_date,t.id
    ''', (scan_start, end)).fetchall()
    matched_salary_ids = {int(row['transaction_id']) for row in salary_matches}
    salary_budget_month = {
        int(row['transaction_id']): next_month_key(row['payroll_period'])
        for row in salary_matches
        if row['payroll_period'] and next_month_key(row['payroll_period'])
    }

    rows = conn.execute('''
        SELECT id,booking_date,amount_cents,label,category,transaction_type,
               is_internal_transfer,status,source_type
        FROM transactions
        WHERE booking_date>=? AND booking_date<=?
          AND COALESCE(status,'confirmed')='confirmed'
        ORDER BY booking_date,id
    ''', (scan_start, end)).fetchall()

    by_month: dict[str, dict[str, int]] = {
        month: defaultdict(int) for month in months
    }

    for row in rows:
        kind = classify_row(row, matched_salary_ids)
        if kind == 'salary_income' and int(row['id']) in salary_budget_month:
            month = salary_budget_month[int(row['id'])]
        else:
            month = row['booking_date'][:7]
        if month not in by_month:
            continue
        amount = abs(int(row['amount_cents']))
        by_month[month][kind] += amount

    print(f'db={db_path}')
    print(f'as_of={as_of.isoformat()} history={start}->{end} complete_months={len(months)}')
    print(f'salary_attribution=payroll_period_plus_one_month matched_salary_rows={len(matched_salary_ids)}')
    print('--- monthly normalized trends ---')

    variable_series = []
    known_consumption_series = []
    salary_series = []
    unknown_series = []
    coverage_series = []
    non_routine_series = []

    for month in months:
        d = by_month[month]
        variable = d['variable_outflow']
        fixed = d['fixed_outflow']
        savings = d['savings_outflow']
        unknown = d['unknown_outflow']
        non_routine = d['non_routine_outflow']
        other_classified = d['other_classified_outflow']
        known_consumption = variable + fixed + other_classified
        salary = d['salary_income']
        other_income = d['other_income']
        internal = d['internal_transfer']
        excluded = d['excluded_outflow']

        # Coverage measures how much reviewable cash outflow is semantically
        # understood. Non-routine outflows improve coverage, but are deliberately
        # excluded from the routine consumption trend itself.
        classified_reviewable = known_consumption + non_routine
        reviewable = classified_reviewable + unknown
        coverage = pct(classified_reviewable, reviewable)

        variable_series.append(variable)
        known_consumption_series.append(known_consumption)
        salary_series.append(salary)
        unknown_series.append(unknown)
        coverage_series.append(coverage)
        non_routine_series.append(non_routine)

        print(
            f'month={month} salary={euros(salary)} other_income={euros(other_income)} '
            f'fixed={euros(fixed)} variable={euros(variable)} savings={euros(savings)} '
            f'non_routine={euros(non_routine)} unknown={euros(unknown)} '
            f'other_classified={euros(other_classified)} internal={euros(internal)} '
            f'excluded={euros(excluded)} known_consumption={euros(known_consumption)} '
            f'coverage={coverage:.1f}%'
        )

    def avg_last(series: list[int], n: int) -> int:
        vals = series[-min(n, len(series)):]
        return int(round(mean(vals))) if vals else 0

    def med_last(series: list[int], n: int) -> int:
        vals = series[-min(n, len(series)):]
        return int(round(median(vals))) if vals else 0

    print('--- trailing trends ---')
    for n in (3, 6, 12):
        if len(months) < min(n, 3):
            continue
        print(
            f'window={min(n, len(months))}m '
            f'variable_avg={euros(avg_last(variable_series, n))} '
            f'variable_median={euros(med_last(variable_series, n))} '
            f'known_consumption_avg={euros(avg_last(known_consumption_series, n))} '
            f'non_routine_avg={euros(avg_last(non_routine_series, n))} '
            f'salary_avg={euros(avg_last(salary_series, n))} '
            f'unknown_avg={euros(avg_last(unknown_series, n))} '
            f'coverage_avg={mean(coverage_series[-min(n, len(coverage_series)):]):.1f}%'
        )

    current_variable = variable_series[-1] if variable_series else 0
    baseline_6m_variable = med_last(variable_series[:-1] if len(variable_series) > 1 else variable_series, 6)
    delta = current_variable - baseline_6m_variable
    delta_pct = (100.0 * delta / baseline_6m_variable) if baseline_6m_variable else 0.0

    total_known = sum(known_consumption_series)
    total_non_routine = sum(non_routine_series)
    total_unknown = sum(unknown_series)
    overall_coverage = pct(total_known + total_non_routine, total_known + total_non_routine + total_unknown)
    confidence = 'high' if overall_coverage >= 90 else ('medium' if overall_coverage >= 65 else 'low')

    print('--- current position vs recent trend ---')
    print(
        f'latest_complete_month={months[-1]} variable={euros(current_variable)} '
        f'prior_6m_variable_median={euros(baseline_6m_variable)} '
        f'delta={euros(delta)} delta_pct={delta_pct:.1f}%'
    )
    print('--- interpretation ---')
    print('rule=complete_months_only_current_partial_month_excluded')
    print('rule=reconciled_salary_is_attributed_from_payroll_period_to_following_budget_month')
    print('rule=bank_posting_on_first_days_does_not_shift_salary_two_budget_months_forward')
    print('rule=generic_employer_credits_are_not_assumed_to_be_salary')
    print('rule=internal_transfers_and_savings_are_separated_from_consumption')
    print('rule=travel_and_explicit_exceptional_outflows_are_classified_but_excluded_from_routine_consumption')
    print('rule=unknown_outflows_remain_visible_and_are_not_silently_classified')
    print('rule=trend_confidence_is_based_on_amount_coverage_not_row_count')
    print(
        f'summary months={len(months)} known_consumption={euros(total_known)} '
        f'non_routine={euros(total_non_routine)} unknown_outflows={euros(total_unknown)} '
        f'coverage={overall_coverage:.1f}% latest_variable={euros(current_variable)} '
        f'prior_6m_variable_median={euros(baseline_6m_variable)} '
        f'confidence={confidence} integrity={conn.execute("PRAGMA integrity_check").fetchone()[0]}'
    )
    conn.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
