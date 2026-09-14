import sqlite3
from datetime import date

from app.safe_to_spend_explanation import build_safe_to_spend_explanation
from app.v2_migrations import ensure_v2_schema


def database(balance_as_of='2026-09-14'):
    conn=sqlite3.connect(':memory:');conn.row_factory=sqlite3.Row
    conn.executescript("""
    CREATE TABLE accounts(id INTEGER PRIMARY KEY,name TEXT,kind TEXT,current_balance_cents INTEGER,is_active INTEGER DEFAULT 1,balance_as_of TEXT,include_in_safe_to_spend INTEGER DEFAULT 1);
    CREATE TABLE transactions(id INTEGER PRIMARY KEY,account_id INTEGER,booking_date TEXT,amount_cents INTEGER,label TEXT,category TEXT,transaction_type TEXT DEFAULT 'expense',is_internal_transfer INTEGER DEFAULT 0);
    CREATE TABLE recurring_transactions(id INTEGER PRIMARY KEY,account_id INTEGER,label TEXT,amount_cents INTEGER,day_of_month INTEGER,category TEXT,kind TEXT,certainty TEXT,is_active INTEGER DEFAULT 1);
    CREATE TABLE financial_goals(id INTEGER PRIMARY KEY,name TEXT,target_cents INTEGER,is_active INTEGER DEFAULT 1);
    CREATE TABLE planned_transactions(id INTEGER PRIMARY KEY,account_id INTEGER,due_date TEXT,amount_cents INTEGER,label TEXT,kind TEXT DEFAULT 'commitment',certainty TEXT DEFAULT 'confirmed',status TEXT DEFAULT 'planned');
    CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
    CREATE TABLE goal_allocations(id INTEGER PRIMARY KEY,goal_id INTEGER,account_id INTEGER,amount_cents INTEGER,allocated_on TEXT,note TEXT);
    CREATE TABLE financial_rules(id INTEGER PRIMARY KEY,rule_type TEXT,name TEXT,value_text TEXT,value_cents INTEGER,start_date TEXT,end_date TEXT,status TEXT DEFAULT 'active',source_key TEXT);
    """)
    ensure_v2_schema(conn)
    conn.executescript("""
    ALTER TABLE recurring_transactions ADD COLUMN usual_day INTEGER;
    ALTER TABLE recurring_transactions ADD COLUMN next_expected_date TEXT;
    ALTER TABLE recurring_transactions ADD COLUMN last_seen_date TEXT;
    ALTER TABLE recurring_transactions ADD COLUMN source_type TEXT;
    ALTER TABLE recurring_transactions ADD COLUMN detection_status TEXT NOT NULL DEFAULT 'accepted';
    ALTER TABLE recurring_transactions ADD COLUMN tolerance_cents INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE financial_goals ADD COLUMN monthly_contribution_cents INTEGER NOT NULL DEFAULT 0;
    """)
    conn.execute("INSERT INTO settings VALUES('safety_reserve_cents','10000')")
    conn.execute("INSERT INTO accounts VALUES(1,'Courant','checking',100000,1,?,1)",(balance_as_of,))
    return conn


def test_v64_formula_reconciles_and_exposes_sources_without_writes():
    conn=database()
    conn.execute("INSERT INTO planned_transactions VALUES(1,1,'2026-09-20',-20000,'Loyer','commitment','confirmed','planned')")
    before=conn.total_changes
    result=build_safe_to_spend_explanation(conn,as_of=date(2026,9,14),horizon_days=10,stale_reference_date=date(2026,9,14))
    assert result['schema_version']=='6.4'
    assert result['formula']['reconciled'] is True
    assert result['formula']['difference_cents']==0
    assert result['formula']['expected_cents']==70000
    assert result['formula']['lines'][0]['sources'][0]['entity']=='accounts'
    assert result['formula']['lines'][1]['sources'][0]['entity_id']==1
    assert result['controls']['read_only'] is True
    assert result['controls']['ledger_unchanged'] is True
    assert conn.total_changes==before


def test_v64_stale_balance_is_explicitly_unavailable():
    conn=database('2026-08-01')
    result=build_safe_to_spend_explanation(conn,as_of=date(2026,9,14),horizon_days=10,stale_reference_date=date(2026,9,14))
    assert result['availability']['available'] is False
    assert result['safe_to_spend']['total_cents'] is None
    assert result['data_actions'][0]['required'] is True


def test_v64_ui_uses_explanation_contract():
    from pathlib import Path
    static=Path(__file__).resolve().parents[1]/'app'/'static'
    script=(static/'v64-explanation-ui.js').read_text(encoding='utf-8')
    assert "fetch('/api/v6/safe-to-spend/explanation'" in script
    assert 'Comprendre ce montant' in script
    assert 'formula.difference_cents' in script
