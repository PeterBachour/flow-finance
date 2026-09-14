import sqlite3

from app.onboarding_routes import readiness


def conn():
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    db.executescript('''
    CREATE TABLE accounts(id INTEGER PRIMARY KEY,name TEXT,kind TEXT,current_balance_cents INTEGER,balance_as_of TEXT,currency TEXT,is_active INTEGER DEFAULT 1);
    CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
    INSERT INTO settings(key,value) VALUES('safety_reserve_cents','0');
    ''')
    return db


def test_no_account_requires_setup():
    db = conn()
    result = readiness(db)
    assert result['ready'] is False
    assert 'Aucun compte liquide configuré' in result['blockers']


def test_dated_checking_account_is_ready_even_without_reserve():
    db = conn()
    db.execute("INSERT INTO accounts VALUES(1,'Courant','checking',10000,'2026-09-08','EUR',1)")
    result = readiness(db)
    assert result['ready'] is True
    assert result['warnings'] == ['Réserve minimale non définie']


def test_unknown_account_kind_is_reported():
    db = conn()
    db.execute("INSERT INTO accounts VALUES(1,'Courant','checking',10000,'2026-09-08','EUR',1)")
    db.execute("INSERT INTO accounts VALUES(2,'Mystère','crypto_wallet',5000,'2026-09-08','EUR',1)")
    result = readiness(db)
    assert result['ready'] is True
    assert result['unknown_account_kinds'][0]['kind'] == 'crypto_wallet'
