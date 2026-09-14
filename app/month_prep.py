import calendar
from datetime import date

from .financial_engine_v1 import financial_rule_summary
from .recurring_detection import detect_recurring_suggestions


def next_month_key(today: date) -> str:
    year = today.year + (1 if today.month == 12 else 0)
    month = 1 if today.month == 12 else today.month + 1
    return f'{year:04d}-{month:02d}'


def _month_parts(month_key: str) -> tuple[int, int]:
    try:
        year, month = map(int, month_key.split('-'))
        if not 1 <= month <= 12:
            raise ValueError
        return year, month
    except Exception as exc:
        raise ValueError('Mois invalide, format attendu YYYY-MM') from exc


def _due_date(month_key: str, day_of_month: int) -> str:
    year, month = _month_parts(month_key)
    day = min(day_of_month, calendar.monthrange(year, month)[1])
    return date(year, month, day).isoformat()


def build_month_preparation(conn, month_key: str, today: date | None = None) -> dict:
    today = today or date.today()
    _month_parts(month_key)
    recurring = conn.execute('SELECT r.*,a.name account_name FROM recurring_transactions r JOIN accounts a ON a.id=r.account_id WHERE r.is_active=1 ORDER BY r.day_of_month,r.id').fetchall()
    expected = []
    for row in recurring:
        item = dict(row)
        item['due_date'] = _due_date(month_key, row['day_of_month'])
        item['source'] = 'recurring'
        expected.append(item)

    planned = [dict(row) for row in conn.execute("SELECT p.*,a.name account_name FROM planned_transactions p JOIN accounts a ON a.id=p.account_id WHERE p.status='planned' AND substr(p.due_date,1,7)=? ORDER BY p.due_date,p.id", (month_key,)).fetchall()]
    rule_summary = financial_rule_summary(conn, month_key)
    suggestions = detect_recurring_suggestions(conn)
    high_confidence = [s for s in suggestions if s.get('confidence', 0) >= 0.75]
    salaries = [e for e in expected if e['amount_cents'] > 0 and (e.get('category') == 'Salaire' or e.get('kind') in {'salary', 'income'})]
    recurring_outflows = sum(-e['amount_cents'] for e in expected if e['amount_cents'] < 0)
    recurring_income = sum(e['amount_cents'] for e in expected if e['amount_cents'] > 0)
    reference_income = rule_summary['income_reference_cents']
    effective_income = recurring_income or reference_income
    confirmed_outflows = sum(-p['amount_cents'] for p in planned if p['amount_cents'] < 0 and p['certainty'] == 'confirmed')
    undated_rule_outflows = rule_summary['rule_reserve_cents']
    budget = conn.execute('SELECT id,status FROM budgets WHERE month=?', (month_key,)).fetchone()
    budget_lines = 0 if not budget else conn.execute('SELECT COUNT(*) n FROM budget_lines WHERE budget_id=?', (budget['id'],)).fetchone()['n']

    blockers = []
    warnings = []
    if not salaries and not reference_income:
        blockers.append('Aucun revenu structurant identifié')
    elif not salaries and reference_income:
        warnings.append('Salaire connu mais date exacte non confirmée : aucune date inventée')
    if not any(e['amount_cents'] < 0 for e in expected) and not rule_summary['obligations']:
        blockers.append('Aucune charge récurrente ou règle financière active')
    if high_confidence:
        warnings.append(f"{len(high_confidence)} récurrence(s) fiable(s) restent à valider")
    total_known_outflows = recurring_outflows + undated_rule_outflows + confirmed_outflows
    if effective_income and total_known_outflows > effective_income:
        warnings.append('Les sorties connues dépassent le revenu mensuel de référence')
    if not budget or budget_lines == 0:
        warnings.append('Aucun budget détaillé préparé pour ce mois')

    if blockers:
        status = 'attention'; label = 'À préparer'
    elif warnings:
        status = 'review'; label = 'À vérifier'
    else:
        status = 'secured'; label = 'Mois sécurisé'

    structural_income = None
    if salaries:
        salary = min(salaries, key=lambda e: e['due_date'])
        structural_income = {'date': salary['due_date'], 'amount_cents': salary['amount_cents'], 'label': salary['label'], 'source': 'recurring'}
    elif reference_income:
        structural_income = {'date': None, 'amount_cents': reference_income, 'label': 'Salaire net de référence', 'source': 'financial_rule'}

    return {
        'month': month_key,
        'status': status,
        'status_label': label,
        'blockers': blockers,
        'warnings': warnings,
        'structural_income': structural_income,
        'recurring_income_cents': recurring_income,
        'income_reference_cents': reference_income,
        'effective_income_cents': effective_income,
        'recurring_outflows_cents': recurring_outflows,
        'rule_reserved_outflows_cents': undated_rule_outflows,
        'confirmed_outflows_cents': confirmed_outflows,
        'known_outflows_cents': total_known_outflows,
        'variable_budget_cents': rule_summary['variable_budget_cents'],
        'net_known_cents': effective_income - total_known_outflows,
        'net_recurring_cents': effective_income - recurring_outflows - undated_rule_outflows,
        'expected_events': expected,
        'planned_events': planned,
        'undated_financial_rules': rule_summary['obligations'],
        'pending_recurring_suggestions': high_confidence,
        'budget': {'exists': bool(budget), 'status': budget['status'] if budget else 'draft', 'line_count': budget_lines},
        'generated_at': today.isoformat(),
    }
