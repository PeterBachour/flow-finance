from __future__ import annotations

from datetime import date

from .certified_safe_to_spend import build_certified_safe_to_spend
from .safe_to_spend import _table_exists, recurring_is_fresh


PROVENANCE = ('source_type', 'source_id', 'source_url', 'source_date', 'source_status', 'confidence', 'source_key')


def _columns(conn, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f'PRAGMA table_info({table})').fetchall()}


def _select(conn, table: str, base: tuple[str, ...], where: str, params=()) -> list[dict]:
    if not _table_exists(conn, table):
        return []
    available = _columns(conn, table)
    fields = [name for name in (*base, *PROVENANCE) if name in available]
    rows = conn.execute(f"SELECT {','.join(fields)} FROM {table} WHERE {where}", params).fetchall()
    return [dict(row) for row in rows]


def _evidence(item: dict, table: str, *, included: bool = True, reason: str | None = None) -> dict:
    return {
        'entity': table,
        'entity_id': item.get('id'),
        'label': item.get('label') or item.get('name') or table,
        'date': item.get('due_date') or item.get('balance_as_of') or item.get('last_seen_date') or item.get('source_date'),
        'amount_cents': item.get('amount_cents', item.get('current_balance_cents')),
        'included': included,
        'reason': reason,
        'provenance': {key: item.get(key) for key in PROVENANCE if item.get(key) is not None},
    }


def _previous_balance_comparison(conn, certified: dict) -> dict:
    if not _table_exists(conn, 'account_balance_history'):
        return {'available': False, 'reason': 'no_balance_history'}
    account_rows = conn.execute(
        "SELECT id,balance_as_of,current_balance_cents FROM accounts WHERE is_active=1 AND include_in_safe_to_spend=1"
    ).fetchall()
    dates = [row['balance_as_of'] for row in account_rows if row['balance_as_of']]
    if not dates:
        return {'available': False, 'reason': 'no_current_balance_date'}
    current_date = min(dates)
    account_ids = [int(row['id']) for row in account_rows]
    if not account_ids:
        return {'available': False, 'reason': 'no_included_account'}
    placeholders = ','.join('?' for _ in account_ids)
    previous_date_row = conn.execute(
        f"SELECT MAX(balance_date) FROM account_balance_history WHERE account_id IN ({placeholders}) AND balance_date<? AND status='confirmed'",
        (*account_ids, current_date),
    ).fetchone()
    previous_date = previous_date_row[0] if previous_date_row else None
    if not previous_date:
        return {'available': False, 'reason': 'no_previous_confirmed_balance'}
    previous_balance = conn.execute(
        f"SELECT COALESCE(SUM(balance_cents),0) FROM account_balance_history WHERE account_id IN ({placeholders}) AND balance_date=? AND status='confirmed'",
        (*account_ids, previous_date),
    ).fetchone()[0]
    current_balance = int(certified['components']['current_balance_cents'])
    delta = current_balance - int(previous_balance or 0)
    calculated = int(certified['safe_to_spend']['calculated_cents'])
    previous_estimate = max(0, calculated - delta)
    return {
        'available': True,
        'certainty': 'estimated',
        'method': 'balance_delta_only',
        'warning': 'Estimation à composantes constantes, pas un calcul historiquement persisté',
        'previous_balance_date': previous_date,
        'previous_balance_cents': int(previous_balance or 0),
        'current_balance_cents': current_balance,
        'balance_delta_cents': delta,
        'estimated_previous_safe_to_spend_cents': previous_estimate,
        'current_calculated_safe_to_spend_cents': calculated,
        'estimated_change_cents': calculated - previous_estimate,
    }


def build_safe_to_spend_explanation(
    conn,
    *,
    as_of: date | None = None,
    horizon_days: int | None = None,
    stale_reference_date: date | None = None,
) -> dict:
    certified = build_certified_safe_to_spend(
        conn, as_of=as_of, horizon_days=horizon_days, stale_reference_date=stale_reference_date
    )
    observed = certified['as_of']
    horizon_end = certified['horizon']['end']

    accounts = _select(
        conn, 'accounts', ('id', 'name', 'current_balance_cents', 'balance_as_of'),
        'is_active=1 AND include_in_safe_to_spend=1'
    )
    planned = _select(
        conn, 'planned_transactions', ('id', 'label', 'amount_cents', 'due_date', 'certainty'),
        "status='planned' AND kind='commitment' AND amount_cents<0 AND due_date>? AND due_date<=?",
        (observed, horizon_end),
    )
    recurring = _select(
        conn, 'recurring_transactions',
        ('id', 'label', 'amount_cents', 'last_seen_date', 'certainty', 'source_type', 'detection_status'),
        "is_active=1 AND amount_cents<0 AND COALESCE(kind,'commitment')='commitment' AND COALESCE(category,'')<>'Transfert interne'",
    )
    goals = _select(
        conn, 'financial_goals', ('id', 'name', 'monthly_contribution_cents'),
        'is_active=1 AND monthly_contribution_cents>0',
    )

    observed_date = date.fromisoformat(observed)
    recurring_evidence = []
    for item in recurring:
        detected = (item.get('source_type') or '').lower() in {'history', 'auto', 'detected'}
        accepted = item.get('detection_status', 'accepted') == 'accepted'
        fresh = not detected or recurring_is_fresh(item.get('last_seen_date'), observed_date)
        included = accepted and fresh
        reason = None if included else ('not_accepted' if not accepted else 'stale')
        recurring_evidence.append(_evidence(item, 'recurring_transactions', included=included, reason=reason))

    components = certified['components']
    lines = [
        {
            'key': 'confirmed_balance', 'label': 'Solde bancaire retenu', 'operator': 'base',
            'amount_cents': int(components['current_balance_cents']), 'certainty': 'confirmed',
            'sources': [_evidence(item, 'accounts') for item in accounts],
        },
        {
            'key': 'planned_commitments', 'label': 'Échéances confirmées', 'operator': 'subtract',
            'amount_cents': int(components['confirmed_commitments_cents']), 'certainty': 'confirmed',
            'sources': [_evidence(item, 'planned_transactions') for item in planned],
        },
        {
            'key': 'recurring_commitments', 'label': 'Charges récurrentes validées', 'operator': 'subtract',
            'amount_cents': int(components['probable_recurring_cents']), 'certainty': 'probable',
            'sources': recurring_evidence,
        },
        {
            'key': 'goal_reservations', 'label': 'Objectifs avec impact de trésorerie', 'operator': 'subtract',
            'amount_cents': int(components['goal_reservations_cents']), 'certainty': 'confirmed',
            'sources': [_evidence(item, 'financial_goals', included=False, reason='allocation_driven') for item in goals],
            'mode': certified['breakdown'][3].get('mode'),
        },
        {
            'key': 'safety_reserve', 'label': 'Marge de sécurité', 'operator': 'subtract',
            'amount_cents': int(components['safety_reserve_cents']), 'certainty': 'confirmed',
            'sources': [{'entity': 'financial_policy', 'entity_id': 'safety_reserve', 'label': 'Politique de réserve', 'included': True}],
        },
    ]
    for line in lines:
        line['source_count'] = len(line['sources'])
        line['included_source_count'] = sum(1 for source in line['sources'] if source.get('included'))

    deductions = sum(line['amount_cents'] for line in lines if line['operator'] == 'subtract')
    reconstructed = lines[0]['amount_cents'] - deductions
    expected = int(certified['safe_to_spend']['calculated_cents'])

    return {
        'schema_version': '6.4',
        'as_of': observed,
        'horizon': certified['horizon'],
        'availability': certified['availability'],
        'confidence': certified['confidence'],
        'safe_to_spend': certified['safe_to_spend'],
        'formula': {
            'expression': 'balance - planned - recurring - goal_cash_impact - safety_reserve',
            'lines': lines,
            'reconstructed_cents': reconstructed,
            'expected_cents': expected,
            'difference_cents': reconstructed - expected,
            'reconciled': reconstructed == expected,
        },
        'low_point': certified['projections']['prudent'],
        'comparison': _previous_balance_comparison(conn, certified),
        'data_actions': [
            {
                'key': 'refresh_balance',
                'required': not certified['availability']['available'],
                'reason': certified['availability']['status'],
                'label': 'Importer un relevé récent',
            }
        ],
        'controls': {
            'read_only': True,
            'ledger_unchanged': True,
            'goals_not_double_counted': certified['controls']['goals_not_double_counted'],
            'every_component_has_evidence': all(line['source_count'] > 0 or line['amount_cents'] == 0 for line in lines),
            'formula_reconciled': reconstructed == expected,
        },
    }
