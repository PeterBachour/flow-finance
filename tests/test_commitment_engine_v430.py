import sqlite3
from datetime import date

from app.commitment_engine import build_commitment_review
from app.safe_to_spend import calculate_safe_to_spend


def _conn():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.executescript('''
        CREATE TABLE accounts(id INTEGER PRIMARY KEY,current_balance_cents INTEGER,balance_as_of TEXT,is_active INTEGER,include_in_safe_to_spend INTEGER);
        CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT);
        CREATE TABLE planned_transactions(id INTEGER PRIMARY KEY,account_id INTEGER,due_date TEXT,amount_cents INTEGER,label TEXT,kind TEXT,certainty TEXT,status TEXT,source_type TEXT);
        CREATE TABLE recurring_transactions(id INTEGER PRIMARY KEY,account_id INTEGER,label TEXT,amount_cents INTEGER,day_of_month INTEGER,category TEXT,kind TEXT,certainty TEXT,tolerance_cents INTEGER,is_active INTEGER,source_type TEXT,source_id TEXT,source_date TEXT,source_status TEXT,confidence REAL,usual_day INTEGER,next_expected_date TEXT,last_seen_date TEXT,detection_status TEXT);
        CREATE TABLE financial_goals(id INTEGER PRIMARY KEY,is_active INTEGER,monthly_contribution_cents INTEGER);
        CREATE TABLE goal_allocations(id INTEGER PRIMARY KEY,goal_id INTEGER,account_id INTEGER,amount_cents INTEGER,allocated_on TEXT,note TEXT);
        CREATE TABLE cycle_reserves(id INTEGER PRIMARY KEY,reserve_key TEXT,cycle_month TEXT,label TEXT,amount_cents INTEGER,kind TEXT,status TEXT,source_type TEXT,source_status TEXT,reason TEXT);
        INSERT INTO settings VALUES('safety_reserve_cents','20000');
        INSERT INTO accounts VALUES(1,100000,'2026-09-10',1,1);
    ''')
    return conn


def test_probable_commitment_is_visible_but_not_protected():
    conn = _conn()
    conn.execute("INSERT INTO recurring_transactions VALUES(1,1,'STREAMING',-1599,15,'Services numériques','commitment','expected',0,1,'history',NULL,NULL,NULL,0.8,15,'2026-09-15','2026-08-15','pending')")
    review = build_commitment_review(conn, as_of=date(2026, 9, 10), horizon_end=date(2026, 9, 29))
    item = next(i for i in review['items'] if i['item_type'] == 'recurring')
    assert item['status'] == 'probable'
    assert item['protected_in_safe'] is False
    assert review['summary']['probable_cents'] == 1599


def test_planned_overlap_prevents_recurring_double_count():
    conn = _conn()
    conn.execute("INSERT INTO planned_transactions VALUES(1,1,'2026-09-15',-1599,'STREAMING','commitment','confirmed','planned','manual')")
    conn.execute("INSERT INTO recurring_transactions VALUES(1,1,'STREAMING',-1599,15,'Services numériques','commitment','expected',0,1,'manual',NULL,NULL,NULL,1.0,15,'2026-09-15','2026-08-15','accepted')")
    safe = calculate_safe_to_spend(conn, as_of=date(2026, 9, 10), horizon_days=19, stale_reference_date=date(2026, 9, 10))
    assert safe.planned_commitments_cents == 1599
    assert safe.recurring_commitments_cents == 0
    assert safe.calculated_safe_to_spend_cents == 78401

    review = build_commitment_review(conn, as_of=date(2026, 9, 10), horizon_end=date(2026, 9, 29))
    recurring = next(i for i in review['items'] if i['item_type'] == 'recurring')
    assert recurring['planned_overlap'] is not None
    assert recurring['protected_in_safe'] is False
    assert review['summary']['protected_confirmed_cents'] == 1599


def test_cycle_reserve_is_exposed_and_prevents_recurring_double_count():
    conn = _conn()
    conn.execute("INSERT INTO cycle_reserves VALUES(1,'reserve:apple:2026-09','2026-09','Apple septembre 2026',1398,'planned_commitment','active','manual_reconciled','confirmed','active monthly rule')")
    conn.execute("INSERT INTO recurring_transactions VALUES(1,1,'Apple septembre 2026',-1398,15,'Services numériques','commitment','expected',0,1,'manual',NULL,NULL,NULL,1.0,15,'2026-09-15','2026-08-15','accepted')")

    safe = calculate_safe_to_spend(conn, as_of=date(2026, 9, 10), horizon_days=19, stale_reference_date=date(2026, 9, 10))
    assert safe.planned_commitments_cents == 1398
    assert safe.recurring_commitments_cents == 0
    assert safe.calculated_safe_to_spend_cents == 78602

    review = build_commitment_review(conn, as_of=date(2026, 9, 10), horizon_end=date(2026, 9, 29))
    reserve = next(i for i in review['items'] if i['item_type'] == 'cycle_reserve')
    recurring = next(i for i in review['items'] if i['item_type'] == 'recurring')
    assert reserve['protected_in_safe'] is True
    assert recurring['cycle_overlap'] is not None
    assert recurring['protected_in_safe'] is False
    assert review['summary']['cycle_reserve_cents'] == 1398
    assert review['summary']['protected_confirmed_cents'] == 1398
