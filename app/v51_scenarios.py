from __future__ import annotations

from datetime import date

from fastapi import HTTPException

from .v32_migrations import ensure_v32_schema
from .v32_routes import _forecast
from .v3_migrations import log_activity
from .v5_planning import _canonical_variable_rate, _estimated_projection


def list_v51_scenarios(conn) -> list[dict]:
    ensure_v32_schema(conn)
    rows = conn.execute(
        'SELECT * FROM forecast_scenarios WHERE is_active=1 ORDER BY updated_at DESC,id DESC'
    ).fetchall()
    result = []
    for row in rows:
        events = [dict(x) for x in conn.execute(
            'SELECT * FROM forecast_scenario_events WHERE scenario_id=? ORDER BY id',
            (row['id'],),
        ).fetchall()]
        result.append({**dict(row), 'events': events})
    return result


def create_v51_scenario(conn, *, name: str, description: str | None, horizon_months: int,
                        events: list[dict]) -> dict:
    ensure_v32_schema(conn)
    cur = conn.execute(
        'INSERT INTO forecast_scenarios(name,description,horizon_months) VALUES(?,?,?)',
        (name, description, horizon_months),
    )
    scenario_id = cur.lastrowid
    for event in events:
        conn.execute(
            'INSERT INTO forecast_scenario_events('
            'scenario_id,event_type,label,amount_cents,due_date,day_of_month,start_date,end_date'
            ') VALUES(?,?,?,?,?,?,?,?)',
            (
                scenario_id,
                event['event_type'],
                event['label'],
                int(event['amount_cents']),
                event.get('due_date'),
                event.get('day_of_month'),
                event.get('start_date'),
                event.get('end_date'),
            ),
        )
    log_activity(
        conn,
        'scenario',
        'Scénario enregistré',
        f'{name} · {horizon_months} mois · {len(events)} hypothèse(s)',
        'forecast_scenario',
        str(scenario_id),
    )
    return {
        'id': scenario_id,
        'name': name,
        'description': description,
        'horizon_months': horizon_months,
        'events': events,
        'persisted': True,
        'affects_real_transactions': False,
    }


def compare_v51_scenario(conn, scenario_id: int) -> dict:
    ensure_v32_schema(conn)
    scenario = conn.execute(
        'SELECT * FROM forecast_scenarios WHERE id=? AND is_active=1',
        (scenario_id,),
    ).fetchone()
    if not scenario:
        raise HTTPException(404, 'Scenario not found')
    events = conn.execute(
        'SELECT * FROM forecast_scenario_events WHERE scenario_id=? ORDER BY id',
        (scenario_id,),
    ).fetchall()
    months = int(scenario['horizon_months'])
    today = date.today()
    daily_rate, estimate_meta = _canonical_variable_rate(conn, today)
    known_baseline = _forecast(conn, months, today=today)
    known_simulated = _forecast(conn, months, events, today=today)
    baseline = _estimated_projection(
        known_baseline,
        today=today,
        daily_rate_cents=daily_rate,
        estimate_meta=estimate_meta,
    )
    simulated = _estimated_projection(
        known_simulated,
        today=today,
        daily_rate_cents=daily_rate,
        estimate_meta=estimate_meta,
    )
    baseline_margin = int(baseline['minimum_safe_margin_cents'])
    simulated_margin = int(simulated['minimum_safe_margin_cents'])
    impact = {
        'closing_balance_delta_cents': int(simulated['closing_balance_cents']) - int(baseline['closing_balance_cents']),
        'low_point_delta_cents': int(simulated['low_point']['balance_cents']) - int(baseline['low_point']['balance_cents']),
        'minimum_safe_margin_delta_cents': simulated_margin - baseline_margin,
    }
    verdict = 'compatible'
    if int(simulated['low_point']['balance_cents']) < 0:
        verdict = 'not_recommended'
    elif simulated_margin <= 0:
        verdict = 'caution'
    return {
        'scenario': {**dict(scenario), 'events': [dict(e) for e in events]},
        'baseline': {
            'known_closing_balance_cents': int(baseline['known_closing_balance_cents']),
            'closing_balance_cents': int(baseline['closing_balance_cents']),
            'estimated_variable_spend_cents': int(baseline['estimated_variable_spend_cents']),
            'low_point_cents': int(baseline['low_point']['balance_cents']),
            'minimum_safe_margin_cents': baseline_margin,
        },
        'simulated': {
            'known_closing_balance_cents': int(simulated['known_closing_balance_cents']),
            'closing_balance_cents': int(simulated['closing_balance_cents']),
            'estimated_variable_spend_cents': int(simulated['estimated_variable_spend_cents']),
            'low_point_cents': int(simulated['low_point']['balance_cents']),
            'minimum_safe_margin_cents': simulated_margin,
            'months': simulated['months'],
        },
        'impact': impact,
        'verdict': verdict,
        'variable_estimate': baseline['variable_estimate'],
        'persisted': True,
        'affects_real_transactions': False,
        'principle': 'Le scénario enregistré est comparé à la trajectoire V5 estimée, qui sépare événements connus et dépenses variables estimées. Il ne modifie jamais le ledger bancaire.',
    }


def delete_v51_scenario(conn, scenario_id: int) -> None:
    ensure_v32_schema(conn)
    row = conn.execute('SELECT name FROM forecast_scenarios WHERE id=? AND is_active=1', (scenario_id,)).fetchone()
    if not row:
        raise HTTPException(404, 'Scenario not found')
    conn.execute(
        'UPDATE forecast_scenarios SET is_active=0,updated_at=CURRENT_TIMESTAMP WHERE id=?',
        (scenario_id,),
    )
    log_activity(conn, 'scenario', 'Scénario supprimé', row['name'], 'forecast_scenario', str(scenario_id))
