from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .db import connection
from .v22_migrations import ensure_v22_schema
from .v3_migrations import ensure_v3_schema, log_activity
from .v32_migrations import ensure_v32_schema
from .v32_routes import _forecast
from .v33_routes import _goal_projection, _scenario_rows
from .v34_migrations import ensure_v34_schema

router = APIRouter(prefix='/api/v3.4', tags=['Flow V3.4'])


class ActionStatusIn(BaseModel):
    status: str = Field(pattern='^(open|done|dismissed)$')
    note: str | None = Field(default=None, max_length=300)


def _days_old(value: str | None, today: date) -> int | None:
    if not value:
        return None
    try:
        observed = date.fromisoformat(value[:10])
    except ValueError:
        return None
    return max(0, (today - observed).days)


def _status_map(conn) -> dict[str, dict]:
    rows = conn.execute('SELECT * FROM action_plan_status').fetchall()
    return {str(r['action_key']): dict(r) for r in rows}


def _decorate(actions: list[dict], statuses: dict[str, dict]) -> list[dict]:
    result = []
    for action in actions:
        state = statuses.get(action['key'])
        result.append({
            **action,
            'status': state['status'] if state else 'open',
            'note': state['note'] if state else None,
            'status_updated_at': state['updated_at'] if state else None,
        })
    order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
    return sorted(result, key=lambda x: (x['status'] != 'open', order.get(x['priority'], 9), x['key']))


@router.get('/action-plan')
def action_plan(
    months: int = Query(default=3, ge=1, le=12),
    scenario_id: int | None = Query(default=None, ge=1),
):
    today = date.today()
    month_key = today.strftime('%Y-%m')
    with connection() as conn:
        ensure_v22_schema(conn)
        ensure_v32_schema(conn)
        ensure_v34_schema(conn)
        scenario, scenario_events = _scenario_rows(conn, scenario_id)
        forecast = _forecast(conn, months, scenario_events)
        statuses = _status_map(conn)

        goals = [dict(r) for r in conn.execute(
            'SELECT * FROM financial_goals WHERE is_active=1 ORDER BY priority,id'
        ).fetchall()]
        allocations = {
            int(r['goal_id']): int(r['total'])
            for r in conn.execute(
                'SELECT goal_id,COALESCE(SUM(amount_cents),0) total FROM goal_allocations GROUP BY goal_id'
            ).fetchall()
        }
        accounts = [dict(r) for r in conn.execute(
            'SELECT id,name,balance_as_of FROM accounts WHERE is_active=1 ORDER BY id'
        ).fetchall()]

    first_month = forecast['months'][0] if forecast['months'] else None
    min_margin = min((int(m['safe_margin_cents']) for m in forecast['months']), default=0)
    actions: list[dict] = []

    if min_margin < 0:
        actions.append({
            'key': f'{month_key}:liquidity-buffer',
            'type': 'liquidity',
            'priority': 'critical',
            'title': 'Rétablir la marge de sécurité',
            'detail': 'La trajectoire passe sous la réserve protégée sur l’horizon analysé.',
            'amount_cents': abs(min_margin),
            'source': 'forecast',
        })
    elif min_margin < max(10000, int(forecast['protected_cents']) // 10):
        actions.append({
            'key': f'{month_key}:liquidity-watch',
            'type': 'liquidity',
            'priority': 'high',
            'title': 'Conserver une marge de sécurité',
            'detail': 'La marge disponible reste positive mais proche du niveau protégé.',
            'amount_cents': max(0, min_margin),
            'source': 'forecast',
        })

    if first_month:
        outflows = [e for e in first_month.get('events', []) if int(e['amount_cents']) < 0]
        total_outflows = sum(abs(int(e['amount_cents'])) for e in outflows)
        if outflows:
            actions.append({
                'key': f'{month_key}:month-outflows',
                'type': 'upcoming',
                'priority': 'high' if total_outflows > max(50000, int(forecast['opening_balance_cents']) // 3) else 'medium',
                'title': 'Couvrir les sorties prévues du mois',
                'detail': f"{len(outflows)} sortie(s) identifiée(s) dans le forecast du mois courant.",
                'amount_cents': total_outflows,
                'source': 'forecast',
            })

    goal_floor = max(0, min_margin)
    projected_goals = [
        _goal_projection(g, allocations.get(int(g['id']), 0), today, goal_floor)
        for g in goals
    ]
    remaining_capacity = goal_floor
    for goal in projected_goals:
        if goal['status'] in {'achieved', 'no_deadline'}:
            continue
        required = int(goal['required_monthly_cents'] or 0)
        configured = int(goal.get('monthly_contribution_cents') or 0)
        gap = max(0, required - configured)
        if gap <= 0:
            continue
        suggested = min(gap, remaining_capacity)
        if suggested > 0:
            remaining_capacity -= suggested
            actions.append({
                'key': f"{month_key}:goal:{goal['id']}",
                'type': 'goal',
                'priority': 'high' if goal['status'] in {'off_track', 'late'} else 'medium',
                'title': f"Renforcer l’objectif {goal['name']}",
                'detail': f"Effort requis {required / 100:.2f} €/mois, contribution configurée {configured / 100:.2f} €/mois.",
                'amount_cents': suggested,
                'source': 'goal_forecast',
                'entity_id': int(goal['id']),
            })
        else:
            actions.append({
                'key': f"{month_key}:goal:{goal['id']}:capacity",
                'type': 'goal',
                'priority': 'medium',
                'title': f"Objectif {goal['name']} sous-financé",
                'detail': 'L’effort cible dépasse la marge de liquidité disponible sur l’horizon analysé.',
                'amount_cents': gap,
                'source': 'goal_forecast',
                'entity_id': int(goal['id']),
            })

    for account in accounts:
        age = _days_old(account.get('balance_as_of'), today)
        if age is None or age > 7:
            actions.append({
                'key': f"{month_key}:account:{account['id']}:refresh",
                'type': 'data_quality',
                'priority': 'medium',
                'title': f"Actualiser le solde {account['name']}",
                'detail': 'Solde sans date fiable.' if age is None else f'Solde âgé de {age} jours.',
                'amount_cents': None,
                'source': 'data_quality',
                'entity_id': int(account['id']),
            })

    decorated = _decorate(actions, statuses)
    open_actions = [a for a in decorated if a['status'] == 'open']
    return {
        'as_of': today.isoformat(),
        'month': month_key,
        'horizon_months': months,
        'scenario': scenario,
        'summary': {
            'total_actions': len(decorated),
            'open_actions': len(open_actions),
            'critical_actions': sum(1 for a in open_actions if a['priority'] == 'critical'),
            'high_actions': sum(1 for a in open_actions if a['priority'] == 'high'),
            'minimum_safe_margin_cents': min_margin,
            'protected_cents': int(forecast['protected_cents']),
            'goal_capacity_cents': goal_floor,
        },
        'actions': decorated,
        'method': 'Plan déterministe dérivé du forecast, des objectifs, des soldes et des règles de protection. Les montants proposés sont indicatifs et aucune transaction ni affectation réelle n’est créée automatiquement.',
    }


@router.patch('/action-plan/{action_key:path}')
def update_action(action_key: str, payload: ActionStatusIn):
    if not action_key.strip():
        raise HTTPException(400, 'Invalid action key')
    with connection() as conn:
        ensure_v34_schema(conn)
        ensure_v3_schema(conn)
        conn.execute(
            """
            INSERT INTO action_plan_status(action_key,status,note,updated_at)
            VALUES(?,?,?,CURRENT_TIMESTAMP)
            ON CONFLICT(action_key) DO UPDATE SET
                status=excluded.status,
                note=excluded.note,
                updated_at=CURRENT_TIMESTAMP
            """,
            (action_key, payload.status, payload.note),
        )
        log_activity(
            conn,
            'action_plan',
            'Plan d’action mis à jour',
            f'{action_key} → {payload.status}',
            'action_plan',
            action_key,
        )
        row = conn.execute('SELECT * FROM action_plan_status WHERE action_key=?', (action_key,)).fetchone()
    return dict(row)
