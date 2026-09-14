#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.financial_intelligence import build_financial_intelligence


def euros(cents: int | None) -> str:
    return 'unavailable' if cents is None else f'{cents / 100:.2f}'


def main() -> int:
    parser = argparse.ArgumentParser(description='Validate unified financial intelligence against a Flow staging DB.')
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--as-of', required=True, help='YYYY-MM-DD')
    parser.add_argument('--history-months', type=int, default=12)
    args = parser.parse_args()

    db_path = args.db.resolve()
    production = (PROJECT_ROOT / 'data' / 'flow.db').resolve()
    if db_path == production:
        print('error=refusing to validate production flow.db')
        return 2
    if not db_path.exists():
        print(f'error=db not found: {db_path}')
        return 3

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')

    payload = build_financial_intelligence(
        conn,
        as_of=date.fromisoformat(args.as_of),
        history_months=args.history_months,
    )

    headline = payload['headline']
    quality = payload['data_quality']
    current = payload['current_position']
    trends = payload['trends']
    forecast = payload['forecast']
    safe = payload['safe_to_spend']

    safe_value = headline['safe_to_spend_cents']
    forecast_baseline = forecast.get('baseline_safe_to_spend_cents')
    baseline_consistent = safe_value == forecast_baseline
    stale_suppression_ok = (
        quality['current_month_observed']
        or (
            current['variable_mtd_cents'] is None
            and current['projected_full_month_cents'] is None
            and current['confidence'] == 'unavailable'
        )
    )
    integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]

    print(f'db={db_path}')
    print(f"as_of={payload['as_of']}")
    print('--- headline ---')
    print(f"safe_to_spend={euros(safe_value)}")
    print(f"expected_remaining={euros(headline['expected_remaining_at_horizon_cents'])}")
    print(f"next_salary_date={headline['next_salary_date']}")
    print(f"variable_daily_rate={euros(headline['variable_daily_rate_cents'])}")
    print(f"historical_variable_month_median_6m={euros(headline['historical_variable_month_median_cents'])}")
    print('--- data quality ---')
    print(f"bank_coverage_end={quality['bank_coverage_end']}")
    print(f"current_month_observed={str(quality['current_month_observed']).lower()}")
    print(f"freshness_status={quality['freshness_status']}")
    print(f"historical_coverage={quality['historical_coverage_pct']:.1f}%")
    print(f"trend_confidence={quality['trend_confidence']}")
    print(f"current_month_confidence={current['confidence']}")
    print('--- consistency ---')
    print(f'forecast_safe_to_spend_consistent={str(baseline_consistent).lower()}')
    print(f'current_month_stale_suppression_ok={str(stale_suppression_ok).lower()}')
    print(f"safe_balance={euros(safe.get('balance_cents'))}")
    print(f"trend_12m_variable_median={euros(trends['windows']['12m']['variable_median_cents'])}")
    print(
        f'summary safe_to_spend={euros(safe_value)} '
        f'expected_remaining={euros(headline["expected_remaining_at_horizon_cents"])} '
        f'next_salary_date={headline["next_salary_date"]} '
        f'bank_coverage_end={quality["bank_coverage_end"]} '
        f'current_month_observed={str(quality["current_month_observed"]).lower()} '
        f'trend_6m_variable_median={euros(trends["windows"]["6m"]["variable_median_cents"])} '
        f'trend_12m_coverage={quality["historical_coverage_pct"]:.1f}% '
        f'trend_confidence={quality["trend_confidence"]} '
        f'current_month_confidence={current["confidence"]} '
        f'forecast_consistent={str(baseline_consistent).lower()} '
        f'stale_guard={str(stale_suppression_ok).lower()} integrity={integrity}'
    )

    conn.close()
    return 0 if integrity == 'ok' and baseline_consistent and stale_suppression_ok else 5


if __name__ == '__main__':
    raise SystemExit(main())
