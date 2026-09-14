import json
from datetime import datetime, timezone

from .db import connection
from .notion_dataset import (
    ACCOUNTS,
    BALANCE_HISTORY,
    CONFIRMED_TRANSACTIONS,
    DECISIONS,
    GOALS,
    HISTORY_SOURCE_URL,
    MONTHLY_HISTORY,
    RECURRING,
    REFERENCE_SOURCE_ID,
    REFERENCE_SOURCE_URL,
    ROOT_SOURCE_ID,
    ROOT_SOURCE_URL,
    RULES,
    SOURCE_REVISION,
)


def cents(value):
    if value is None:
        return None
    return round(float(value) * 100)


def _ensure_import_schema(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS monthly_financial_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        month TEXT NOT NULL,
        salary_cents INTEGER,
        total_debits_cents INTEGER,
        total_credits_cents INTEGER,
        closing_balance_cents INTEGER,
        fixed_costs_cents INTEGER,
        variable_estimated_cents INTEGER,
        savings_identified_cents INTEGER,
        status TEXT NOT NULL DEFAULT 'confirmed',
        comment TEXT,
        source_type TEXT,
        source_id TEXT,
        source_url TEXT,
        source_date TEXT,
        source_status TEXT,
        confidence REAL,
        source_key TEXT UNIQUE,
        imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_monthly_financial_history_month ON monthly_financial_history(month)')


def _account_id(conn, source_key):
    row = conn.execute('SELECT id FROM accounts WHERE source_key=?', (source_key,)).fetchone()
    if not row:
        raise RuntimeError(f'Account missing after migration: {source_key}')
    return row['id']


def _open_conflict(conn, entity_type, source_key):
    return bool(conn.execute(
        "SELECT 1 FROM notion_import_conflicts WHERE entity_type=? AND source_key=? AND resolution='needs_review' LIMIT 1",
        (entity_type, source_key),
    ).fetchone())


def _record_conflict(conn, run_id, entity_type, source_key, reason, existing_value, incoming_value):
    if conn.execute(
        "SELECT 1 FROM notion_import_conflicts WHERE entity_type=? AND source_key=? AND reason=? AND resolution='needs_review' LIMIT 1",
        (entity_type, source_key, reason),
    ).fetchone():
        return False
    conn.execute(
        'INSERT INTO notion_import_conflicts(run_id,entity_type,source_key,reason,existing_value,incoming_value) VALUES(?,?,?,?,?,?)',
        (run_id, entity_type, source_key, reason, existing_value, incoming_value),
    )
    return True


def _account_metadata_values(item, now, source_status=None):
    return (
        item['name'], item['kind'], item['wealth'], item['liquidity'], item['safe'],
        'notion', ROOT_SOURCE_ID, ROOT_SOURCE_URL, item['as_of'],
        source_status or item['status'], item['confidence'], item['key'], now,
    )


def _merge_accounts(conn, run_id, stats, now):
    for item in ACCOUNTS:
        existing = conn.execute(
            'SELECT * FROM accounts WHERE source_key=? OR lower(name)=lower(?) ORDER BY source_key IS NOT NULL DESC LIMIT 1',
            (item['key'], item['name']),
        ).fetchone()
        incoming_balance = cents(item['balance'])
        if existing and existing['source_key'] not in (None, item['key']):
            if _record_conflict(conn, run_id, 'account', item['key'], 'Existing Flow account has different provenance', json.dumps(dict(existing), default=str), json.dumps(item)):
                stats['conflicts'] += 1
            stats['ignored'] += 1
            continue

        if not existing:
            conn.execute(
                '''INSERT INTO accounts(
                    name,kind,current_balance_cents,balance_as_of,
                    include_in_wealth,include_in_liquidity,include_in_safe_to_spend,
                    source_type,source_id,source_url,source_date,source_status,confidence,source_key,imported_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (item['name'], item['kind'], incoming_balance, item['as_of'], item['wealth'], item['liquidity'], item['safe'], 'notion', ROOT_SOURCE_ID, ROOT_SOURCE_URL, item['as_of'], item['status'], item['confidence'], item['key'], now),
            )
            stats['accounts'] += 1
            continue

        flow_newer = bool(existing['balance_as_of'] and existing['balance_as_of'] > item['as_of'])
        unresolved = _open_conflict(conn, 'account', item['key'])
        first_unmapped_conflict = existing['source_key'] is None and existing['current_balance_cents'] != 0 and existing['current_balance_cents'] != incoming_balance

        if flow_newer:
            conn.execute(
                '''UPDATE accounts SET name=?,kind=?,include_in_wealth=?,include_in_liquidity=?,include_in_safe_to_spend=?,
                   source_type=?,source_id=?,source_url=?,source_date=?,source_status=?,confidence=?,source_key=?,imported_at=? WHERE id=?''',
                _account_metadata_values(item, now, 'flow_newer') + (existing['id'],),
            )
        elif unresolved:
            conn.execute(
                '''UPDATE accounts SET name=?,kind=?,include_in_wealth=?,include_in_liquidity=?,include_in_safe_to_spend=?,
                   source_type=?,source_id=?,source_url=?,source_date=?,source_status=?,confidence=?,source_key=?,imported_at=? WHERE id=?''',
                _account_metadata_values(item, now, 'conflict_preserved') + (existing['id'],),
            )
        elif first_unmapped_conflict:
            if _record_conflict(conn, run_id, 'account', item['key'], 'Existing Flow balance differs from Notion; preserved pending review', str(existing['current_balance_cents']), str(incoming_balance)):
                stats['conflicts'] += 1
            conn.execute(
                '''UPDATE accounts SET name=?,kind=?,include_in_wealth=?,include_in_liquidity=?,include_in_safe_to_spend=?,
                   source_type=?,source_id=?,source_url=?,source_date=?,source_status=?,confidence=?,source_key=?,imported_at=? WHERE id=?''',
                _account_metadata_values(item, now, 'conflict_preserved') + (existing['id'],),
            )
        else:
            conn.execute(
                '''UPDATE accounts SET name=?,kind=?,current_balance_cents=?,balance_as_of=?,
                   include_in_wealth=?,include_in_liquidity=?,include_in_safe_to_spend=?,
                   source_type=?,source_id=?,source_url=?,source_date=?,source_status=?,confidence=?,source_key=?,imported_at=? WHERE id=?''',
                (item['name'], item['kind'], incoming_balance, item['as_of'], item['wealth'], item['liquidity'], item['safe'], 'notion', ROOT_SOURCE_ID, ROOT_SOURCE_URL, item['as_of'], item['status'], item['confidence'], item['key'], now, existing['id']),
            )
        stats['accounts'] += 1


def _merge_balance_history(conn, stats, now):
    for account_key, balance_date, balance, status_value, source_key in BALANCE_HISTORY:
        conn.execute(
            '''INSERT INTO account_balance_history(
                account_id,balance_cents,balance_date,status,source_type,source_id,source_url,
                source_date,source_status,confidence,source_key,imported_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(source_key) DO UPDATE SET balance_cents=excluded.balance_cents,status=excluded.status,source_date=excluded.source_date''',
            (_account_id(conn, account_key), cents(balance), balance_date, status_value, 'notion', ROOT_SOURCE_ID, ROOT_SOURCE_URL, balance_date, status_value, 1.0, source_key, now),
        )
        stats['balances'] += 1


def _merge_monthly_history(conn, stats, now):
    for item in MONTHLY_HISTORY:
        conn.execute(
            '''INSERT INTO monthly_financial_history(
                month,salary_cents,total_debits_cents,total_credits_cents,closing_balance_cents,
                fixed_costs_cents,variable_estimated_cents,savings_identified_cents,status,comment,
                source_type,source_id,source_url,source_date,source_status,confidence,source_key,imported_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(source_key) DO UPDATE SET
                salary_cents=excluded.salary_cents,total_debits_cents=excluded.total_debits_cents,
                total_credits_cents=excluded.total_credits_cents,closing_balance_cents=excluded.closing_balance_cents,
                fixed_costs_cents=excluded.fixed_costs_cents,variable_estimated_cents=excluded.variable_estimated_cents,
                savings_identified_cents=excluded.savings_identified_cents,comment=excluded.comment''',
            (item['month'], cents(item['salary']), cents(item['debits']), cents(item['credits']), cents(item['closing']), cents(item['fixed']), cents(item['variable']), cents(item['savings']), item['status'], item['comment'], 'notion', item['source_id'], item['source_url'], item['month']+'-01', item['status'], 0.95, item['key'], now),
        )
        stats['monthly_history'] += 1


def _merge_transactions(conn, stats, now):
    for item in CONFIRMED_TRANSACTIONS:
        destination_id = _account_id(conn, item['destination']) if item.get('destination') else None
        conn.execute(
            '''INSERT INTO transactions(
                account_id,booking_date,amount_cents,label,category,transaction_type,is_internal_transfer,
                destination_account_id,status,source_type,source_id,source_url,source_date,source_status,confidence,source_key,imported_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(source_key) DO UPDATE SET label=excluded.label,category=excluded.category,status=excluded.status''',
            (_account_id(conn, item['account']), item['date'], cents(item['amount']), item['label'], item['category'], item['type'], item['transfer'], destination_id, item['status'], 'notion', ROOT_SOURCE_ID, ROOT_SOURCE_URL, item['date'], 'confirmed', 1.0, item['key'], now),
        )
        stats['transactions'] += 1


def _merge_recurrences(conn, run_id, stats, now):
    for item in RECURRING:
        account_id = _account_id(conn, item['account'])
        existing = conn.execute(
            'SELECT * FROM recurring_transactions WHERE source_key=? OR (account_id=? AND lower(label)=lower(?)) ORDER BY source_key IS NOT NULL DESC LIMIT 1',
            (item['key'], account_id, item['label']),
        ).fetchone()
        if existing and existing['source_key'] not in (None, item['key']):
            if _record_conflict(conn, run_id, 'recurring', item['key'], 'Existing recurrence has different provenance', json.dumps(dict(existing), default=str), json.dumps(item)):
                stats['conflicts'] += 1
            stats['ignored'] += 1
            continue
        values = (cents(item['amount']), item['day'], item['category'], item['kind'], item['certainty'], 'notion', REFERENCE_SOURCE_ID, REFERENCE_SOURCE_URL, '2026-08-01', 'documented', 0.9, item['key'], now)
        if existing:
            conn.execute(
                '''UPDATE recurring_transactions SET amount_cents=?,day_of_month=?,category=?,kind=?,certainty=?,is_active=1,
                   source_type=?,source_id=?,source_url=?,source_date=?,source_status=?,confidence=?,source_key=?,imported_at=? WHERE id=?''',
                values + (existing['id'],),
            )
        else:
            conn.execute(
                '''INSERT INTO recurring_transactions(
                    account_id,label,amount_cents,day_of_month,category,kind,certainty,tolerance_cents,is_active,
                    source_type,source_id,source_url,source_date,source_status,confidence,source_key,imported_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (account_id, item['label'], cents(item['amount']), item['day'], item['category'], item['kind'], item['certainty'], 0, 1, 'notion', REFERENCE_SOURCE_ID, REFERENCE_SOURCE_URL, '2026-08-01', 'documented', 0.9, item['key'], now),
            )
        stats['recurrences'] += 1


def _merge_rules(conn, stats, now):
    for item in RULES:
        conn.execute(
            '''INSERT INTO financial_rules(
                rule_type,name,value_text,value_cents,start_date,end_date,status,comment,
                source_type,source_id,source_url,source_date,source_status,confidence,source_key,imported_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(source_key) DO UPDATE SET value_text=excluded.value_text,value_cents=excluded.value_cents,
                start_date=excluded.start_date,end_date=excluded.end_date,status=excluded.status,comment=excluded.comment''',
            (item['type'], item['name'], item.get('text'), item.get('cents'), item.get('start'), item.get('end'), item['status'], item['comment'], 'notion', REFERENCE_SOURCE_ID, REFERENCE_SOURCE_URL, item.get('start') or '2026-08-01', 'documented', 0.95, item['key'], now),
        )
        stats['rules'] += 1


def _merge_goals(conn, run_id, stats, now):
    for item in GOALS:
        existing = conn.execute(
            'SELECT * FROM financial_goals WHERE source_key=? OR lower(name)=lower(?) ORDER BY source_key IS NOT NULL DESC LIMIT 1',
            (item['key'], item['name']),
        ).fetchone()
        if existing and existing['source_key'] not in (None, item['key']):
            if _record_conflict(conn, run_id, 'goal', item['key'], 'Existing goal has different provenance', json.dumps(dict(existing), default=str), json.dumps(item)):
                stats['conflicts'] += 1
            stats['ignored'] += 1
            continue
        values = (item['name'], cents(item['target']), item['date'], item['priority'], item['active'], cents(item['current']), cents(item['monthly']), 'notion', item['source_id'], item['source_url'], '2026-07-20', 'documented', 1.0, item['key'], now)
        if existing:
            conn.execute(
                '''UPDATE financial_goals SET name=?,target_cents=?,target_date=?,priority=?,is_active=?,current_cents=?,monthly_contribution_cents=?,
                   source_type=?,source_id=?,source_url=?,source_date=?,source_status=?,confidence=?,source_key=?,imported_at=? WHERE id=?''',
                values + (existing['id'],),
            )
        else:
            conn.execute(
                '''INSERT INTO financial_goals(
                    name,target_cents,target_date,priority,is_active,current_cents,monthly_contribution_cents,
                    source_type,source_id,source_url,source_date,source_status,confidence,source_key,imported_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', values,
            )
        stats['goals'] += 1


def _merge_decisions(conn, stats, now):
    for item in DECISIONS:
        conn.execute(
            '''INSERT INTO financial_decisions(
                decision_date,title,details,status,source_type,source_id,source_url,source_date,source_status,confidence,source_key,imported_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(source_key) DO UPDATE SET title=excluded.title,details=excluded.details,status=excluded.status''',
            (item['date'], item['title'], item['details'], item['status'], 'notion', ROOT_SOURCE_ID, ROOT_SOURCE_URL, item['date'], 'documented', 1.0, item['key'], now),
        )
        stats['decisions'] += 1


def _merge_monthly_closing_balances(conn, now):
    lcl_id = _account_id(conn, 'account:lcl-current')
    for item in MONTHLY_HISTORY:
        source_key = f"history:{item['key']}:closing"
        conn.execute(
            '''INSERT INTO account_balance_history(
                account_id,balance_cents,balance_date,status,source_type,source_id,source_url,source_date,source_status,confidence,source_key,imported_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(source_key) DO NOTHING''',
            (lcl_id, cents(item['closing']), item['month']+'-28', 'historical', 'notion', item['source_id'], item['source_url'], item['month']+'-01', 'historical', 0.9, source_key, now),
        )


def preview():
    return {
        'source_revision': SOURCE_REVISION,
        'sources': [ROOT_SOURCE_URL, REFERENCE_SOURCE_URL, HISTORY_SOURCE_URL],
        'accounts': len(ACCOUNTS),
        'balance_history': len(BALANCE_HISTORY),
        'monthly_history': len(MONTHLY_HISTORY),
        'confirmed_transactions': len(CONFIRMED_TRANSACTIONS),
        'recurrences': len(RECURRING),
        'rules': len(RULES),
        'goals': len(GOALS),
        'decisions': len(DECISIONS),
        'planned_only_not_confirmed': ['LCL Vie 100 € mensuel', 'Assurance emprunteur 22,36 € mensuelle', 'Impôt septembre-novembre 113 €', 'Impôt décembre 116 €'],
        'obsolete_examples': ['LDDS 76,51 €', 'Boursobank 157,39 €', 'Livret A 50 €', 'Darty 3 150 €'],
        'policy': 'newer_flow_then_confirmed_latest_without_double_counting',
    }


def apply_import(mode='initial'):
    stats = {'accounts':0,'balances':0,'monthly_history':0,'transactions':0,'recurrences':0,'rules':0,'goals':0,'decisions':0,'conflicts':0,'ignored':0}
    now = datetime.now(timezone.utc).isoformat()
    with connection() as conn:
        _ensure_import_schema(conn)
        run_id = conn.execute('INSERT INTO notion_import_runs(mode,status,source_revision) VALUES(?,?,?)', (mode, 'running', SOURCE_REVISION)).lastrowid
        _merge_accounts(conn, run_id, stats, now)
        _merge_balance_history(conn, stats, now)
        _merge_monthly_history(conn, stats, now)
        _merge_transactions(conn, stats, now)
        _merge_recurrences(conn, run_id, stats, now)
        _merge_rules(conn, stats, now)
        _merge_goals(conn, run_id, stats, now)
        _merge_decisions(conn, stats, now)
        _merge_monthly_closing_balances(conn, now)
        conn.execute("INSERT INTO settings(key,value) VALUES('safety_reserve_cents','20000') ON CONFLICT(key) DO NOTHING")
        conn.execute("INSERT INTO settings(key,value) VALUES('notion_last_sync_at',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (now,))
        conn.execute("INSERT INTO settings(key,value) VALUES('notion_source_revision',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (SOURCE_REVISION,))
        conn.execute('UPDATE notion_import_runs SET status=?,stats_json=?,conflict_count=?,ignored_count=?,completed_at=CURRENT_TIMESTAMP WHERE id=?', ('completed', json.dumps(stats, ensure_ascii=False), stats['conflicts'], stats['ignored'], run_id))
    return {'run_id': run_id, 'source_revision': SOURCE_REVISION, 'stats': stats}


def status():
    with connection() as conn:
        _ensure_import_schema(conn)
        last = conn.execute('SELECT * FROM notion_import_runs ORDER BY id DESC LIMIT 1').fetchone()
        conflicts = conn.execute("SELECT COUNT(*) n FROM notion_import_conflicts WHERE resolution='needs_review'").fetchone()['n']
        settings = {r['key']: r['value'] for r in conn.execute("SELECT key,value FROM settings WHERE key IN ('notion_last_sync_at','notion_source_revision')").fetchall()}
    return {
        'connected': True,
        'connection_mode': 'migrated_snapshot',
        'last_sync_at': settings.get('notion_last_sync_at') or None,
        'source_revision': settings.get('notion_source_revision') or None,
        'last_run': dict(last) if last else None,
        'open_conflicts': conflicts,
    }


def bootstrap_if_needed():
    with connection() as conn:
        _ensure_import_schema(conn)
        value = conn.execute("SELECT value FROM settings WHERE key='notion_source_revision'").fetchone()
        if value and value['value'] == SOURCE_REVISION:
            return None
    return apply_import('bootstrap')
