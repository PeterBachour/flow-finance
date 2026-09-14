import sqlite3

from app.imports import classify_row


def conn():
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE categorization_rules (pattern TEXT, category TEXT, transaction_type TEXT, priority INTEGER, is_active INTEGER)')
    return db


def test_own_name_transfers_are_internal():
    db = conn()
    assert classify_row(db, 'VIR SEPA M PETER BACHOUR', -50000) == ('Transfert interne', 'transfer', 1, True)
    assert classify_row(db, 'VIREMENT M PETER BACHOUR', 10000) == ('Transfert interne', 'transfer', 1, True)


def test_kardham_salary_and_reimbursement_are_distinct():
    db = conn()
    assert classify_row(db, 'VIREMENT KARDHAM DIGITAL', 295661) == ('Salaire', 'income', 0, True)
    assert classify_row(db, 'VIREMENT SAS KARDHAM DIGITAL', 10690) == ('Frais professionnel remboursé', 'reimbursement', 0, True)


def test_chatgpt_subscription_is_professional_reimbursed_expense():
    db = conn()
    assert classify_row(db, 'CB APPLE.COM/BILL 28/06/26', -2299) == ('Frais professionnel remboursé', 'expense', 0, True)


def test_card_credit_is_refund_but_stays_for_review():
    db = conn()
    assert classify_row(db, 'CB Uniqlo Wagram 21/05/26', 2490) == (None, 'refund', 0, False)


def test_third_party_transfer_stays_unclassified():
    db = conn()
    assert classify_row(db, 'VIR INST BENJAMIN OLIVAR', 1300) == (None, 'income', 0, False)


def test_category_rule_preserves_positive_card_credit_as_refund():
    db = conn()
    db.execute(
        "INSERT INTO categorization_rules VALUES(?,?,?,?,?)",
        ('CB SNCF-VOYAGEURS', 'Transport', None, 50, 1),
    )
    assert classify_row(db, 'CB SNCF-VOYAGEURS', 5275) == ('Transport', 'refund', 0, True)
