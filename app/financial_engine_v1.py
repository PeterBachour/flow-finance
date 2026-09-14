from datetime import date, timedelta

RESERVING_RULE_TYPES = {'monthly_expense', 'monthly_saving'}


def _active_for_month(row, month_key):
    start = row['start_date'] or '0000-01-01'
    end = row['end_date'] or '9999-12-31'
    return start <= f'{month_key}-31' and end >= f'{month_key}-01' and row['status'] == 'active'


def _marker(row):
    text = f"{row['source_key'] or ''} {row['name'] or ''}".lower()
    for token, value in (('ldds','LDDS'),('livret','LIVRET'),('lcl-vie','LCL VIE'),('insurance','ASSURANCE'),('assurance','ASSURANCE'),('phone','TEL'),('téléphone','TEL'),('apple','APPLE'),('velib','VELIB'),('vélib','VELIB'),('tax','IMPOT'),('impôt','IMPOT')):
        if token in text:
            return value
    return None


def _covered_by_boursobank(conn, marker):
    if marker not in {'LCL VIE', 'ASSURANCE'}:
        return False
    row = conn.execute("SELECT current_balance_cents FROM accounts WHERE source_key='account:boursobank' AND is_active=1 LIMIT 1").fetchone()
    return bool(row and row['current_balance_cents'] >= 12236)


def _prefunded(conn, marker, month_key):
    start = date.fromisoformat(f'{month_key}-01')
    window_start = (start - timedelta(days=7)).isoformat()
    window_end = (start - timedelta(days=1)).isoformat()
    return bool(conn.execute(
        "SELECT 1 FROM transactions WHERE booking_date BETWEEN ? AND ? AND upper(label) LIKE ? AND upper(label) LIKE '%PR_PARATION%' AND COALESCE(status,'confirmed')='confirmed' LIMIT 1",
        (window_start, window_end, f'%{marker}%'),
    ).fetchone())


def _satisfied(conn, row, month_key):
    marker = _marker(row)
    if not marker:
        return False
    if _covered_by_boursobank(conn, marker):
        return True
    if conn.execute("SELECT 1 FROM transactions WHERE substr(booking_date,1,7)=? AND upper(label) LIKE ? AND COALESCE(status,'confirmed')='confirmed' LIMIT 1", (month_key, f'%{marker}%')).fetchone():
        return True
    if _prefunded(conn, marker, month_key):
        return True
    return bool(conn.execute("SELECT 1 FROM planned_transactions WHERE substr(due_date,1,7)=? AND upper(label) LIKE ? AND status='planned' AND certainty='confirmed' LIMIT 1", (month_key, f'%{marker}%')).fetchone())


def financial_rule_summary(conn, month_key):
    active = [row for row in conn.execute("SELECT * FROM financial_rules WHERE status='active' ORDER BY id").fetchall() if _active_for_month(row, month_key)]
    income = reserve = variable = minimum_reserve = 0
    obligations = []
    informational = []
    for row in active:
        rule = dict(row)
        rule['satisfied'] = _satisfied(conn, row, month_key)
        amount = int(row['value_cents'] or 0)
        if row['rule_type'] == 'income_reference':
            income = max(income, amount)
        elif row['rule_type'] == 'minimum_reserve':
            minimum_reserve = max(minimum_reserve, amount)
            informational.append(rule)
        elif row['rule_type'] == 'spending_budget':
            variable += max(0, amount)
            informational.append(rule)
        elif row['rule_type'] in RESERVING_RULE_TYPES:
            if not rule['satisfied']:
                reserve += max(0, amount)
            obligations.append(rule)
        else:
            informational.append(rule)
    return {'month': month_key, 'income_reference_cents': income, 'minimum_reserve_cents': minimum_reserve, 'rule_reserve_cents': reserve, 'variable_budget_cents': variable, 'obligations': obligations, 'informational_rules': informational}


def safe_account_balance_cents(conn):
    return conn.execute('SELECT COALESCE(SUM(current_balance_cents),0) total FROM accounts WHERE is_active=1 AND include_in_safe_to_spend=1').fetchone()['total']


def data_freshness(conn, today):
    rows = conn.execute('SELECT id,name,source_key,include_in_safe_to_spend,balance_as_of,current_balance_cents,source_status FROM accounts WHERE is_active=1 ORDER BY id').fetchall()
    result = []
    for row in rows:
        age_days = None
        if row['balance_as_of']:
            try:
                age_days = (today - date.fromisoformat(row['balance_as_of'])).days
            except ValueError:
                pass
        result.append({**dict(row), 'age_days': age_days})
    return {'accounts': result, 'oldest_age_days': max((r['age_days'] for r in result if r['age_days'] is not None), default=None)}
