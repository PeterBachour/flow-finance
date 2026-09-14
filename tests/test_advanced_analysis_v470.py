import re
import sqlite3
from datetime import date
from pathlib import Path

from app.v47_routes import build_advanced_analysis


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'app' / 'static'


def _conn():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.executescript('''
    CREATE TABLE recurring_transactions(
      id INTEGER PRIMARY KEY,
      label TEXT,
      amount_cents INTEGER,
      detection_status TEXT
    );
    CREATE TABLE transactions(
      id INTEGER PRIMARY KEY,
      booking_date TEXT NOT NULL,
      amount_cents INTEGER NOT NULL,
      label TEXT NOT NULL,
      category TEXT,
      transaction_type TEXT,
      is_internal_transfer INTEGER DEFAULT 0,
      status TEXT DEFAULT 'confirmed'
    );
    ''')
    return conn


def test_analysis_uses_closed_months_and_canonical_variable_classifier():
    conn = _conn()
    rows = [
        ('2026-03-10', -10000, 'RESTO A', 'Restaurants', 'expense', 0),
        ('2026-04-10', -10000, 'RESTO B', 'Restaurants', 'expense', 0),
        ('2026-05-10', -10000, 'RESTO C', 'Restaurants', 'expense', 0),
        ('2026-06-10', -10000, 'RESTO D', 'Restaurants', 'expense', 0),
        ('2026-07-10', -10000, 'RESTO E', 'Restaurants', 'expense', 0),
        ('2026-08-10', -20000, 'RESTO F', 'Restaurants', 'expense', 0),
        ('2026-08-12', -9999, 'SFR', 'Télécom', 'expense', 0),
        ('2026-08-15', -50000, 'VIREMENT', 'Transfert interne', 'transfer', 1),
        ('2026-09-05', -90000, 'RESTO COURANT', 'Restaurants', 'expense', 0),
    ]
    conn.executemany(
        'INSERT INTO transactions(booking_date,amount_cents,label,category,transaction_type,is_internal_transfer) VALUES(?,?,?,?,?,?)',
        rows,
    )
    data = build_advanced_analysis(conn, as_of=date(2026, 9, 11))
    assert data['latest_closed_month'] == '2026-08'
    assert data['latest_closed_variable_cents'] == 20000
    assert all(row['month'] != '2026-09' for row in data['monthly_variable'])
    assert data['category_trends'][0]['category'] == 'Restaurants'


def test_analysis_explains_anomaly_threshold_and_rejects_seasonality_claim():
    js = (STATIC / 'advanced-analysis-ui.js').read_text(encoding='utf-8')
    route = (ROOT / 'app' / 'v47_routes.py').read_text(encoding='utf-8')
    assert '/api/v4.7/analysis' in js
    assert 'au moins 3 mois observés' in route
    assert '+50 %' in route
    assert '+30 €' in route
    assert 'Aucune saisonnalité' in route


def test_v470_assets_and_router_are_wired():
    html = (STATIC / 'index.html').read_text(encoding='utf-8')
    sw = (STATIC / 'sw.js').read_text(encoding='utf-8')
    workspace = (ROOT / 'app' / 'workspace_routes.py').read_text(encoding='utf-8')
    version = (ROOT / 'app' / 'version.py').read_text(encoding='utf-8')

    assert '/static/advanced-analysis.css?v=' in html
    assert '/static/advanced-analysis-ui.js?v=' in html
    assert 'v47_router' in workspace

    version_match = re.search(r"VERSION\s*=\s*'([^']+)'", version)
    sw_match = re.search(r"const VERSION='([^']+)'", sw)
    assert version_match and sw_match
    assert sw_match.group(1) == version_match.group(1)


def test_settings_use_prioritized_decisions_and_explicit_diagnostic():
    js = (STATIC / 'pre-v5-settings-ui.js').read_text(encoding='utf-8')
    route = (ROOT / 'app' / 'v47_routes.py').read_text(encoding='utf-8')
    assert '/api/v4.7/decision-priorities' in js
    assert '/api/v4.7/system-diagnostic' in js
    assert 'Non injecté' in js
    assert 'quality_review_count' in route
    assert 'commit_status' in route
