from __future__ import annotations

import io
import re
from datetime import date, datetime
from decimal import Decimal

from pypdf import PdfReader

PERIOD_RE = re.compile(r'\bdu\s+(\d{2}\.\d{2}\.\d{4})\s+au\s+(\d{2}\.\d{2}\.\d{4})', re.IGNORECASE)
TRANSACTION_HEAD_RE = re.compile(
    r'^\s*(\d{2}\.\d{2})\s{2,}(.+?)\s{2,}(\d{2}\.\d{2}\.\d{2})\s{2,}(.*)$'
)
MONEY_RE = re.compile(r'\d[\d ]*,\d{2}')
BALANCE_LABELS = ('ANCIEN SOLDE', 'SOLDE EN EUROS')


def _money(value: str) -> int:
    cleaned = value.replace('\u00a0', ' ').replace(' ', '').replace(',', '.')
    return int(Decimal(cleaned) * 100)


def _period(layout_text: str) -> tuple[date, date] | None:
    match = PERIOD_RE.search(layout_text)
    if not match:
        return None
    return tuple(datetime.strptime(value, '%d.%m.%Y').date() for value in match.groups())


def _booking_date(booking_short: str, value_date: str) -> date:
    value = datetime.strptime(value_date, '%d.%m.%y').date()
    day, month = map(int, booking_short.split('.'))
    year = value.year
    if month == 12 and value.month == 1:
        year -= 1
    elif month == 1 and value.month == 12:
        year += 1
    return date(year, month, day)


def _table_columns(lines: list[str]) -> tuple[int, int] | None:
    for line in lines:
        upper = line.upper()
        if all(token in upper for token in ('DATE', 'LIBELLE', 'VALEUR', 'DEBIT', 'CREDIT')):
            return upper.index('DEBIT'), upper.index('CREDIT')
    return None


def _signed_amount(amount_cents: int, amount_start: int, credit_col: int) -> int:
    return amount_cents if amount_start >= credit_col - 4 else -amount_cents


def _parse_transaction_line(line: str, credit_col: int) -> dict | None:
    match = TRANSACTION_HEAD_RE.match(line)
    if not match:
        return None
    booking_short, label_raw, value_date, tail = match.groups()
    money_matches = list(MONEY_RE.finditer(tail))
    if not money_matches:
        return None

    amount_match = money_matches[-1]
    amount_raw = amount_match.group()
    amount_start = match.start(4) + amount_match.start()
    amount_cents = _signed_amount(_money(amount_raw), amount_start, credit_col)
    label = ' '.join(label_raw.split()).strip()
    if not label:
        return None

    return {
        'booking_short': booking_short,
        'value_date': value_date,
        'label': label,
        'amount_cents': amount_cents,
        'amount_start': amount_start,
    }


def _parse_balance_line(line: str, debit_col: int, credit_col: int) -> tuple[str, int] | None:
    upper = line.upper()
    label = next((candidate for candidate in BALANCE_LABELS if candidate in upper), None)
    if not label:
        return None
    matches = list(MONEY_RE.finditer(line))
    if not matches:
        return None
    amount_match = matches[-1]
    amount_start = amount_match.start()
    amount = _money(amount_match.group())

    # LCL right-aligns balance values inside the DEBIT/CREDIT columns. The start
    # of the CREDIT header is the stable boundary between those columns: a
    # balance amount starting before it belongs to DEBIT, while one starting at
    # or after it belongs to CREDIT. Comparing distances to header starts is
    # incorrect for short right-aligned values such as 0,45 EUR.
    signed = amount if amount_start >= credit_col else -amount
    return label, signed


def parse_lcl_pdf_layout(data: bytes) -> tuple[list[dict], dict]:
    reader = PdfReader(io.BytesIO(data))
    layouts = [page.extract_text(extraction_mode='layout') or '' for page in reader.pages]
    joined = '\n'.join(layouts)
    period = _period(joined)
    rows: list[dict] = []
    warnings: list[str] = []
    balances: dict[str, int] = {}

    for page_number, text in enumerate(layouts, start=1):
        lines = text.splitlines()
        columns = _table_columns(lines)
        if not columns:
            continue
        debit_col, credit_col = columns

        for line_number, line in enumerate(lines, start=1):
            balance = _parse_balance_line(line, debit_col, credit_col)
            if balance:
                balances[balance[0]] = balance[1]
                continue

            parsed = _parse_transaction_line(line, credit_col)
            if not parsed:
                continue

            try:
                booking = _booking_date(parsed['booking_short'], parsed['value_date'])
            except ValueError:
                warnings.append(f'page {page_number} line {line_number}: invalid date')
                continue

            rows.append({
                'booking_date': booking.isoformat(),
                'amount_cents': parsed['amount_cents'],
                'label': parsed['label'],
                'raw': {
                    'page': page_number,
                    'line_number': line_number,
                    'line': ' '.join(line.split()),
                    'value_date': parsed['value_date'],
                    'parser': 'lcl-layout-v2',
                },
            })

    if not rows:
        raise ValueError('Aucune opération LCL exploitable détectée dans ce PDF')

    if 'ANCIEN SOLDE' not in balances:
        warnings.append('opening balance not detected')
    if 'SOLDE EN EUROS' not in balances:
        warnings.append('closing balance not detected')

    return rows, {
        'period_start': period[0].isoformat() if period else None,
        'period_end': period[1].isoformat() if period else None,
        'opening_balance_cents': balances.get('ANCIEN SOLDE'),
        'closing_balance_cents': balances.get('SOLDE EN EUROS'),
        'warnings': warnings,
        'parser': 'lcl-layout-v2',
    }
