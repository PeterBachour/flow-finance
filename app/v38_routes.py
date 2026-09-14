from __future__ import annotations

from fastapi import APIRouter, Query

from .db import connection
from .v2_migrations import ensure_v2_schema
from .v32_migrations import ensure_v32_schema
from .v32_routes import _forecast

router = APIRouter(prefix='/api/v3.8', tags=['Flow V3.8'])


def _setting_int(conn, key: str, default: int = 0) -> int:
    row = conn.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
    if not row:
        return default
    try:
        return int(row['value'])
    except (TypeError, ValueError):
        return default


@router.get('/strategy')
def strategy(months: int = Query(default=3, ge=1, le=12)):
    with connection() as conn:
        ensure_v2_schema(conn)
        ensure_v32_schema(conn)
        forecast = _forecast(conn, months)
        accounts = [dict(r) for r in conn.execute(
            "SELECT id,name,kind,current_balance_cents,include_in_safe_to_spend,include_in_liquidity FROM accounts WHERE is_active=1 ORDER BY id"
        ).fetchall()]
        goals = [dict(r) for r in conn.execute(
            "SELECT id,name,target_cents,current_cents,monthly_contribution_cents,target_date,priority,is_mandatory,include_in_safe_to_spend FROM financial_goals WHERE is_active=1 ORDER BY priority,id"
        ).fetchall()]
        safety_reserve = max(0, _setting_int(conn, 'safety_reserve_cents', 0))

    liquid = sum(int(a['current_balance_cents']) for a in accounts if a.get('include_in_liquidity'))
    safe_accounts = sum(int(a['current_balance_cents']) for a in accounts if a.get('include_in_safe_to_spend'))
    min_margin = min((int(m['safe_margin_cents']) for m in forecast.get('months', [])), default=0)
    mandatory_goal_monthly = sum(max(0, int(g.get('monthly_contribution_cents') or 0)) for g in goals if g.get('is_mandatory'))
    all_goal_monthly = sum(max(0, int(g.get('monthly_contribution_cents') or 0)) for g in goals)
    protected = max(safety_reserve, max(0, safe_accounts - max(0, min_margin)))
    immediate_capacity = max(0, min(liquid, safe_accounts) - protected)
    mandatory_allocation = min(immediate_capacity, mandatory_goal_monthly)
    after_mandatory = max(0, immediate_capacity - mandatory_allocation)
    optional_goal_need = max(0, all_goal_monthly - mandatory_goal_monthly)
    optional_goal_allocation = min(after_mandatory, optional_goal_need)
    strategic_surplus = max(0, after_mandatory - optional_goal_allocation)

    if min_margin < 0:
        status = 'protect_liquidity'
        headline = 'Priorité à la liquidité'
    elif mandatory_goal_monthly and mandatory_allocation < mandatory_goal_monthly:
        status = 'fund_mandatory_goals'
        headline = 'Sécuriser les objectifs obligatoires'
    elif strategic_surplus > 0:
        status = 'surplus_available'
        headline = 'Surplus stratégique disponible'
    else:
        status = 'balanced'
        headline = 'Trajectoire équilibrée'

    buckets = [
        {'key': 'reserve', 'label': 'Réserve protégée', 'amount_cents': protected, 'priority': 1, 'reason': 'Réserve de sécurité et marge nécessaire pour éviter un point bas négatif.'},
        {'key': 'mandatory_goals', 'label': 'Objectifs obligatoires', 'amount_cents': mandatory_allocation, 'priority': 2, 'reason': 'Contributions mensuelles des objectifs marqués comme obligatoires.'},
        {'key': 'optional_goals', 'label': 'Autres objectifs', 'amount_cents': optional_goal_allocation, 'priority': 3, 'reason': 'Contribution aux autres objectifs dans la limite de la capacité disponible.'},
        {'key': 'strategic_surplus', 'label': 'Surplus non affecté', 'amount_cents': strategic_surplus, 'priority': 4, 'reason': 'Montant restant après réserve et contributions configurées. Flow ne l’investit pas automatiquement.'},
    ]

    return {
        'horizon_months': months,
        'status': status,
        'headline': headline,
        'liquid_cents': liquid,
        'safe_accounts_cents': safe_accounts,
        'minimum_safe_margin_cents': min_margin,
        'safety_reserve_cents': safety_reserve,
        'protected_cents': protected,
        'immediate_capacity_cents': immediate_capacity,
        'mandatory_goal_monthly_cents': mandatory_goal_monthly,
        'optional_goal_monthly_cents': optional_goal_need,
        'strategic_surplus_cents': strategic_surplus,
        'buckets': buckets,
        'method': 'Moteur déterministe : réserve et liquidité d’abord, objectifs obligatoires ensuite, autres objectifs ensuite, puis surplus non affecté. Aucune opération bancaire ni recommandation d’instrument financier n’est exécutée automatiquement.',
    }
