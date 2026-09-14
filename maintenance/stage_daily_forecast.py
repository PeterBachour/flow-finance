#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.forecast import build_validated_daily_forecast


def euros(cents: int | None) -> str:
    if cents is None:
        return 'unavailable'
    return f'{int(cents) / 100:.2f}'


def main() -> int:
    parser = argparse.ArgumentParser(description='Validate Flow daily forecast against a staging database')
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--as-of', required=True, help='YYYY-MM-DD')
    args = parser.parse_args()

    db_path = args.db.resolve()
    production = (PROJECT_ROOT / 'data' / 'flow.db').resolve()
    if db_path == production:
        print('error=refusing to run daily forecast staging validator on production flow.db')
        return 2
    if not db_path.exists():
        print(f'error=db not found: {db_path}')
        return 3

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')

    forecast = build_validated_daily_forecast(conn, as_of=date.fromisoformat(args.as_of))
    print(f'db={db_path}')
    print(
        f"as_of={forecast['as_of']} horizon_end={forecast['horizon_end']} horizon_days={forecast['horizon_days']} "
        f"horizon_mode={forecast['horizon_mode']} next_salary_date={forecast['next_salary_date']}"
    )
    print(
        f"starting_balance={euros(forecast['starting_balance_cents'])} "
        f"baseline_safe_to_spend={euros(forecast['baseline_safe_to_spend_cents'])} "
        f"protected_static={euros(forecast['protected_static_cents'])} "
        f"dated_commitments={euros(forecast['dated_commitments_cents'])} "
        f"daily_budget={euros(forecast['daily_budget_cents'])}"
    )
    print(
        f"variable_daily_rate={euros(forecast['variable_daily_rate_cents'])} "
        f"variable_projection_confidence={forecast['variable_projection_confidence']} "
        f"variable_history_rows={forecast['variable_history_rows']} "
        f"projected_variable_to_horizon={euros(forecast['projected_variable_to_horizon_cents'])} "
        f"expected_remaining_after_variable_spend={euros(forecast['expected_remaining_after_variable_spend_cents'])}"
    )
    print('--- daily forecast ---')
    for row in forecast['timeline']:
        event_text = ';'.join(
            f"{event['type']}:{event['label']}:{euros(event['amount_cents'])}"
            for event in row['events']
        ) or '-'
        print(
            f"day date={row['date']} opening={euros(row['opening_balance_cents'])} "
            f"movement={euros(row['movement_cents'])} closing={euros(row['closing_balance_cents'])} "
            f"protected_static={euros(row['protected_static_cents'])} "
            f"remaining_committed={euros(row['remaining_committed_cents'])} "
            f"safe_to_spend_remaining={euros(row['safe_to_spend_remaining_cents'])} "
            f"expected_variable_spend={euros(row['expected_variable_spend_cents'])} "
            f"expected_safe_after_variable={euros(row['expected_safe_after_variable_cents'])} "
            f"events={event_text}"
        )
    low = forecast['low_point']
    first_safe = forecast['timeline'][0]['safe_to_spend_remaining_cents'] if forecast['timeline'] else None
    last_safe = forecast['timeline'][-1]['safe_to_spend_remaining_cents'] if forecast['timeline'] else None
    baseline = forecast['baseline_safe_to_spend_cents']
    baseline_consistent = first_safe == baseline and last_safe == baseline
    expected_last = forecast['timeline'][-1]['expected_safe_after_variable_cents'] if forecast['timeline'] else None
    expected_consistent = expected_last == forecast['expected_remaining_after_variable_spend_cents']
    print(
        f"summary closing_balance={euros(forecast['closing_balance_cents'])} "
        f"low_point_date={low['date']} low_point_balance={euros(low['balance_cents'])} "
        f"baseline_safe_to_spend={euros(baseline)} "
        f"first_day_safe={euros(first_safe)} last_day_safe={euros(last_safe)} "
        f"baseline_consistent={str(baseline_consistent).lower()} "
        f"projected_variable={euros(forecast['projected_variable_to_horizon_cents'])} "
        f"expected_remaining={euros(expected_last)} "
        f"expected_consistent={str(expected_consistent).lower()} "
        f"variable_confidence={forecast['variable_projection_confidence']} "
        f"daily_budget={euros(forecast['daily_budget_cents'])} "
        f"integrity={conn.execute('PRAGMA integrity_check').fetchone()[0]}"
    )
    conn.close()
    return 0 if baseline_consistent and expected_consistent else 5


if __name__ == '__main__':
    raise SystemExit(main())
