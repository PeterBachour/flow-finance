from __future__ import annotations

from datetime import date

from .data_reconciliation import reconcile_account_balances
from .financial_engine_v2 import data_quality as legacy_data_quality


ANALYTIC_EXCLUDED_TYPES = {'refund', 'reimbursement', 'transfer'}


def _table_exists(conn, name: str) -> bool:
    return bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (name,),
    ).fetchone())


def _columns(conn, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f'PRAGMA table_info({table})').fetchall()}


def _duplicate_controls(conn) -> dict:
    exact = conn.execute('''
        SELECT account_id,booking_date,amount_cents,upper(trim(label)) normalized_label,COUNT(*) n
        FROM transactions
        GROUP BY account_id,booking_date,amount_cents,upper(trim(label))
        HAVING COUNT(*)>1
        ORDER BY n DESC,booking_date DESC
        LIMIT 50
    ''').fetchall()
    source_key_duplicates = []
    cols = _columns(conn, 'transactions')
    missing_source_key = 0
    if 'source_key' in cols:
        source_key_duplicates = conn.execute('''
            SELECT source_key,COUNT(*) n
            FROM transactions
            WHERE source_key IS NOT NULL AND trim(source_key)<>''
            GROUP BY source_key
            HAVING COUNT(*)>1
            ORDER BY n DESC,source_key
            LIMIT 50
        ''').fetchall()
        if 'source_type' in cols:
            missing_source_key = int(conn.execute('''
                SELECT COUNT(*) n
                FROM transactions
                WHERE COALESCE(source_type,'') NOT IN ('','manual')
                  AND (source_key IS NULL OR trim(source_key)='')
            ''').fetchone()['n'])
    return {
        'exact_duplicate_groups': len(exact),
        'source_key_duplicate_groups': len(source_key_duplicates),
        'imported_rows_missing_source_key': missing_source_key,
        'exact_duplicates': [dict(row) for row in exact],
        'source_key_duplicates': [dict(row) for row in source_key_duplicates],
    }


def _category_controls(conn) -> dict:
    unknown = conn.execute('''
        SELECT COALESCE(t.category,'') category,COUNT(*) n
        FROM transactions t
        LEFT JOIN categories c ON c.name=t.category AND c.is_active=1
        WHERE COALESCE(t.status,'confirmed')='confirmed'
          AND COALESCE(t.is_internal_transfer,0)=0
          AND COALESCE(t.exclude_from_analytics,0)=0
          AND COALESCE(t.transaction_type,'expense') NOT IN ('refund','reimbursement','transfer')
          AND COALESCE(t.category,'')<>''
          AND c.id IS NULL
        GROUP BY t.category
        ORDER BY n DESC,t.category
    ''').fetchall()
    uncategorized = int(conn.execute('''
        SELECT COUNT(*) n
        FROM transactions t
        WHERE COALESCE(t.status,'confirmed')='confirmed'
          AND COALESCE(t.is_internal_transfer,0)=0
          AND COALESCE(t.exclude_from_analytics,0)=0
          AND COALESCE(t.transaction_type,'expense') NOT IN ('refund','reimbursement','transfer')
          AND (t.category IS NULL OR trim(t.category)='')
    ''').fetchone()['n'])
    return {
        'uncategorized_rows': uncategorized,
        'unknown_category_rows': sum(int(row['n']) for row in unknown),
        'unknown_categories': [dict(row) for row in unknown],
    }


def _period_controls(conn) -> dict:
    if not _table_exists(conn, 'imports'):
        return {'available': False, 'incomplete_periods': [], 'count': 0}
    cols = _columns(conn, 'imports')
    period_col = 'period_end' if 'period_end' in cols else ('period' if 'period' in cols else None)
    if not period_col:
        return {'available': False, 'incomplete_periods': [], 'count': 0}
    status_expr = "COALESCE(status,'')" if 'status' in cols else "'completed'"
    quality_expr = "COALESCE(quality_status,'')" if 'quality_status' in cols else "'verified'"
    rows = conn.execute(f'''
        SELECT substr({period_col},1,7) period,COUNT(*) source_count,
               SUM(CASE WHEN {status_expr}<>'completed' OR {quality_expr}<>'verified' THEN 1 ELSE 0 END) incomplete_sources
        FROM imports
        WHERE {period_col} IS NOT NULL AND trim({period_col})<>''
        GROUP BY substr({period_col},1,7)
        HAVING SUM(CASE WHEN {status_expr}<>'completed' OR {quality_expr}<>'verified' THEN 1 ELSE 0 END)>0
        ORDER BY period DESC
    ''').fetchall()
    return {'available': True, 'incomplete_periods': [dict(row) for row in rows], 'count': len(rows)}


def build_data_quality_report(conn, today: date | None = None) -> dict:
    today = today or date.today()
    legacy = legacy_data_quality(conn, today)
    reconciliation = reconcile_account_balances(conn)
    duplicates = _duplicate_controls(conn)
    categories = _category_controls(conn)
    periods = _period_controls(conn)

    issues = list(legacy.get('issues') or [])
    if reconciliation['mismatch_count']:
        issues.append({
            'type': 'balance_reconciliation_mismatch', 'severity': 'critical',
            'count': reconciliation['mismatch_count'], 'title': 'Écart solde bancaire / ledger',
        })
    if duplicates['exact_duplicate_groups'] or duplicates['source_key_duplicate_groups']:
        issues.append({
            'type': 'duplicates', 'severity': 'warning',
            'count': duplicates['exact_duplicate_groups'] + duplicates['source_key_duplicate_groups'],
            'title': 'Doublons à contrôler',
        })
    if duplicates['imported_rows_missing_source_key']:
        issues.append({
            'type': 'missing_source_key', 'severity': 'warning',
            'count': duplicates['imported_rows_missing_source_key'], 'title': 'Imports sans source_key',
        })
    if categories['unknown_category_rows']:
        issues.append({
            'type': 'unknown_categories', 'severity': 'warning',
            'count': categories['unknown_category_rows'], 'title': 'Catégories inconnues',
        })
    if periods['count']:
        issues.append({
            'type': 'incomplete_periods', 'severity': 'warning',
            'count': periods['count'], 'title': 'Périodes importées incomplètes',
        })

    weighted = sum({'critical': 25, 'warning': 10, 'info': 4}.get(item.get('severity'), 5) for item in issues)
    score = max(0, 100 - weighted)
    return {
        **legacy,
        'score': score,
        'status': 'good' if score >= 85 else ('watch' if score >= 65 else 'poor'),
        'issues': issues,
        'reconciliation': reconciliation,
        'controls': {
            'duplicates': duplicates,
            'categories': categories,
            'periods': periods,
        },
        'read_only': True,
    }
