from __future__ import annotations

import json
from datetime import date, timedelta

from .forecast_v6 import build_v6_daily_trajectory


SCENARIO_MODES = ('engaged', 'realistic', 'prudent')


def capture_daily_forecast(conn, *, as_of: date | None = None) -> dict:
    """Persist the first valid forecast of a date; repeated captures never overwrite it."""
    observed = as_of or date.today()
    forecast = build_v6_daily_trajectory(conn, as_of=observed)
    availability = forecast.get('availability') or {}
    safe_to_spend = (forecast.get('safe_to_spend') or {}).get('total_cents')
    if not availability.get('available') or safe_to_spend is None:
        return {
            'status': 'unavailable',
            'as_of': observed.isoformat(),
            'reason': availability.get('status') or 'safe_to_spend_unavailable',
            'captured_modes': [],
        }

    account_ids = [
        int(row['id'])
        for row in conn.execute(
            "SELECT id FROM accounts WHERE is_active=1 AND include_in_safe_to_spend=1 ORDER BY id"
        ).fetchall()
    ]
    horizon = str((forecast.get('horizon') or {}).get('end') or '')
    confidence_score = (forecast.get('confidence') or {}).get('score')
    existing_modes = {
        row['mode']
        for row in conn.execute(
            'SELECT mode FROM forecast_snapshots WHERE as_of=?',
            (observed.isoformat(),),
        ).fetchall()
    }

    captured = []
    for mode in SCENARIO_MODES:
        if mode in existing_modes:
            continue
        scenario = (forecast.get('scenarios') or {}).get(mode)
        if not scenario:
            continue
        points = [
            {
                'date': point['date'],
                'balance_cents': int(point['balance_cents']),
            }
            for point in scenario.get('timeline') or []
        ]
        if not points:
            continue
        low_point = scenario.get('low_point') or {}
        payload = {
            'schema_version': forecast.get('schema_version'),
            'account_ids': account_ids,
            'confidence_level': (forecast.get('confidence') or {}).get('level'),
            'timeline': points,
        }
        cursor = conn.execute(
            '''INSERT OR IGNORE INTO forecast_snapshots(
                   as_of,horizon,mode,safe_to_spend_cents,low_point_cents,low_point_date,
                   confidence_score,payload_json
               ) VALUES(?,?,?,?,?,?,?,?)''',
            (
                observed.isoformat(),
                horizon,
                mode,
                int(safe_to_spend),
                int(low_point.get('balance_cents') or 0),
                str(low_point.get('date') or observed.isoformat()),
                confidence_score,
                json.dumps(payload, ensure_ascii=False, separators=(',', ':')),
            ),
        )
        if cursor.rowcount:
            captured.append(mode)

    return {
        'status': 'captured' if captured else 'already_captured',
        'as_of': observed.isoformat(),
        'horizon': horizon,
        'captured_modes': captured,
        'preserved_modes': sorted(existing_modes),
        'read_only': False,
    }


def build_forecast_accuracy(conn, *, as_of: date | None = None, window_days: int = 90) -> dict:
    """Compare saved daily forecasts with statement balances at the same date."""
    observed = as_of or date.today()
    window_days = max(30, min(365, int(window_days)))
    start = (observed - timedelta(days=window_days)).isoformat()

    snapshots = conn.execute(
        '''SELECT id,as_of,horizon,mode,safe_to_spend_cents,confidence_score,payload_json
           FROM forecast_snapshots
           WHERE as_of>=? AND as_of<?
           ORDER BY as_of,id''',
        (start, observed.isoformat()),
    ).fetchall()

    account_ids_by_snapshot: dict[int, list[int]] = {}
    parsed_by_snapshot: dict[int, dict] = {}
    all_account_ids: set[int] = set()
    target_dates: set[str] = set()
    for row in snapshots:
        try:
            payload = json.loads(row['payload_json'] or '{}')
        except (TypeError, json.JSONDecodeError):
            continue
        ids = sorted({int(value) for value in payload.get('account_ids', [])})
        timeline = payload.get('timeline') or []
        if not ids or not timeline:
            continue
        snapshot_id = int(row['id'])
        account_ids_by_snapshot[snapshot_id] = ids
        parsed_by_snapshot[snapshot_id] = {
            'row': row,
            'timeline': timeline,
            'payload': payload,
        }
        all_account_ids.update(ids)
        target_dates.update(
            point['date'] for point in timeline
            if point.get('date') and row['as_of'] < point['date'] < observed.isoformat()
        )

    actual_by_date: dict[str, dict[int, int]] = {}
    if all_account_ids and target_dates:
        ids_sql = ','.join('?' for _ in all_account_ids)
        dates = sorted(target_dates)
        dates_sql = ','.join('?' for _ in dates)
        actual_rows = conn.execute(
            f'''SELECT account_id,balance_date,balance_cents
                FROM account_balance_history
                WHERE account_id IN ({ids_sql})
                  AND balance_date IN ({dates_sql})
                  AND source_type='bank_statement'
                  AND status='confirmed'
                ORDER BY id''',
            [*sorted(all_account_ids), *dates],
        ).fetchall()
        for row in actual_rows:
            actual_by_date.setdefault(row['balance_date'], {})[int(row['account_id'])] = int(row['balance_cents'])

    comparisons: dict[str, list[dict]] = {mode: [] for mode in SCENARIO_MODES}
    skipped_incomplete = 0
    skipped_invalid = len(snapshots) - len(parsed_by_snapshot)
    for snapshot_id, parsed in parsed_by_snapshot.items():
        row = parsed['row']
        ids = account_ids_by_snapshot[snapshot_id]
        scenario_mode = row['mode']
        if scenario_mode not in comparisons:
            continue
        points_by_date = {
            point.get('date'): point
            for point in parsed['timeline']
            if point.get('date') and row['as_of'] < point['date'] < observed.isoformat()
        }
        for actual_date, point in points_by_date.items():
            balances = actual_by_date.get(actual_date, {})
            if not all(account_id in balances for account_id in ids):
                skipped_incomplete += 1
                continue
            predicted = int(point['balance_cents'])
            actual = sum(balances[account_id] for account_id in ids)
            comparisons[scenario_mode].append({
                'forecast_as_of': row['as_of'],
                'actual_date': actual_date,
                'predicted_balance_cents': predicted,
                'actual_balance_cents': actual,
                'error_cents': predicted - actual,
                'absolute_error_cents': abs(predicted - actual),
                'confidence_score': row['confidence_score'],
            })

    modes = {}
    for mode, items in comparisons.items():
        count = len(items)
        modes[mode] = {
            'comparison_count': count,
            'mean_absolute_error_cents': round(sum(item['absolute_error_cents'] for item in items) / count) if count else None,
            'mean_error_cents': round(sum(item['error_cents'] for item in items) / count) if count else None,
            'comparisons': items[-120:],
        }
    return {
        'as_of': observed.isoformat(),
        'window_days': window_days,
        'status': 'available' if any(item['comparison_count'] for item in modes.values()) else 'insufficient_history',
        'snapshot_count': len(snapshots),
        'skipped_invalid_snapshot_count': skipped_invalid,
        'skipped_incomplete_actual_count': skipped_incomplete,
        'modes': modes,
        'method': 'Écart entre le solde quotidien projeté et la somme des soldes bancaires confirmés à la même date. Une comparaison est omise si un compte inclus ne possède pas de snapshot de relevé ce jour-là.',
        'read_only': True,
    }
