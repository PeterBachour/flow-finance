from __future__ import annotations

from datetime import date

from .v5_engine import build_v5_cockpit
from .v5_planning import build_v5_plan


_PRIORITY = {'critical': 0, 'high': 1, 'medium': 2, 'watch': 3, 'info': 4, 'positive': 5}


def _item(*, key: str, kind: str, priority: str, title: str, explanation: str,
          suggested_action: str, source: str, impact_cents: int | None = None,
          evidence: dict | None = None) -> dict:
    return {
        'key': key,
        'kind': kind,
        'priority': priority,
        'title': title,
        'explanation': explanation,
        'suggested_action': suggested_action,
        'source': source,
        'impact_cents': impact_cents,
        'evidence': evidence or {},
        'read_only': True,
    }


def build_v5_recommendations(conn, *, as_of: date, financial_decisions: list[dict] | None = None,
                             months: int = 6, cockpit: dict | None = None,
                             plan: dict | None = None) -> dict:
    """Build explainable recommendations from one coherent V5 financial snapshot.

    Callers that already computed the cockpit and/or plan can pass them explicitly to
    avoid rebuilding the same financial state. Standalone callers keep the historical
    behaviour because missing inputs are calculated locally.
    """
    decisions = financial_decisions or []
    if cockpit is None:
        cockpit = build_v5_cockpit(conn, as_of=as_of, financial_decisions=decisions)
    if plan is None:
        plan = build_v5_plan(conn, months=months, today=as_of)

    decision = cockpit.get('decision') or {}
    forecast = cockpit.get('forecast') or {}
    confidence = cockpit.get('confidence') or {}
    historical = cockpit.get('historical_context') or {}
    arbitration = plan.get('goal_arbitration') or {}

    safe = int(decision.get('safe_until_income_cents') or 0)
    daily = int(decision.get('daily_pace_cents') or 0)
    margin = int(forecast.get('projected_margin_above_safety_cents') or 0)
    projected_balance = int(forecast.get('projected_bank_balance_cents') or 0)
    items: list[dict] = []

    if safe <= 0:
        items.append(_item(
            key='protect_liquidity', kind='liquidity', priority='critical',
            title='Réduire immédiatement les dépenses variables',
            explanation='Le Safe disponible jusqu’au prochain revenu est nul ou négatif.',
            suggested_action='Limiter les dépenses discrétionnaires et revoir les engagements avant toute nouvelle dépense.',
            source='safe_to_spend', impact_cents=safe,
            evidence={'safe_until_income_cents': safe, 'daily_pace_cents': daily},
        ))
    elif margin < 0:
        items.append(_item(
            key='restore_margin', kind='forecast', priority='critical',
            title='Restaurer la marge de fin de cycle',
            explanation='La projection passe sous la réserve cible avant le prochain revenu.',
            suggested_action='Réduire le rythme variable ou reporter une dépense non essentielle.',
            source='validated_forecast', impact_cents=margin,
            evidence={'projected_margin_cents': margin, 'projected_balance_cents': projected_balance},
        ))
    elif daily > 0:
        items.append(_item(
            key='keep_daily_pace', kind='pace', priority='positive',
            title='Maintenir le rythme conseillé',
            explanation='Le Safe et la marge projetée restent positifs avec le rythme actuel.',
            suggested_action='Utiliser le rythme quotidien comme plafond indicatif, pas comme objectif de dépense.',
            source='decision_cockpit', impact_cents=daily,
            evidence={'daily_pace_cents': daily, 'safe_until_income_cents': safe, 'projected_margin_cents': margin},
        ))

    level = confidence.get('level') or 'low'
    age = confidence.get('balance_age_days')
    if level == 'low' or (age is not None and int(age) > 7):
        items.append(_item(
            key='refresh_financial_data', kind='data_confidence', priority='high' if level == 'low' else 'medium',
            title='Actualiser les données avant une décision importante',
            explanation='La confiance du moteur est dégradée par la fraîcheur ou la couverture des données.',
            suggested_action='Actualiser le solde et importer les données disponibles avant un engagement important.',
            source='data_quality',
            evidence={'confidence_level': level, 'balance_age_days': age, 'balance_as_of': confidence.get('balance_as_of')},
        ))

    for goal in arbitration.get('goals') or []:
        gap = int(goal.get('funding_gap_cents') or 0)
        if gap <= 0 or goal.get('status') == 'achieved':
            continue
        priority = 'high' if goal.get('mandatory') or goal.get('status') in {'late', 'off_track'} else 'medium'
        items.append(_item(
            key=f"goal:{goal.get('goal_id')}", kind='goal', priority=priority,
            title=f"Ajuster l’objectif « {goal.get('name')} »",
            explanation='La contribution mensuelle recommandée reste inférieure à l’effort requis pour respecter la trajectoire.',
            suggested_action='Revoir la contribution, l’échéance ou la priorité de cet objectif.',
            source='goal_arbitration', impact_cents=gap,
            evidence={
                'goal_id': goal.get('goal_id'),
                'status': goal.get('status'),
                'required_monthly_cents': goal.get('required_monthly_cents'),
                'recommended_monthly_cents': goal.get('recommended_monthly_cents'),
                'funding_gap_cents': gap,
            },
        ))

    for index, signal in enumerate((historical.get('signals') or [])[:3]):
        items.append(_item(
            key=f"historical:{index}:{signal.get('kind') or 'signal'}", kind='historical_signal', priority='watch',
            title=signal.get('title') or 'Écart historique à surveiller',
            explanation=signal.get('detail') or 'Un écart significatif est détecté par rapport à l’historique clôturé.',
            suggested_action='Vérifier si cet écart est exceptionnel ou s’il doit modifier le rythme futur.',
            source='advanced_analysis', impact_cents=signal.get('amount_cents'),
            evidence={'latest_closed_month': historical.get('latest_closed_month'), 'signal': signal},
        ))

    ordered = sorted(items, key=lambda row: (_PRIORITY.get(row['priority'], 99), row['key']))
    actionable = [row for row in ordered if row['priority'] not in {'positive', 'info'}]
    return {
        'as_of': as_of.isoformat(),
        'schema_version': '5.0',
        'status': 'action_required' if actionable else 'stable',
        'actionable_count': len(actionable),
        'recommendations': ordered,
        'primary': ordered[0] if ordered else None,
        'principle': 'Les recommandations sont déterministes, explicables et en lecture seule. Elles n’exécutent aucun virement, aucune réservation et aucune modification de donnée.',
        'sources': ['v5_cockpit', 'v5_plan', 'goal_arbitration', 'advanced_analysis', 'data_quality'],
    }
