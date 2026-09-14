from __future__ import annotations


def build_history_readiness(coverage: dict) -> dict:
    summary = coverage.get('summary') or {}
    months = coverage.get('months') or []
    actions = coverage.get('actions') or []

    statement_pct = float(summary.get('statement_coverage_pct') or 0)
    payroll_pct = float(summary.get('payroll_coverage_pct') or 0)
    window = max(1, int(coverage.get('window_months') or len(months) or 1))
    complete_months = int(summary.get('complete_months') or 0)
    review_months = int(summary.get('review_months') or 0)
    duplicate_months = int(summary.get('duplicate_months') or 0)

    complete_pct = min(100.0, complete_months / window * 100)
    base_score = statement_pct * .45 + payroll_pct * .25 + complete_pct * .30
    penalty = min(30.0, review_months * 4.0 + duplicate_months * 6.0)
    score = max(0, min(100, round(base_score - penalty)))

    recent = months[-6:]
    recent_missing_statements = [row['period'] for row in recent if not row.get('statement', {}).get('present')]
    recent_unverified_statements = [
        row['period'] for row in recent
        if row.get('statement', {}).get('present') and not row.get('statement', {}).get('verified')
    ]
    recent_missing_payrolls = [row['period'] for row in recent if not row.get('payroll', {}).get('present')]

    blockers = []
    if recent_missing_statements:
        blockers.append({
            'key': 'recent_statement_gap',
            'title': 'Relevés récents manquants',
            'detail': f"{len(recent_missing_statements)} mois récent(s) sans relevé",
            'periods': recent_missing_statements,
        })
    if recent_unverified_statements:
        blockers.append({
            'key': 'recent_statement_review',
            'title': 'Relevés récents non vérifiés',
            'detail': f"{len(recent_unverified_statements)} mois récent(s) à fiabiliser",
            'periods': recent_unverified_statements,
        })
    if duplicate_months:
        blockers.append({
            'key': 'duplicate_periods',
            'title': 'Doublons historiques à vérifier',
            'detail': f"{duplicate_months} période(s) potentiellement dupliquée(s)",
            'periods': sorted(set((coverage.get('duplicates') or {}).get('statements', []) + (coverage.get('duplicates') or {}).get('payrolls', []))),
        })

    trend_ready = not recent_missing_statements and not recent_unverified_statements and duplicate_months == 0 and statement_pct >= 75
    payroll_ready = not recent_missing_payrolls and payroll_pct >= 75

    if trend_ready and score >= 90:
        status = 'ready'
        label = 'Historique fiable'
        confidence = 'high'
    elif trend_ready and score >= 70:
        status = 'usable'
        label = 'Historique exploitable'
        confidence = 'medium'
    elif score >= 50:
        status = 'limited'
        label = 'Historique partiel'
        confidence = 'low'
    else:
        status = 'insufficient'
        label = 'Historique insuffisant'
        confidence = 'low'

    ranked_actions = []
    priority_rank = {'high': 0, 'medium': 1, 'low': 2}
    for action in actions:
        item = dict(action)
        item['why'] = {
            'missing_statements': 'Les relevés sont la base du rapprochement et des tendances de dépenses.',
            'statement_reviews': 'Un relevé non vérifié réduit la confiance dans les tendances et projections.',
            'missing_payrolls': 'Les fiches de paie améliorent la lecture des revenus structurels.',
            'duplicate_periods': 'Un doublon peut surévaluer revenus, dépenses ou soldes historiques.',
        }.get(item.get('key'), 'Cette action améliore la qualité de l’historique.')
        ranked_actions.append(item)
    ranked_actions.sort(key=lambda item: (priority_rank.get(item.get('priority'), 9), -int(item.get('count') or 0), item.get('key', '')))

    primary_action = ranked_actions[0] if ranked_actions else None
    gate = {
        'trends': {
            'ready': trend_ready,
            'label': 'Prêt' if trend_ready else 'À fiabiliser',
            'reason': 'Les 6 derniers mois de relevés sont présents et vérifiés.' if trend_ready else 'Les tendances restent limitées tant que les relevés récents ne sont pas complets et vérifiés.',
        },
        'income_analysis': {
            'ready': payroll_ready,
            'label': 'Prêt' if payroll_ready else 'Partiel',
            'reason': 'Les revenus récents sont documentés.' if payroll_ready else 'Des fiches de paie récentes manquent encore.',
        },
        'predictive_models': {
            'ready': trend_ready and score >= 80,
            'label': 'Prêt' if trend_ready and score >= 80 else 'Prudence',
            'reason': 'La profondeur et la qualité historiques sont suffisantes.' if trend_ready and score >= 80 else 'Flow doit conserver un niveau de confiance prudent sur les projections historiques.',
        },
    }

    return {
        'score': score,
        'status': status,
        'label': label,
        'confidence': confidence,
        'trend_ready': trend_ready,
        'payroll_ready': payroll_ready,
        'recent_window_months': len(recent),
        'recent_gaps': {
            'statements': recent_missing_statements,
            'unverified_statements': recent_unverified_statements,
            'payrolls': recent_missing_payrolls,
        },
        'blockers': blockers,
        'gates': gate,
        'primary_action': primary_action,
        'actions': ranked_actions,
        'method': 'Score V5.6 : relevés 45 %, paies 25 %, mois complets 30 %, avec pénalité pour revues et doublons. Les tendances exigent en plus 6 mois récents sans trou de relevé ni revue ouverte.',
        'read_only': True,
    }
