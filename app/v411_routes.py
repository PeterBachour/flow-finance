from __future__ import annotations

from datetime import date

from fastapi import APIRouter

from .v47_routes import decision_priorities, system_diagnostic
from .v49_routes import month_status
from .v410_routes import wealth_readiness

router = APIRouter(prefix='/api/v4.11', tags=['Flow V4.11'])


def _previous_month(today: date) -> str:
    if today.month == 1:
        return f'{today.year - 1:04d}-12'
    return f'{today.year:04d}-{today.month - 1:02d}'


@router.get('/pre-v5-readiness')
def pre_v5_readiness():
    today = date.today()
    previous_month = _previous_month(today)

    diagnostic = system_diagnostic()
    decisions = decision_priorities()
    wealth = wealth_readiness()
    consolidation = month_status(previous_month)

    gates = []

    commit_known = diagnostic.get('commit_status') == 'known'
    gates.append({
        'key': 'runtime_identity',
        'label': 'Version et commit identifiables',
        'status': 'ok' if commit_known else 'warning',
        'detail': (
            f"Version {diagnostic.get('version')} · commit {diagnostic.get('labels', {}).get('commit', 'Non injecté')}"
            if commit_known
            else f"Version {diagnostic.get('version')} · commit non injecté"
        ),
    })

    previous_consolidated = consolidation.get('status') == 'consolidated'
    gates.append({
        'key': 'previous_month',
        'label': f'Mois {previous_month} consolidé',
        'status': 'ok' if previous_consolidated else 'warning',
        'detail': {
            'ready': 'Un relevé validé est prêt à être clôturé.',
            'blocked': 'Le relevé existe mais comporte encore des points à revoir.',
            'statement_missing': 'Aucun relevé de clôture exploitable n’est disponible.',
            'consolidated': 'Le mois est consolidé à partir d’un relevé validé.',
        }.get(consolidation.get('status'), 'Statut de clôture à vérifier.'),
    })

    stale = int(wealth.get('summary', {}).get('stale_accounts') or 0)
    undated = int(wealth.get('summary', {}).get('undated_accounts') or 0)
    wealth_clean = stale == 0 and undated == 0
    gates.append({
        'key': 'wealth_freshness',
        'label': 'Patrimoine suffisamment frais',
        'status': 'ok' if wealth_clean else 'warning',
        'detail': (
            'Toutes les valeurs patrimoniales suivies sont datées de moins de 32 jours.'
            if wealth_clean
            else f'{stale} valeur(s) ancienne(s) · {undated} valeur(s) non datée(s).'
        ),
    })

    uncategorized = int(diagnostic.get('database', {}).get('uncategorized') or 0)
    gates.append({
        'key': 'categorization',
        'label': 'Qualité de catégorisation',
        'status': 'ok' if uncategorized == 0 else 'info',
        'detail': (
            'Aucun mouvement non catégorisé.'
            if uncategorized == 0
            else f'{uncategorized} mouvement(s) restent à catégoriser ; ce point ne bloque pas le moteur financier canonique.'
        ),
    })

    decision_count = int(decisions.get('open_count') or 0)
    gates.append({
        'key': 'financial_decisions',
        'label': 'Décisions financières',
        'status': 'ok' if decision_count == 0 else 'info',
        'detail': (
            'Aucune décision financière en attente.'
            if decision_count == 0
            else f'{decision_count} décision(s) financière(s) restent à traiter.'
        ),
    })

    blockers = [gate for gate in gates if gate['status'] == 'warning']
    return {
        'as_of': today.isoformat(),
        'release_status': 'ready' if not blockers else 'attention',
        'blocking_count': len(blockers),
        'gates': gates,
        'summary': {
            'version': diagnostic.get('version'),
            'commit': diagnostic.get('commit'),
            'previous_month': previous_month,
            'previous_month_status': consolidation.get('status'),
            'wealth_stale_accounts': stale,
            'wealth_undated_accounts': undated,
            'uncategorized_movements': uncategorized,
            'open_financial_decisions': decision_count,
        },
        'principle': 'Ce contrôle est en lecture seule. Il vérifie la cohérence opérationnelle du socle avant V5 sans modifier les données financières.',
    }
