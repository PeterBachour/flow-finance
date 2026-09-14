from datetime import date
from pathlib import Path
import sqlite3

from app.v46_routes import _movement_filters, _period_start, _summary


def _conn():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.executescript('''
        CREATE TABLE accounts(id INTEGER PRIMARY KEY,name TEXT,kind TEXT);
        CREATE TABLE transactions(
            id INTEGER PRIMARY KEY, account_id INTEGER, booking_date TEXT, amount_cents INTEGER,
            label TEXT, user_label TEXT, category TEXT, status TEXT,
            is_internal_transfer INTEGER DEFAULT 0, exclude_from_analytics INTEGER DEFAULT 0,
            is_exceptional INTEGER DEFAULT 0
        );
        INSERT INTO accounts VALUES(1,'LCL','checking');
        INSERT INTO transactions VALUES
          (1,1,'2026-08-01',-5000,'Restaurant',NULL,'Restaurants','confirmed',0,0,0),
          (2,1,'2026-08-02',-3000,'Courses',NULL,'Alimentation','confirmed',0,0,0),
          (3,1,'2026-08-03',10000,'Remboursement',NULL,'Remboursement','confirmed',0,0,0),
          (4,1,'2026-08-04',-2000,'Virement',NULL,'Transfert interne','confirmed',1,0,0),
          (5,1,'2026-08-05',-9000,'Exceptionnel',NULL,'Loisirs','confirmed',0,0,1);
    ''')
    return conn


def test_period_presets_are_deterministic():
    as_of = date(2026, 9, 11)
    assert _period_start(as_of, '30d') == date(2026, 8, 13)
    assert _period_start(as_of, '12m') == date(2025, 9, 11)


def test_filtered_summary_keeps_transfers_out_of_consumption():
    conn = _conn()
    where, params = _movement_filters(
        start=date(2026, 8, 1), end=date(2026, 8, 31), q='', category=None,
        account_id=None, min_cents=None, max_cents=None, flow_type='all'
    )
    result = _summary(conn, where, params)
    assert result['expenses_cents'] == 17000
    assert result['income_cents'] == 10000
    assert result['transfers_cents'] == 2000
    assert result['expense_count'] == 3
    assert result['average_expense_cents'] == 5667


def test_expense_filter_excludes_internal_transfers():
    conn = _conn()
    where, params = _movement_filters(
        start=date(2026, 8, 1), end=date(2026, 8, 31), q='', category=None,
        account_id=None, min_cents=None, max_cents=None, flow_type='expense'
    )
    rows = conn.execute(
        f'SELECT t.id FROM transactions t JOIN accounts a ON a.id=t.account_id WHERE {where} ORDER BY t.id', params
    ).fetchall()
    assert [r['id'] for r in rows] == [1, 2, 5]


def test_pre_v5_ui_exposes_historical_filters_and_wealth_balance_update():
    text = Path('app/static/movement-wealth-ui.js').read_text(encoding='utf-8')
    assert "['30d','3m','6m','12m']" in text
    assert 'Filtres avancés' in text
    assert 'Moy. dépense' in text
    assert 'Top catégorie' in text
    assert 'data-balance' in text
    assert '/api/accounts/${id}/balance' in text


def test_settings_separates_financial_decisions_from_quality_reviews():
    text = Path('app/static/pre-v5-settings-ui.js').read_text(encoding='utf-8')
    assert '/api/v4.7/decision-priorities' in text
    assert 'Décisions financières' in text
    assert 'revue(s) de données' in text
