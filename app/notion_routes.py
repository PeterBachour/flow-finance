import json

from fastapi import APIRouter

from .db import connection
from .notion_import import apply_import, preview, status

router = APIRouter(prefix='/api/notion', tags=['notion'])


@router.get('/status')
def notion_status():
    return status()


@router.get('/preview')
def notion_preview():
    data = preview()
    with connection() as conn:
        data['existing_flow'] = {
            'accounts': conn.execute('SELECT COUNT(*) n FROM accounts').fetchone()['n'],
            'transactions': conn.execute('SELECT COUNT(*) n FROM transactions').fetchone()['n'],
            'goals': conn.execute('SELECT COUNT(*) n FROM financial_goals').fetchone()['n'],
        }
        data['open_conflicts'] = conn.execute("SELECT COUNT(*) n FROM notion_import_conflicts WHERE resolution='needs_review'").fetchone()['n']
    return data


@router.post('/import')
def notion_import():
    return apply_import('manual')


@router.post('/sync')
def notion_sync():
    # V0.7 sync is incremental and idempotent against the latest Notion snapshot
    # extracted through the connected Notion workspace. Runtime Flow never depends
    # on Notion for calculations.
    return apply_import('sync')


@router.get('/conflicts')
def notion_conflicts():
    with connection() as conn:
        rows = conn.execute("SELECT * FROM notion_import_conflicts WHERE resolution='needs_review' ORDER BY id DESC").fetchall()
    return [dict(row) for row in rows]


@router.get('/audit')
def notion_audit():
    with connection() as conn:
        accounts = [dict(r) for r in conn.execute('SELECT id,name,kind,current_balance_cents,balance_as_of,include_in_wealth,include_in_liquidity,include_in_safe_to_spend,source_status FROM accounts WHERE is_active=1 ORDER BY id').fetchall()]
        liquid = conn.execute('SELECT COALESCE(SUM(current_balance_cents),0) total FROM accounts WHERE is_active=1 AND include_in_liquidity=1').fetchone()['total']
        wealth = conn.execute('SELECT COALESCE(SUM(current_balance_cents),0) total FROM accounts WHERE is_active=1 AND include_in_wealth=1').fetchone()['total']
        notion_transactions = conn.execute("SELECT COUNT(*) n FROM transactions WHERE source_type='notion'").fetchone()['n']
        transfers = conn.execute("SELECT COUNT(*) n FROM transactions WHERE source_type='notion' AND is_internal_transfer=1").fetchone()['n']
        planned = conn.execute("SELECT COUNT(*) n FROM planned_transactions WHERE source_type='notion' AND status='planned'").fetchone()['n']
        goals = conn.execute("SELECT COUNT(*) n FROM financial_goals WHERE source_type='notion'").fetchone()['n']
        rules = conn.execute("SELECT COUNT(*) n FROM financial_rules WHERE source_type='notion'").fetchone()['n']
        duplicates = conn.execute("SELECT COUNT(*) n FROM (SELECT source_key,COUNT(*) c FROM transactions WHERE source_key IS NOT NULL GROUP BY source_key HAVING c>1)").fetchone()['n']
        last = conn.execute('SELECT stats_json FROM notion_import_runs ORDER BY id DESC LIMIT 1').fetchone()
    return {
        'accounts': accounts,
        'totals': {'liquidity_cents': liquid, 'financial_wealth_cents': wealth},
        'notion_transactions': notion_transactions,
        'notion_transfers': transfers,
        'planned_transactions': planned,
        'goals': goals,
        'rules': rules,
        'duplicate_source_keys': duplicates,
        'last_import_stats': json.loads(last['stats_json']) if last and last['stats_json'] else None,
    }
