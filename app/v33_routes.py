from __future__ import annotations

from datetime import date
from math import ceil

from fastapi import APIRouter, HTTPException, Query

from .db import connection
from .v22_migrations import ensure_v22_schema
from .v22_routes import wealth as wealth_snapshot
from .v32_migrations import ensure_v32_schema
from .v32_routes import _forecast

router = APIRouter(prefix='/api/v3.3', tags=['Flow V3.3'])


def _months_until(target: date | None, today: date) -> int | None:
    if target is None:
        return None
    if target <= today:
        return 0
    months = (target.year - today.year) * 12 + target.month - today.month
    if target.day > today.day:
        months += 1
    return max(1, months)


def _scenario_rows(conn, scenario_id: int | None):
    if scenario_id is None:
        return None, None
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
    return dict(scenario), events


def _goal_projection(goal: dict, allocated: int, today: date, liquidity_floor: int) -> dict:
    current = max(int(goal.get('current_cents') or 0), int(allocated or 0))
    target = int(goal['target_cents'])
    remaining = max(0, target - current)
    target_date = date.fromisoformat(goal['target_date']) if goal.get('target_date') else None
    months = _months_until(target_date, today)
    contribution = int(goal.get('monthly_contribution_cents') or 0)
    required = None if months is None else (remaining if months == 0 else ceil(remaining / months))
    projected = current if months is None else current + contribution * months
    projected = min(projected, target) if target > 0 else projected

    if remaining <= 0:
        status = 'achieved'
    elif months == 0:
        status = 'late'
    elif required is None:
        status = 'no_deadline'
    elif contribution >= required:
        status = 'on_track'
    elif contribution >= required * 0.6:
        status = 'at_risk'
    else:
        status = 'off_track'

    liquidity_signal = 'comfortable'
    if contribution > 0 and liquidity_floor < contribution:
        liquidity_signal = 'tight'
    elif contribution > 0 and liquidity_floor < contribution * 2:
        liquidity_signal = 'watch'

    return {
        **goal,
        'effective_current_cents': current,
        'remaining_cents': remaining,
        'months_remaining': months,
        'required_monthly_cents': required,
        'projected_at_target_cents': projected,
        'projected_gap_cents': max(0, target - projected),
        'progress_pct': 100 if target <= 0 else min(100, round(current / target * 100, 1)),
        'projected_progress_pct': 100 if target <= 0 else min(100, round(projected / target * 100, 1)),
        'status': status,
        'liquidity_signal': liquidity_signal,
    }


@router.get('/goals-forecast')
def goals_forecast(
    months: int = Query(default=12, ge=1, le=12),
    scenario_id: int | None = Query(default=None, ge=1),
):
    today = date.today()
    with connection() as conn:
        ensure_v22_schema(conn)
        ensure_v32_schema(conn)
        scenario, scenario_events = _scenario_rows(conn, scenario_id)
        forecast = _forecast(conn, months, scenario_events)
        liquidity_floor = min((int(m['safe_margin_cents']) for m in forecast['months']), default=0)
        goals = [dict(r) for r in conn.execute(
            'SELECT * FROM financial_goals WHERE is_active=1 ORDER BY priority,id'
        ).fetchall()]
        allocations = {
            int(r['goal_id']): int(r['total'])
            for r in conn.execute(
                'SELECT goal_id,COALESCE(SUM(amount_cents),0) total FROM goal_allocations GROUP BY goal_id'
            ).fetchall()
        }

    projections = [_goal_projection(g, allocations.get(int(g['id']), 0), today, liquidity_floor) for g in goals]
    counts = {
        'achieved': sum(1 for g in projections if g['status'] == 'achieved'),
        'on_track': sum(1 for g in projections if g['status'] == 'on_track'),
        'at_risk': sum(1 for g in projections if g['status'] == 'at_risk'),
        'off_track': sum(1 for g in projections if g['status'] in {'off_track', 'late'}),
    }
    return {
        'as_of': today.isoformat(),
        'horizon_months': months,
        'scenario': scenario,
        'liquidity_floor_cents': liquidity_floor,
        'goals': projections,
        'counts': counts,
        'method': 'Projection déterministe à partir du montant actuel, de la contribution mensuelle configurée et de la date cible. Le signal de liquidité utilise la marge minimale du forecast et ne constitue pas une réservation de fonds.',
    }


@router.get('/wealth-forecast')
def wealth_forecast(
    months: int = Query(default=12, ge=1, le=12),
    scenario_id: int | None = Query(default=None, ge=1),
):
    snapshot = wealth_snapshot()
    with connection() as conn:
        ensure_v32_schema(conn)
        scenario, scenario_events = _scenario_rows(conn, scenario_id)
        forecast = _forecast(conn, months, scenario_events)

    liquidity_delta = int(forecast['closing_balance_cents']) - int(forecast['opening_balance_cents'])
    projected_net_worth = int(snapshot['net_worth_cents']) + liquidity_delta
    monthly = []
    opening = int(forecast['opening_balance_cents'])
    for row in forecast['months']:
        delta = int(row['closing_balance_cents']) - opening
        monthly.append({
            'month': row['month'],
            'projected_net_worth_cents': int(snapshot['net_worth_cents']) + delta,
            'projected_liquid_balance_cents': int(row['closing_balance_cents']),
            'low_point_cents': int(row['low_point_cents']),
        })

    return {
        'as_of': snapshot['as_of'],
        'horizon_months': months,
        'scenario': scenario,
        'current_net_worth_cents': int(snapshot['net_worth_cents']),
        'projected_net_worth_cents': projected_net_worth,
        'net_worth_delta_cents': liquidity_delta,
        'current_assets_cents': int(snapshot['total_assets_cents']),
        'current_debt_cents': int(snapshot['total_debt_cents']),
        'months': monthly,
        'method': 'Projection déterministe : seule la variation de liquidité issue du forecast modifie le patrimoine net. Les valorisations des actifs physiques, investissements non modélisés et dettes sont maintenues constantes faute de nouvelle donnée.',
    }
