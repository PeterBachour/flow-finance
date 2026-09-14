from app.lcl_parser_v2 import _parse_balance_line, _parse_transaction_line


def test_credit_with_placeholder_dot_is_kept():
    line = '  22.06     CB GP FOOD AND BEV 21/06/26                                                                   22.06.26                                 .                  6,00'
    parsed = _parse_transaction_line(line, credit_col=151)
    assert parsed is not None
    assert parsed['amount_cents'] == 600
    assert parsed['label'] == 'CB GP FOOD AND BEV 21/06/26'


def test_debit_with_trailing_placeholder_dot_is_kept():
    line = '  10.06     PRET IMMOBILIER ECH 10/06/26                                                                  10.06.26                       207,20                             .'
    parsed = _parse_transaction_line(line, credit_col=151)
    assert parsed is not None
    assert parsed['amount_cents'] == -20720


def _balance_line(label: str, amount: str, amount_col: int) -> str:
    prefix = f' 31.07  {label}'
    if len(prefix) >= amount_col:
        raise AssertionError('fixture label overlaps amount column')
    return prefix + (' ' * (amount_col - len(prefix))) + amount


def test_debit_closing_balance_is_negative():
    debit_col = 120
    credit_col = 151
    line = _balance_line('SOLDE EN EUROS', '0,45', debit_col)
    parsed = _parse_balance_line(line, debit_col=debit_col, credit_col=credit_col)
    assert parsed == ('SOLDE EN EUROS', -45)


def test_credit_opening_balance_is_positive():
    debit_col = 120
    credit_col = 151
    line = _balance_line('ANCIEN SOLDE', '2 428,52', credit_col)
    parsed = _parse_balance_line(line, debit_col=debit_col, credit_col=credit_col)
    assert parsed == ('ANCIEN SOLDE', 242852)
