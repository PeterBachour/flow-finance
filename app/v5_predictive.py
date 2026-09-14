from __future__ import annotations

from datetime import date

from .v5_engine import build_v5_cockpit
from .v5_planning import build_v5_plan
from .v5_recommendations import build_v5_recommendations


def _clamp(value: float, minimum: int = 0, maximum: int = 100) -> int:
    return max(minimum, min(maximum, round(value)))


def _risk_level(score: int) -> str:
    if score >= 75:
        return 'critical'
    if score >= 50:
        return 'high'
    if score >= 25:
        return 'watch'
    return 'low'


def _liquidity_risk(plan: dict) -> tuple[int, dict]:
    projection = plan.get('projection') or {}
    months = projection.get('months') or []
    minimum_margin = int(projection.get('minimum_safe_margin_cents') or 0)
    protected = max(1, int(projection.get('protected_cents') or 0))
    low = int((projection.get('low_point') or {}).get('balance_cents') or 0)

    if low < 0:
        score = 100
    elif minimum_margin <= 0:
        score = 85
    else:
        ratio = minimum_margin / protected
        score = _clamp(70 - ratio * 55)

    stressed_months = sum(1 for row in months if int(row.get('safe_margin_cents') or 0) <= 0)
    score = _clamp(score + stressed_months * 8)
    return score, {
        'minimum_safe_margin_cents': minimum_margin,
        'protected_cents': protected,
        'low_point_cents': low,
        'stressed_months': stressed_months,
    }


def _goal_risk(plan: dict) -> tuple[int, dict]:
    arbitration = plan.get('goal_arbitration') or {}
    goals = arbitration.get('goals') or []
    active = [goal for goal in goals if goal.get('status') != 'achieved']
    if not active:
        return 0, {'at_risk_goals': 0, 'funding_gap_cents': 0, 'mandatory_at_risk': 0}

    at_risk = [goal for goal in active if goal.get('status') in {'late', 'off_track', 'at_risk'}]
    mandatory = [goal for goal in at_risk if goal.get('mandatory')]
    funding_gap = sum(max(0, int(goal.get('funding_gap_cents') or 0)) for goal in active)
    required = sum(max(0, int(goal.get('required_monthly_cents') or 0)) for goal in active)
    gap_ratio = (funding_gap / required) if required > 0 else 0
    score = _clamp(len(at_risk) * 14 + len(mandatory) * 18 + gap_ratio * 45)
    return score, {
        'at_risk_goals': len(at_risk),
        'mandatory_at_risk': len(mandatory),
        'funding_gap_cents': funding_gap,
        'required_monthly_cents': required,
    }


def _confidence_risk(cockpit: dict) -> tuple[int, dict]:
    confidence = cockpit.get('confidence') or {}
    level = confidence.get('level') or 'low'
    base = {'high': 10, 'medium': 35, 'low': 70}.get(level, 70)
    age = confidence.get('balance_age_days')
    if age is None:
        base += 20
    elif int(age) > 31:
        base += 25
    elif int(age) > 7:
        base += 12
    if not confidence.get('current_month_observed'):
        base += 8
    return _clamp(base), {
        'confidence_level': level,
        'balance_age_days': age,
        'current_month_observed': bool(confidence.get('current_month_observed')),
        'historical_coverage_pct': confidence.get('historical_coverage_pct'),
    }


def _critical_events(plan: dict, limit: int = 8) -> list[dict]:
    projection = plan.get('projection') or {}
    protected = int(projection.get('protected_cents') or 0)
    events: list[dict] = []
    for month in projection.get('months') or []:
        for event in month.get('events') or []:
            amount = int(event.get('amount_cents') or 0)
            balance_after = int(event.get('balance_after_cents') or 0)
            if amount >= 0:
                continue
            distance = balance_after - protected
            severity = 'critical' if balance_after < 0 else ('high' if distance < 0 else ('watch' if distance < protected * 0.25 else 'info'))
            if severity == 'info':
                continue
            events.append({
                'date': event.get('date'),
                'label': event.get('label'),
                'amount_cents': amount,
                'balance_after_cents': balance_after,
                'distance_to_protection_cents': distance,
                'severity': severity,
                'source': event.get('source'),
            })
    rank = {'critical': 0, 'high': 1, 'watch': 2}
    return sorted(events, key=lambda row: (rank.get(row['severity'], 9), row.get('date') or ''))[:limit]


def build_v5_predictive_pilot(conn, *, as_of: date, financial_decisions: list[dict] | None = None,
                              months: int = 6, cockpit: dict | None = None,
                              plan: dict | None = None, recommendations: dict | None = None) -> dict:
    """Build predictive risk from a coherent request-scoped financial snapshot.

    Standalone callers can omit every precomputed input. Composite callers can inject
    cockpit, plan and recommendations so all downstream values come from one snapshot.
    """
    months = max(1, min(12, int(months)))
    decisions = financial_decisions or []
    if cockpit is None:
        cockpit = build_v5_cockpit(conn, as_of=as_of, financial_decisions=decisions)
    if plan is None:
        plan = build_v5_plan(conn, months=months, today=as_of)
    if recommendations is None:
        recommendations = build_v5_recommendations(
            conn,
            as_of=as_of,
            financial_decisions=decisions,
            months=months,
            cockpit=cockpit,
            plan=plan,
        )

    liquidity_score, liquidity_evidence = _liquidity_risk(plan)
    goal_score, goal_evidence = _goal_risk(plan)
    confidence_score, confidence_evidence = _confidence_risk(cockpit)
    events = _critical_events(plan)
    event_score = _clamp(len([e for e in events if e['severity'] == 'critical']) * 45 +
                         len([e for e in events if e['severity'] == 'high']) * 22 +
                         len([e for e in events if e['severity'] == 'watch']) * 8)

    total = _clamp(
        liquidity_score * 0.45 +
        goal_score * 0.25 +
        confidence_score * 0.20 +
        event_score * 0.10
    )
    level = _risk_level(total)

    projection = plan.get('projection') or {}
    months_rows = projection.get('months') or []
    checkpoints = []
    for index in (0, 2, 5):
        if index >= len(months_rows):
            continue
        row = months_rows[index]
        checkpoints.append({
            'horizon_months': index + 1,
            'month': row.get('month'),
            'closing_balance_cents': int(row.get('closing_balance_cents') or 0),
            'low_point_cents': int(row.get('low_point_cents') or 0),
            'safe_margin_cents': int(row.get('safe_margin_cents') or 0),
        })

    return {
        'schema_version': '5.0',
        'as_of': as_of.isoformat(),
        'horizon_months': months,
        'engine_context': {
            'schema_version': '5.3-rc',
            'shared_snapshot': True,
            'cockpit_reused_for_recommendations': True,
            'plan_reused_for_recommendations': True,
            'principle': 'Cockpit, plan, risque et recommandations sont calculés à partir du même snapshot financier de requête.',
        },
        'risk': {
            'score': total,
            'level': level,
            'components': {
                'liquidity': {'score': liquidity_score, 'weight_pct': 45, 'evidence': liquidity_evidence},
                'goals': {'score': goal_score, 'weight_pct': 25, 'evidence': goal_evidence},
                'data_confidence': {'score': confidence_score, 'weight_pct': 20, 'evidence': confidence_evidence},
                'future_events': {'score': event_score, 'weight_pct': 10, 'evidence': {'critical_event_count': len(events)}},
            },
            'method': 'Indice 0–100 : liquidité projetée 45 %, pression des objectifs 25 %, confiance des données 20 %, événements futurs critiques 10 %. Le score priorise l’attention et ne remplace aucun montant financier canonique.',
        },
        'trajectory': {
            'opening_balance_cents': int(projection.get('opening_balance_cents') or 0),
            'closing_balance_cents': int(projection.get('closing_balance_cents') or 0),
            'minimum_safe_margin_cents': int(projection.get('minimum_safe_margin_cents') or 0),
            'protected_cents': int(projection.get('protected_cents') or 0),
            'checkpoints': checkpoints,
        },
        'critical_events': events,
        'goals': {
            'monthly_capacity_cents': int((plan.get('goal_arbitration') or {}).get('monthly_capacity_cents') or 0),
            'unallocated_monthly_capacity_cents': int((plan.get('goal_arbitration') or {}).get('unallocated_monthly_capacity_cents') or 0),
            'items': (plan.get('goal_arbitration') or {}).get('goals') or [],
        },
        'recommendations': {
            'status': recommendations.get('status'),
            'actionable_count': int(recommendations.get('actionable_count') or 0),
            'primary': recommendations.get('primary'),
            'items': recommendations.get('recommendations') or [],
        },
        'principle': 'Pilotage prédictif en lecture seule. Les projections et recommandations sont déterministes et n’exécutent aucune opération.',
    }
