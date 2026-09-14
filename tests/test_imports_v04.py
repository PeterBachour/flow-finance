from app.imports import _lcl_labels, _lcl_rows, make_fingerprint, normalize_label, parse_csv_bytes


def test_normalize_removes_card_date_and_spaces():
    assert normalize_label('  CB   MONOPRIX  08/09/26 ') == 'CB MONOPRIX'


def test_fingerprint_is_stable_and_account_scoped():
    a = make_fingerprint(1, '2026-09-08', -1200, 'CB TEST 08/09/26')
    b = make_fingerprint(1, '2026-09-08', -1200, 'CB TEST')
    c = make_fingerprint(2, '2026-09-08', -1200, 'CB TEST')
    assert a == b
    assert a != c


def test_csv_supports_debit_credit_columns():
    rows = parse_csv_bytes('Date;Libelle;Debit;Credit\n08/09/2026;Restaurant;18,50;\n09/09/2026;Salaire;;3104,00\n'.encode())
    assert rows[0]['amount_cents'] == -1850
    assert rows[1]['amount_cents'] == 310400


def test_lcl_pairs_permanent_transfer_and_credit_column():
    text = '''
CB TEST 01/06/26
VIR.PERMANENT Compte Joint
VIR INST TEST
  Page 1 / 1
01.06 01.06.26 6,50
01.06 01.06.26 1 400,00 .
02.06 02.06.26 . 150,00
RELEVE DE COMPTE
DATE LIBELLE VALEUR DEBIT CREDIT
'''
    labels = _lcl_labels(text)
    rows = _lcl_rows(text, 2026)
    assert labels == ['CB TEST 01/06/26', 'VIR.PERMANENT Compte Joint', 'VIR INST TEST']
    assert [r['amount_cents'] for r in rows] == [-650, -140000, 15000]
