#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.financial_intelligence import build_financial_intelligence
from app.monthly_finance import month_totals


def euros(cents: int | None) -> str:
    if cents is None:
        return 'n/a'
    return f'{cents / 100:.2f}'


def main() -> int:
    parser = argparse.ArgumentParser(description='Audit current Flow finance cycle, coverage, monthly semantics and Safe-to-Spend.')
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--as-of', default=date.today().isoformat())
    args = parser.parse_args()

    as_of = date.fromisoformat(args.as_of)
    month = as_of.strftime('%Y-%m')
    db = args.db.resolve()
    if not db.exists():
        print(f'error=db not found: {db}')
        return 2

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        statement_end = conn.execute(
            "SELECT MAX(booking_date) d FROM transactions WHERE source_type='bank_statement'"
        ).fetchone()['d']
        activity_end = conn.execute(
            "SELECT MAX(booking_date) d FROM transactions WHERE source_type='bank_activity'"
        ).fetchone()['d']
        any_end = conn.execute(
            "SELECT MAX(booking_date) d FROM transactions WHERE COALESCE(status,'confirmed')='confirmed'"
        ).fetchone()['d']

        month_rows = conn.execute(
            '''SELECT id,booking_date,amount_cents,label,category,source_type
               FROM transactions
               WHERE substr(booking_date,1,7)=?
                 AND COALESCE(status,'confirmed')='confirmed'
               ORDER BY booking_date,id''',
            (month,),
        ).fetchall()
        unknown = [r for r in month_rows if int(r['amount_cents']) < 0 and not (r['category'] or '').strip()]

        totals = month_totals(conn, month)
        intel = build_financial_intelligence(conn, as_of=as_of, history_months=12)
        current = intel['current_position']
        trends = intel['trends']['windows']
        quality = intel['data_quality']
        safe = intel['safe_to_spend']

        print(f'db={db}')
        print(f'as_of={as_of.isoformat()} month={month}')
        print('--- coverage ---')
        print(f'statement_coverage_end={statement_end}')
        print(f'activity_coverage_end={activity_end}')
        print(f'transaction_coverage_end={quality.get("transaction_coverage_end") or any_end}')
        print(f'current_month_observed={quality.get("current_month_observed")}')
        print(f'transaction_freshness={quality.get("transaction_freshness_status")}')
        print(f'balance_as_of={quality.get("balance_as_of")} balance_freshness={quality.get("balance_freshness_status")}')

        print('--- current month ---')
        print(f'rows={len(month_rows)} unknown_rows={len(unknown)} unknown={euros(totals.get("unknown_cents"))}')
        print(f'consumption={euros(totals.get("consumption_cents"))}')
        print(f'fixed={euros(totals.get("fixed_cents"))} variable={euros(totals.get("variable_cents"))}')
        print(f'savings={euros(totals.get("saving_cents"))} exceptional={euros(totals.get("exceptional_cents"))}')
        print(f'transfers={euros(totals.get("transfers_cents"))} cash_outflow={euros(totals.get("cash_outflow_cents"))}')
        print(f'semantic_coverage_pct={totals.get("semantic_coverage_pct")}')

        if unknown:
            print('--- current month unknowns ---')
            for row in unknown:
                print(
                    f"id={row['id']} date={row['booking_date']} amount={abs(int(row['amount_cents']))/100:.2f} "
                    f"source={row['source_type']} label={row['label']}"
                )

        print('--- current position ---')
        print(f'status={current.get("status")} confidence={current.get("confidence")} observed_through={current.get("observed_through")}')
        print(f'variable_mtd={euros(current.get("variable_mtd_cents"))}')
        print(f'expected_to_date={euros(current.get("expected_to_date_cents"))}')
        print(f'projected_full_month={euros(current.get("projected_full_month_cents"))}')
        print(f'baseline_6m_variable_median={euros(current.get("baseline_variable_month_median_cents"))}')

        print('--- trends ---')
        for name in ('3m', '6m', '12m'):
            window = trends[name]
            print(
                f'{name}: variable_avg={euros(window.get("variable_avg_cents"))} '
                f'variable_median={euros(window.get("variable_median_cents"))} '
                f'known_consumption_avg={euros(window.get("known_consumption_avg_cents"))} '
                f'coverage_avg_pct={window.get("coverage_avg_pct")}'
            )

        print('--- safe to spend ---')
        print(f'safe_to_spend={euros(safe.get("safe_to_spend_cents"))}')
        print(f'next_salary_date={safe.get("next_salary_date")}')
        print(f'horizon_end={safe.get("horizon_end")}')
        print(f'safety_reserve={euros(safe.get("safety_reserve_cents"))}')
        print(f'planned_commitments={euros(safe.get("planned_commitments_cents"))}')
        print(f'recurring_commitments={euros(safe.get("recurring_commitments_cents"))}')
        print('integrity=ok')
        return 0
    finally:
        conn.close()


if __name__ == '__main__':
    raise SystemExit(main())
