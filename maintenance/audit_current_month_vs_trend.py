#!/usr/bin/env python3
from __future__ import annotations

import argparse
import calendar
import sqlite3
from datetime import date
from pathlib import Path
from statistics import mean, median

PROJECT_ROOT = Path(__file__).resolve().parents[1]

VARIABLE_CATEGORIES = {'Alimentation','Restaurants','Shopping','Loisirs','Santé','Transport'}
FIXED_CATEGORIES = {'Logement','Télécom','Assurances','Crédits','Impôts','Frais bancaires'}
NON_ROUTINE_CATEGORIES = {'Voyage','Dépense exceptionnelle'}
EXCLUDED_CATEGORIES = {'Salaire','Remboursement','Transfert interne','Frais professionnel remboursé','Services numériques','Épargne','Investissement'}
FIXED_VARIABLE_CATEGORY_PATTERNS = {'Transport': ('NAVIGO','COMUTITRES','VELIB','VÉLIB')}


def normalize(value: str | None) -> str:
    return ' '.join((value or '').upper().split())


def euros(cents: int | float | None) -> str:
    if cents is None:
        return 'unavailable'
    return f'{float(cents)/100:.2f}'


def previous_month(y:int,m:int)->tuple[int,int]:
    return (y-1,12) if m==1 else (y,m-1)


def month_keys_before(as_of: date, count: int) -> list[str]:
    y,m = previous_month(as_of.year,as_of.month)
    out=[]
    for _ in range(count):
        out.append(f'{y:04d}-{m:02d}')
        y,m=previous_month(y,m)
    return list(reversed(out))


def classify(row: sqlite3.Row) -> str:
    category=(row['category'] or '').strip()
    label=normalize(row['label'])
    if int(row['is_internal_transfer'] or 0)==1 or category=='Transfert interne':
        return 'internal'
    if int(row['amount_cents'])>=0:
        return 'income'
    if category in NON_ROUTINE_CATEGORIES:
        return 'non_routine'
    if category in FIXED_CATEGORIES:
        return 'fixed'
    if category in VARIABLE_CATEGORIES:
        if any(p in label for p in FIXED_VARIABLE_CATEGORY_PATTERNS.get(category,())):
            return 'fixed'
        return 'variable'
    if category in EXCLUDED_CATEGORIES:
        return 'excluded'
    if not category:
        return 'unknown'
    return 'other_classified'


def main() -> int:
    parser=argparse.ArgumentParser(description='Audit current partial month against historical routine spending trend.')
    parser.add_argument('--db',type=Path,required=True)
    parser.add_argument('--as-of',required=True)
    parser.add_argument('--history-months',type=int,default=6)
    args=parser.parse_args()

    db=args.db.resolve()
    production=(PROJECT_ROOT/'data'/'flow.db').resolve()
    if db==production:
        print('error=refusing to audit production flow.db')
        return 2
    if not db.exists():
        print(f'error=db not found: {db}')
        return 3

    as_of=date.fromisoformat(args.as_of)
    history=month_keys_before(as_of,max(3,args.history_months))
    start=f'{history[0]}-01'
    month_start=as_of.replace(day=1)

    conn=sqlite3.connect(db)
    conn.row_factory=sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')

    source_coverage_end = conn.execute("SELECT MAX(booking_date) FROM transactions WHERE source_type='bank_statement'").fetchone()[0]
    source_coverage_end_date = date.fromisoformat(source_coverage_end) if source_coverage_end else None
    current_month_observed = bool(source_coverage_end_date and source_coverage_end_date >= month_start)
    observed_through = min(as_of, source_coverage_end_date) if current_month_observed and source_coverage_end_date else None

    query_end = as_of.isoformat() if current_month_observed else (source_coverage_end or as_of.isoformat())
    rows=conn.execute('''
        SELECT booking_date,amount_cents,label,category,is_internal_transfer,status,source_type
        FROM transactions
        WHERE booking_date>=? AND booking_date<=?
          AND COALESCE(status,'confirmed')='confirmed'
        ORDER BY booking_date,id
    ''',(start,query_end)).fetchall()

    hist={m:{'variable':0,'unknown':0,'fixed':0,'non_routine':0} for m in history}
    current={'variable':0,'unknown':0,'fixed':0,'non_routine':0}
    current_month=f'{as_of.year:04d}-{as_of.month:02d}'
    for row in rows:
        key=row['booking_date'][:7]
        kind=classify(row)
        amount=abs(int(row['amount_cents']))
        bucket=current if current_month_observed and key==current_month else hist.get(key)
        if bucket is None:
            continue
        if kind in bucket:
            bucket[kind]+=amount

    variable_months=[hist[m]['variable'] for m in history]
    variable_daily=[]
    for m in history:
        y,mo=map(int,m.split('-'))
        variable_daily.append(hist[m]['variable']/calendar.monthrange(y,mo)[1])

    baseline_month_median=median(variable_months) if variable_months else 0
    baseline_daily_median=median(variable_daily) if variable_daily else 0
    baseline_daily_avg=mean(variable_daily) if variable_daily else 0

    total_days=calendar.monthrange(as_of.year,as_of.month)[1]
    elapsed_days=(observed_through.day if observed_through else 0)

    if current_month_observed and elapsed_days > 0:
        expected_to_date=baseline_daily_median*elapsed_days
        pace_delta=current['variable']-expected_to_date
        pace_delta_pct=(100*pace_delta/expected_to_date) if expected_to_date else 0.0
        projected_full_month=current['variable']+baseline_daily_median*max(0,total_days-elapsed_days)
        projected_delta=projected_full_month-baseline_month_median
        projected_delta_pct=(100*projected_delta/baseline_month_median) if baseline_month_median else 0.0
        known=current['variable']+current['fixed']
        reviewable=known+current['unknown']
        coverage=(100*known/reviewable) if reviewable else 100.0
        confidence='high' if coverage>=90 else ('medium' if coverage>=65 else 'low')
        observation_status='observed'
    else:
        expected_to_date=None
        pace_delta=None
        pace_delta_pct=None
        projected_full_month=None
        projected_delta=None
        projected_delta_pct=None
        coverage=None
        confidence='unavailable'
        observation_status='source_not_current'

    print(f'db={db}')
    print(f'as_of={as_of.isoformat()} current_month={current_month} source_coverage_end={source_coverage_end or "unavailable"} current_month_observed={str(current_month_observed).lower()} observation_status={observation_status}')
    print('--- historical baseline ---')
    for m in history:
        print(f"month={m} variable={euros(hist[m]['variable'])} fixed={euros(hist[m]['fixed'])} unknown={euros(hist[m]['unknown'])} non_routine={euros(hist[m]['non_routine'])}")
    print('--- current month position ---')
    if current_month_observed:
        print(f"observed_through={observed_through.isoformat()} elapsed_observed_days={elapsed_days} variable_mtd={euros(current['variable'])} fixed_mtd={euros(current['fixed'])} unknown_mtd={euros(current['unknown'])} non_routine_mtd={euros(current['non_routine'])} coverage={coverage:.1f}%")
    else:
        print(f'observed_through=unavailable elapsed_observed_days=0 variable_mtd=unavailable fixed_mtd=unavailable unknown_mtd=unavailable non_routine_mtd=unavailable coverage=unavailable')
    print('--- pace vs trend ---')
    print(f'baseline_variable_month_median={euros(baseline_month_median)} baseline_daily_median={euros(baseline_daily_median)} baseline_daily_avg={euros(baseline_daily_avg)}')
    if current_month_observed:
        print(f'expected_variable_to_date={euros(expected_to_date)} actual_variable_to_date={euros(current["variable"])} delta={euros(pace_delta)} delta_pct={pace_delta_pct:.1f}%')
        print(f'projected_variable_full_month={euros(projected_full_month)} projected_vs_baseline_delta={euros(projected_delta)} projected_vs_baseline_pct={projected_delta_pct:.1f}%')
    else:
        print('expected_variable_to_date=unavailable actual_variable_to_date=unavailable delta=unavailable delta_pct=unavailable')
        print('projected_variable_full_month=unavailable projected_vs_baseline_delta=unavailable projected_vs_baseline_pct=unavailable')
    print('--- interpretation ---')
    print('rule=current_partial_month_metrics_require_bank_source_coverage_for_current_month')
    print('rule=no_transactions_is_not_interpreted_as_zero_spending_when_source_is_stale')
    print('rule=non_routine_and_unknown_outflows_do_not_enter_variable_projection')
    print('rule=coverage_is_reported_only_for_an_observed_current_month')
    integrity=conn.execute('PRAGMA integrity_check').fetchone()[0]
    print(f'summary current_month_observed={str(current_month_observed).lower()} source_coverage_end={source_coverage_end or "unavailable"} current_variable={euros(current["variable"] if current_month_observed else None)} expected_to_date={euros(expected_to_date)} projected_full_month={euros(projected_full_month)} baseline_month_median={euros(baseline_month_median)} coverage={"unavailable" if coverage is None else f"{coverage:.1f}%"} confidence={confidence} integrity={integrity}')
    conn.close()
    return 0 if integrity=='ok' else 5

if __name__=='__main__':
    raise SystemExit(main())
