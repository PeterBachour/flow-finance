from __future__ import annotations

from datetime import date

from .v5_recommendations import build_v5_recommendations


_PRIORITY = {'critical': 0, 'high': 1, 'medium': 2, 'watch': 3, 'info': 4, 'positive': 5}
_DECISION_PRIORITY = {'high': 'high', 'medium': 'medium', 'low': 'info'}


def _decision_action(item: dict) -> tuple[str, str]:
    kind = item.get('type') or 'financial_decision'
    actions = {
        'recurring_suggestion': ('Valider ou rejeter cette récurrence avant de l’intégrer au pilotage.', 'movements'),
        'reconciliation_review': ('Confirmer le rapprochement ou corriger l’association proposée.', 'movements'),
        'missing_expected': ('Vérifier si cette échéance a été débitée, reportée ou annulée.', 'month'),
        'stale_balance': ('Actualiser le solde avant une décision importante.', 'wealth'),
        'goal_risk': ('Revoir la contribution, l’échéance ou la priorité de cet objectif.', 'wealth'),
    }
    return actions.get(kind, ('Examiner cette décision financière et choisir l’action adaptée.', 'home'))


def _normalize_financial_decision(item: dict) -> dict:
    action, surface = _decision_action(item)
    return {
        'key': str(item.get('key') or f"decision:{item.get('type') or 'unknown'}"),
        'kind': item.get('type') or 'financial_decision',
        'priority': _DECISION_PRIORITY.get(item.get('priority'), 'medium'),
        'title': item.get('title') or 'Décision financière à traiter',
        'explanation': item.get('detail') or 'Une décision financière ouverte nécessite une validation.',
        'suggested_action': action,
        'source': 'financial_decisions',
        'origin': 'financial_decision',
        'surface': surface,
        'impact_cents': item.get('amount_cents'),
        'status': item.get('status') or 'open',
        'note': item.get('note'),
        'status_updated_at': item.get('status_updated_at'),
        'status_editable': True,
        'evidence': {
            'type': item.get('type'),
            'entity_id': item.get('entity_id'),
            'status': item.get('status'),
        },
        'read_only': True,
    }


def _normalize_recommendation(item: dict) -> dict:
    kind = item.get('kind') or 'recommendation'
    surface = 'wealth' if kind == 'goal' else ('month' if kind in {'forecast', 'pace', 'historical_signal'} else 'home')
    return {
        **item,
        'origin': 'recommendation',
        'surface': surface,
        'status_editable': False,
        'read_only': True,
    }


def _merge_items(recommendations: list[dict], decisions: list[dict]) -> list[dict]:
    """Merge financial choices and model recommendations without double-counting the same key.

    A concrete financial decision wins over a recommendation with the same key because
    it represents a user choice already surfaced by the decision inbox. Recommendation
    evidence is preserved on the merged item when available.
    """
    merged: dict[str, dict] = {}
    for raw in recommendations:
        item = _normalize_recommendation(raw)
        merged[item['key']] = item

    for raw in decisions:
        item = _normalize_financial_decision(raw)
        existing = merged.get(item['key'])
        if existing:
            item['recommendation_context'] = {
                'explanation': existing.get('explanation'),
                'suggested_action': existing.get('suggested_action'),
                'source': existing.get('source'),
                'evidence': existing.get('evidence') or {},
            }
            if existing.get('priority') == 'critical':
                item['priority'] = 'critical'
            if item.get('impact_cents') is None:
                item['impact_cents'] = existing.get('impact_cents')
        merged[item['key']] = item

    return sorted(merged.values(), key=lambda row: (_PRIORITY.get(row.get('priority'), 99), row.get('key') or ''))


def _recent_closed(conn, decisions: list[dict], *, limit: int = 6) -> list[dict]:
    """Return recent closed financial decisions with their persisted note and timestamp.

    The status table is metadata only; reading it never changes financial data. The
    helper tolerates lightweight test doubles that do not expose a database connection.
    """
    metadata: dict[str, dict] = {}
    try:
        rows = conn.execute(
            "SELECT item_key,status,note,updated_at FROM decision_inbox_status WHERE status IN ('done','dismissed')"
        ).fetchall()
        metadata = {str(row['item_key']): dict(row) for row in rows}
    except Exception:
        metadata = {}

    history = []
    for raw in decisions:
        status = raw.get('status') or 'open'
        if status not in {'done', 'dismissed'}:
            continue
        item = dict(raw)
        persisted = metadata.get(str(item.get('key'))) or {}
        if persisted:
            item['status'] = persisted.get('status') or status
            item['note'] = persisted.get('note')
            item['status_updated_at'] = persisted.get('updated_at')
        normalized = _normalize_financial_decision(item)
        history.append(normalized)

    history.sort(
        key=lambda row: (
            row.get('status_updated_at') or '',
            row.get('key') or '',
        ),
        reverse=True,
    )
    return history[:max(1, int(limit))]


def build_v52_decision_center(conn, *, as_of: date, financial_decisions: list[dict] | None = None,
                              closed_decisions: list[dict] | None = None,
                              quality_review_count: int = 0, months: int = 6,
                              recommendations: dict | None = None) -> dict:
    decisions = financial_decisions or []
    if recommendations is None:
        recommendations = build_v5_recommendations(
            conn,
            as_of=as_of,
            financial_decisions=decisions,
            months=months,
        )
    items = _merge_items(recommendations.get('recommendations') or [], decisions)
    actionable = [item for item in items if item.get('priority') not in {'positive', 'info'}]
    financial_choice_count = sum(1 for item in items if item.get('origin') == 'financial_decision')
    recommendation_count = sum(1 for item in items if item.get('origin') == 'recommendation')
    recent_closed = _recent_closed(conn, closed_decisions or [], limit=6)

    return {
        'schema_version': '5.2',
        'as_of': as_of.isoformat(),
        'status': 'action_required' if actionable else 'stable',
        'actionable_count': len(actionable),
        'financial_choice_count': financial_choice_count,
        'recommendation_count': recommendation_count,
        'quality_review_count': max(0, int(quality_review_count)),
        'primary': items[0] if items else None,
        'items': items[:12],
        'recent_closed': recent_closed,
        'principle': (
            'Le centre de décision fusionne les choix financiers ouverts et les recommandations V5, '
            'sans mélanger les tâches de qualité de données. Une décision existante prime sur une '
            'recommandation portant la même clé. Seul le statut d’une vraie décision financière peut '
            'être modifié ; les notes et statuts sont des métadonnées de pilotage et aucune donnée '
            'financière n’est modifiée automatiquement.'
        ),
        'sources': ['v4.7_financial_decisions', 'v5_recommendations', 'decision_inbox_status'],
    }
