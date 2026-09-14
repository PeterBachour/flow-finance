from __future__ import annotations

import calendar
from datetime import date
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .db import connection
from .financial_engine_v1 import financial_rule_summary, safe_account_balance_cents
from .projection_routes import _planned_events, _recurring_events
from .v3_migrations import log_activity
from .v32_migrations import ensure_v32_schema

router = APIRouter(prefix='/api/v3.2', tags=['Flow V3.2'])


class ScenarioEventIn(BaseModel):
    event_type: str = Field(default='one_time', pattern='^(one_time|monthly)$')
    label: str = Field(min_length=1, max_length=180)
    amount_cents: int
    due_date: date | None = None
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    start_date: date | None = None
    end_date: date | None = None


class ScenarioIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=400)
    horizon_months: int = Field(default=6, ge=1, le=12)
    events: list[ScenarioEventIn] = Field(default_factory=list)


def _month_add(value: date, offset: int) -> tuple[int, int]:
    idx = value.year * 12 + value.month - 1 + offset
    return idx // 12, idx % 12 + 1


def _month_key(y: int, m: int) -> str:
    return f'{y:04d}-{m:02d}'


def _scenario_events(rows, today: date, months: int) -> list[dict]:
    horizon_y, horizon_m = _month_add(today, months - 1)
    horizon_end = date(horizon_y, horizon_m, calendar.monthrange(horizon_y, horizon_m)[1])
    out = []
    for row in rows:
        if row['event_type'] == 'one_time':
            if row['due_date']:
                due = date.fromisoformat(row['due_date'])
                if today <= due <= horizon_end:
                    out.append({'date': due, 'amount_cents': int(row['amount_cents']), 'label': row['label'], 'source': 'scenario'})
            continue
        start = date.fromisoformat(row['start_date']) if row['start_date'] else today
        end = date.fromisoformat(row['end_date']) if row['end_date'] else horizon_end
        for offset in range(months):
            y, m = _month_add(today, offset)
            day = min(int(row['day_of_month'] or start.day), calendar.monthrange(y, m)[1])
            due = date(y, m, day)
            if due >= max(today, start) and due <= min(end, horizon_end):
                out.append({'date': due, 'amount_cents': int(row['amount_cents']), 'label': row['label'], 'source': 'scenario'})
    return out


def _forecast(conn, months: int, scenario_rows=None, today: date | None = None) -> dict:
    today = today or date.today()
    opening = safe_account_balance_cents(conn)
    rules = financial_rule_summary(conn, today.strftime('%Y-%m'))
    reserve_row = conn.execute("SELECT value FROM settings WHERE key='safety_reserve_cents'").fetchone()
    configured_reserve = int(reserve_row['value']) if reserve_row else 0
    safety_reserve = max(configured_reserve, int(rules.get('minimum_reserve_cents') or 0))
    rule_reserve = int(rules.get('rule_reserve_cents') or 0)
    allocated = int(conn.execute("SELECT COALESCE(SUM(g.amount_cents),0) total FROM goal_allocations g LEFT JOIN accounts a ON a.id=g.account_id WHERE g.account_id IS NULL OR COALESCE(a.include_in_safe_to_spend,0)=1").fetchone()['total'])
    protected = safety_reserve + rule_reserve + allocated

    base = []
    for e in _planned_events(conn, today) + _recurring_events(conn, today, months_ahead=months):
        base.append({'date': e.due_date, 'amount_cents': int(e.amount_cents), 'label': e.label, 'source': e.source})
    base.extend(_scenario_events(scenario_rows or [], today, months))
    base.sort(key=lambda e: (e['date'], e['label']))

    seen = set(); events = []
    for e in base:
        key = (e['date'].isoformat(), e['amount_cents'], e['label'].strip().upper())
        if key in seen:
            continue
        seen.add(key); events.append(e)

    balance = opening
    month_rows = []
    global_low = {'date': today.isoformat(), 'balance_cents': balance}
    for offset in range(months):
        y, m = _month_add(today, offset)
        key = _month_key(y, m)
        month_events = [e for e in events if e['date'].strftime('%Y-%m') == key]
        start_balance = balance
        month_low = balance
        inflows = outflows = 0
        timeline = []
        for e in month_events:
            balance += e['amount_cents']
            if e['amount_cents'] >= 0:
                inflows += e['amount_cents']
            else:
                outflows += -e['amount_cents']
            month_low = min(month_low, balance)
            if balance < global_low['balance_cents']:
                global_low = {'date': e['date'].isoformat(), 'balance_cents': balance}
            timeline.append({**e, 'date': e['date'].isoformat(), 'balance_after_cents': balance})
        month_rows.append({
            'month': key,
            'opening_balance_cents': start_balance,
            'inflows_cents': inflows,
            'outflows_cents': outflows,
            'closing_balance_cents': balance,
            'low_point_cents': month_low,
            'safe_margin_cents': max(0, month_low - protected),
            'events': timeline,
        })
    return {
        'as_of': today.isoformat(),
        'horizon_months': months,
        'opening_balance_cents': opening,
        'protected_cents': protected,
        'protection': {
            'safety_reserve_cents': safety_reserve,
            'rule_reserved_cents': rule_reserve,
            'goal_allocations_cents': allocated,
        },
        'closing_balance_cents': balance,
        'low_point': global_low,
        'months': month_rows,
    }


@router.get('/forecast')
def forecast(months: int = Query(default=6, ge=1, le=12)):
    with connection() as conn:
        ensure_v32_schema(conn)
        return _forecast(conn, months)


@router.get('/scenarios')
def scenarios():
    with connection() as conn:
        ensure_v32_schema(conn)
        rows = conn.execute('SELECT * FROM forecast_scenarios WHERE is_active=1 ORDER BY updated_at DESC,id DESC').fetchall()
        result = []
        for row in rows:
            events = [dict(x) for x in conn.execute('SELECT * FROM forecast_scenario_events WHERE scenario_id=? ORDER BY id', (row['id'],)).fetchall()]
            result.append({**dict(row), 'events': events})
        return result


@router.post('/scenarios', status_code=201)
def create_scenario(payload: ScenarioIn):
    with connection() as conn:
        ensure_v32_schema(conn)
        cur = conn.execute('INSERT INTO forecast_scenarios(name,description,horizon_months) VALUES(?,?,?)', (payload.name,payload.description,payload.horizon_months))
        sid = cur.lastrowid
        for e in payload.events:
            conn.execute('INSERT INTO forecast_scenario_events(scenario_id,event_type,label,amount_cents,due_date,day_of_month,start_date,end_date) VALUES(?,?,?,?,?,?,?,?)', (sid,e.event_type,e.label,e.amount_cents,e.due_date.isoformat() if e.due_date else None,e.day_of_month,e.start_date.isoformat() if e.start_date else None,e.end_date.isoformat() if e.end_date else None))
        log_activity(conn, 'scenario', 'Scénario enregistré', f'{payload.name} · {payload.horizon_months} mois · {len(payload.events)} hypothèse(s)', 'forecast_scenario', str(sid))
        return {'id': sid, **payload.model_dump(mode='json')}


@router.get('/scenarios/{scenario_id}/compare')
def compare_scenario(scenario_id: int):
    with connection() as conn:
        ensure_v32_schema(conn)
        scenario = conn.execute('SELECT * FROM forecast_scenarios WHERE id=? AND is_active=1', (scenario_id,)).fetchone()
        if not scenario:
            raise HTTPException(404, 'Scenario not found')
        events = conn.execute('SELECT * FROM forecast_scenario_events WHERE scenario_id=? ORDER BY id', (scenario_id,)).fetchall()
        months = int(scenario['horizon_months'])
        baseline = _forecast(conn, months)
        simulated = _forecast(conn, months, events)
        return {
            'scenario': dict(scenario),
            'baseline': baseline,
            'simulated': simulated,
            'impact': {
                'closing_balance_delta_cents': simulated['closing_balance_cents'] - baseline['closing_balance_cents'],
                'low_point_delta_cents': simulated['low_point']['balance_cents'] - baseline['low_point']['balance_cents'],
                'minimum_safe_margin_delta_cents': min(m['safe_margin_cents'] for m in simulated['months']) - min(m['safe_margin_cents'] for m in baseline['months']),
            },
        }


@router.delete('/scenarios/{scenario_id}', status_code=204)
def delete_scenario(scenario_id: int):
    with connection() as conn:
        ensure_v32_schema(conn)
        row = conn.execute('SELECT name FROM forecast_scenarios WHERE id=?', (scenario_id,)).fetchone()
        if not row:
            raise HTTPException(404, 'Scenario not found')
        conn.execute('UPDATE forecast_scenarios SET is_active=0,updated_at=CURRENT_TIMESTAMP WHERE id=?', (scenario_id,))
        log_activity(conn, 'scenario', 'Scénario supprimé', row['name'], 'forecast_scenario', str(scenario_id))
