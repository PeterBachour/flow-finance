from __future__ import annotations


PRIORITY_RANK = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
ACTION_RANK = {'missing_statement': 0, 'review_statement': 1, 'duplicate_period': 2, 'missing_payroll': 3}


def _action(
    *,
    key: str,
    kind: str,
    period: str,
    priority: str,
    title: str,
    detail: str,
    impact: str,
    target: str,
    evidence: str,
    expected_document: str | None,
    unlocks: list[str],
) -> dict:
    return {
        'id': f'{key}:{period}',
        'key': key,
        'kind': kind,
        'period': period,
        'priority': priority,
        'title': title,
        'detail': detail,
        'impact': impact,
        'target': target,
        'evidence': evidence,
        'expected_document': expected_document,
        'unlocks': unlocks,
        'status': 'open',
        'requires_confirmation': True,
    }


def _period_rank(period: str) -> int:
    try:
        year, month = (int(part) for part in period.split('-', 1))
        return -(year * 12 + month)
    except (TypeError, ValueError):
        return 0


def build_data_quality_actions(coverage: dict, readiness: dict) -> dict:
    actions: list[dict] = []
    recent_periods = {row.get('period') for row in (coverage.get('months') or [])[-6:]}

    for period in (coverage.get('gaps') or {}).get('statements', []):
        recent = period in recent_periods
        actions.append(_action(
            key='missing_statement', kind='import_statement', period=period,
            priority='critical' if recent else 'high',
            title=f'Importer le relevé {period}',
            detail='Aucun relevé bancaire n’est disponible pour cette période.',
            impact='Bloque la fiabilité des tendances récentes.' if recent else 'Réduit la profondeur de l’historique.',
            target='bulk_import',
            evidence=f'Couverture relevé {period} : absente.',
            expected_document=f'Relevé bancaire {period}',
            unlocks=['trends', 'predictive_models'] if recent else ['historical_depth'],
        ))

    for period in coverage.get('review_periods', []):
        recent = period in recent_periods
        actions.append(_action(
            key='review_statement', kind='review_statement', period=period,
            priority='critical' if recent else 'high',
            title=f'Fiabiliser le relevé {period}',
            detail='Le relevé existe mais comporte encore une revue ou une alerte.',
            impact='Empêche Flow de considérer ce mois comme vérifié.',
            target='statement_review',
            evidence=f'Relevé {period} présent mais qualité non vérifiée ou lignes de revue ouvertes.',
            expected_document=None,
            unlocks=['trends', 'predictive_models'] if recent else ['historical_depth'],
        ))

    duplicate_periods = sorted(set(
        (coverage.get('duplicates') or {}).get('statements', [])
        + (coverage.get('duplicates') or {}).get('payrolls', [])
    ))
    for period in duplicate_periods:
        actions.append(_action(
            key='duplicate_period', kind='review_duplicate', period=period,
            priority='high',
            title=f'Contrôler les doublons {period}',
            detail='Plusieurs sources confirmées existent pour la même période.',
            impact='Peut surévaluer revenus, dépenses ou couverture historique.',
            target='history_details',
            evidence=f'Plus d’une source confirmée détectée pour {period}.',
            expected_document=None,
            unlocks=['trends', 'predictive_models', 'income_analysis'],
        ))

    for period in (coverage.get('gaps') or {}).get('payrolls', []):
        recent = period in recent_periods
        actions.append(_action(
            key='missing_payroll', kind='import_payroll', period=period,
            priority='medium' if recent else 'low',
            title=f'Importer la fiche de paie {period}',
            detail='Aucune fiche de paie n’est documentée pour cette période.',
            impact='Améliore l’analyse des revenus structurels.',
            target='bulk_import',
            evidence=f'Couverture fiche de paie {period} : absente.',
            expected_document=f'Fiche de paie {period}',
            unlocks=['income_analysis'],
        ))

    actions.sort(key=lambda item: (
        PRIORITY_RANK.get(item['priority'], 9),
        0 if item['period'] in recent_periods else 1,
        ACTION_RANK.get(item['key'], 9),
        _period_rank(item['period']),
    ))

    counts = {level: sum(1 for item in actions if item['priority'] == level) for level in PRIORITY_RANK}
    blockers = [item for item in actions if item['priority'] in {'critical', 'high'}]

    return {
        'score': readiness.get('score'),
        'readiness_status': readiness.get('status'),
        'open_count': len(actions),
        'blocking_count': len(blockers),
        'counts': counts,
        'primary_action': actions[0] if actions else None,
        'actions': actions,
        'read_only': True,
        'method': 'V5.7 priorise d’abord les relevés récents manquants, puis les relevés à vérifier et les doublons, ensuite les paies. À priorité égale, la période la plus récente passe d’abord. Chaque action expose sa preuve, le document attendu et les analyses débloquées, sans correction automatique.',
    }
