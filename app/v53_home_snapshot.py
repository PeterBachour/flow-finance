from __future__ import annotations

from datetime import date

from .v5_engine import build_v5_cockpit
from .v5_planning import build_v5_plan
from .v5_predictive import build_v5_predictive_pilot
from .v5_recommendations import build_v5_recommendations
from .v52_decisions import build_v52_decision_center


_DECISION_RANK = {'high': 0, 'medium': 1, 'low': 2}


def select_open_financial_decisions(items: list[dict], *, limit: int = 8) -> list[dict]:
    """Mirror the V4.7 decision-priority ordering from one already-loaded inbox."""
    open_items = [item for item in items if (item.get('status') or 'open') == 'open']
    open_items.sort(
        key=lambda item: (
            _DECISION_RANK.get(item.get('priority'), 9),
            item.get('type', ''),
            item.get('key', ''),
        )
    )
    return open_items[:max(1, int(limit))]


def build_v53_home_snapshot(conn, *, as_of: date, all_financial_decisions: list[dict] | None = None,
                            quality_review_count: int = 0, months: int = 6) -> dict:
    """Build every V5 home decision surface from one request-scoped snapshot.

    The function is read-only. Cockpit and plan are calculated once, recommendations
    reuse both, and predictive/decision-center reuse the same recommendations. This
    guarantees that all V5 home overlays explain the same financial state.
    """
    months = max(1, min(12, int(months)))
    all_decisions = all_financial_decisions or []
    open_decisions = select_open_financial_decisions(all_decisions)

    cockpit = build_v5_cockpit(
        conn,
        as_of=as_of,
        financial_decisions=open_decisions,
    )
    plan = build_v5_plan(conn, months=months, today=as_of)
    recommendations = build_v5_recommendations(
        conn,
        as_of=as_of,
        financial_decisions=open_decisions,
        months=months,
        cockpit=cockpit,
        plan=plan,
    )
    predictive = build_v5_predictive_pilot(
        conn,
        as_of=as_of,
        financial_decisions=open_decisions,
        months=months,
        cockpit=cockpit,
        plan=plan,
        recommendations=recommendations,
    )
    decision_center = build_v52_decision_center(
        conn,
        as_of=as_of,
        financial_decisions=open_decisions,
        closed_decisions=all_decisions,
        quality_review_count=quality_review_count,
        months=months,
        recommendations=recommendations,
    )

    open_count = sum(1 for item in all_decisions if (item.get('status') or 'open') == 'open')
    cockpit_payload = {
        **cockpit,
        'open_financial_decisions': open_count,
        'quality_review_count': max(0, int(quality_review_count)),
    }

    return {
        'schema_version': '5.3',
        'as_of': as_of.isoformat(),
        'horizon_months': months,
        'cockpit': cockpit_payload,
        'decision_center': decision_center,
        'predictive': predictive,
        'engine_context': {
            'shared_home_snapshot': True,
            'cockpit_builds': 1,
            'plan_builds': 1,
            'recommendation_builds': 1,
            'decision_inbox_reads': 1,
            'principle': 'Toutes les surfaces V5 de l’Accueil utilisent le même snapshot financier de requête.',
        },
        'principle': 'Snapshot V5.3 en lecture seule : aucune transaction, aucun solde, aucun budget et aucun objectif ne sont modifiés.',
    }
