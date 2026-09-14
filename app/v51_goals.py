from __future__ import annotations

from datetime import date

from .v33_routes import _goal_projection
from .v410_routes import ensure_v410_schema
from .v5_planning import build_v5_plan


def _goal_allocations(conn) -> dict[int, int]:
    return {
        int(row['goal_id']): int(row['total'] or 0)
        for row in conn.execute(
            'SELECT goal_id,COALESCE(SUM(amount_cents),0) total FROM goal_allocations GROUP BY goal_id'
        ).fetchall()
    }


def _history(conn, goal_id: int) -> list[dict]:
    ensure_v410_schema(conn)
    return [dict(row) for row in conn.execute(
        '''SELECT observed_on,current_cents,target_cents,monthly_contribution_cents,target_date,source_type
           FROM goal_progress_history WHERE goal_id=? ORDER BY observed_on DESC,id DESC LIMIT 12''',
        (goal_id,),
    ).fetchall()]


def _liquidity_floor(plan: dict) -> int:
    months = (plan.get('projection') or {}).get('months') or []
    return min((int(row.get('safe_margin_cents') or 0) for row in months), default=0)


def build_goal_control(conn, *, today: date, months: int = 12) -> dict:
    months = max(1, min(12, int(months)))
    plan = build_v5_plan(conn, months=months, today=today)
    liquidity_floor = _liquidity_floor(plan)
    arbitration = plan.get('goal_arbitration') or {}
    advised = {int(row.get('goal_id')): row for row in arbitration.get('goals') or [] if row.get('goal_id') is not None}
    allocations = _goal_allocations(conn)
    goals = [dict(row) for row in conn.execute(
        'SELECT * FROM financial_goals WHERE is_active=1 ORDER BY priority,id'
    ).fetchall()]

    items = []
    for goal in goals:
        goal_id = int(goal['id'])
        projection = _goal_projection(goal, allocations.get(goal_id, 0), today, liquidity_floor)
        advice = advised.get(goal_id) or {}
        required = projection.get('required_monthly_cents')
        configured = int(projection.get('monthly_contribution_cents') or 0)
        recommended = int(advice.get('recommended_monthly_cents') or 0)
        funding_gap = max(0, int(advice.get('funding_gap_cents') or 0))
        items.append({
            'goal_id': goal_id,
            'name': projection.get('name'),
            'priority': int(projection.get('priority') or 0),
            'mandatory': bool(projection.get('mandatory')),
            'status': projection.get('status'),
            'target_date': projection.get('target_date'),
            'target_cents': int(projection.get('target_cents') or 0),
            'current_cents': int(projection.get('effective_current_cents') or 0),
            'remaining_cents': int(projection.get('remaining_cents') or 0),
            'progress_pct': float(projection.get('progress_pct') or 0),
            'projected_progress_pct': float(projection.get('projected_progress_pct') or 0),
            'projected_at_target_cents': int(projection.get('projected_at_target_cents') or 0),
            'projected_gap_cents': int(projection.get('projected_gap_cents') or 0),
            'months_remaining': projection.get('months_remaining'),
            'configured_monthly_cents': configured,
            'required_monthly_cents': required,
            'recommended_monthly_cents': recommended,
            'funding_gap_cents': funding_gap,
            'liquidity_signal': projection.get('liquidity_signal'),
            'history': _history(conn, goal_id),
        })

    rank = {'late': 0, 'off_track': 1, 'at_risk': 2, 'no_deadline': 3, 'on_track': 4, 'achieved': 5}
    items.sort(key=lambda row: (
        0 if row['mandatory'] else 1,
        rank.get(row['status'], 9),
        row['priority'],
        row['goal_id'],
    ))
    attention = sum(1 for row in items if row['status'] in {'late', 'off_track', 'at_risk'})
    return {
        'schema_version': '5.1',
        'as_of': today.isoformat(),
        'horizon_months': months,
        'monthly_capacity_cents': int(arbitration.get('monthly_capacity_cents') or 0),
        'unallocated_monthly_capacity_cents': int(arbitration.get('unallocated_monthly_capacity_cents') or 0),
        'liquidity_floor_cents': liquidity_floor,
        'summary': {
            'goal_count': len(items),
            'goals_needing_attention': attention,
            'on_track_or_achieved': sum(1 for row in items if row['status'] in {'on_track', 'achieved'}),
        },
        'goals': items,
        'principle': 'Le pilotage des objectifs combine la projection déterministe existante et la capacité mensuelle du plan V5. Aucun argent n’est déplacé ni réservé automatiquement.',
    }


def simulate_goal_contribution(conn, *, goal_id: int, monthly_contribution_cents: int,
                               today: date, months: int = 12) -> dict | None:
    months = max(1, min(12, int(months)))
    plan = build_v5_plan(conn, months=months, today=today)
    liquidity_floor = _liquidity_floor(plan)
    arbitration = plan.get('goal_arbitration') or {}
    monthly_capacity = int(arbitration.get('monthly_capacity_cents') or 0)
    goal_row = conn.execute('SELECT * FROM financial_goals WHERE id=? AND is_active=1', (goal_id,)).fetchone()
    if not goal_row:
        return None
    goal = dict(goal_row)
    allocated = _goal_allocations(conn).get(goal_id, 0)
    baseline = _goal_projection(goal, allocated, today, liquidity_floor)
    simulated_goal = {**goal, 'monthly_contribution_cents': max(0, int(monthly_contribution_cents))}
    simulated = _goal_projection(simulated_goal, allocated, today, liquidity_floor)
    proposed = max(0, int(monthly_contribution_cents))
    capacity_delta = monthly_capacity - proposed
    compatible = proposed <= monthly_capacity if monthly_capacity > 0 else proposed == 0
    return {
        'schema_version': '5.1',
        'as_of': today.isoformat(),
        'goal_id': goal_id,
        'name': goal.get('name'),
        'monthly_capacity_cents': monthly_capacity,
        'proposed_monthly_cents': proposed,
        'capacity_after_proposal_cents': capacity_delta,
        'compatible_with_current_capacity': compatible,
        'baseline': {
            'status': baseline.get('status'),
            'monthly_contribution_cents': int(baseline.get('monthly_contribution_cents') or 0),
            'projected_at_target_cents': int(baseline.get('projected_at_target_cents') or 0),
            'projected_gap_cents': int(baseline.get('projected_gap_cents') or 0),
            'projected_progress_pct': float(baseline.get('projected_progress_pct') or 0),
        },
        'simulated': {
            'status': simulated.get('status'),
            'monthly_contribution_cents': proposed,
            'projected_at_target_cents': int(simulated.get('projected_at_target_cents') or 0),
            'projected_gap_cents': int(simulated.get('projected_gap_cents') or 0),
            'projected_progress_pct': float(simulated.get('projected_progress_pct') or 0),
        },
        'impact': {
            'projected_gap_delta_cents': int(simulated.get('projected_gap_cents') or 0) - int(baseline.get('projected_gap_cents') or 0),
            'projected_progress_delta_pct': round(float(simulated.get('projected_progress_pct') or 0) - float(baseline.get('projected_progress_pct') or 0), 1),
        },
        'persisted': False,
        'principle': 'Simulation en lecture seule : la contribution de l’objectif n’est modifiée qu’après une confirmation explicite via le mécanisme de mise à jour existant.',
    }
