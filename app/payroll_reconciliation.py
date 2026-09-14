from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

from .data_intelligence import ensure_intelligence_schema
from .imports import normalize_label


PAYROLL_AMOUNT_TOLERANCE_CENTS = 5000
MIN_SALARY_CENTS = 100000


def _period_matching_window(period: str) -> tuple[date, date, date] | None:
    """Return the bank window used to reconcile a payslip to the actual salary credit.

    Documentary reconciliation follows the payslip period itself. The separate
    Flow budgeting rule assigns a salary received at the end of month N to the
    spending/budget month N+1.
    """
    try:
        year, month = (int(v) for v in period.split('-', 1))
    except Exception:
        return None
    month_start = date(year, month, 1)
    month_end = date(year, month, calendar.monthrange(year, month)[1])
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    end = next_month + timedelta(days=7)
    return month_start, month_end, end


def period_payment_window(period: str) -> tuple[date, date] | None:
    bounds = _period_matching_window(period)
    if not bounds:
        return None
    start, _, end = bounds
    return start, end


def period_has_bank_coverage(period: str | None, coverage_start: str | None, coverage_end: str | None) -> bool:
    if not period or not coverage_start or not coverage_end:
        return False
    bounds = _period_matching_window(period)
    if not bounds:
        return False
    start, _, end = bounds
    try:
        cov_start = date.fromisoformat(coverage_start)
        cov_end = date.fromisoformat(coverage_end)
    except Exception:
        return False
    return (end - timedelta(days=1)) >= cov_start and start <= cov_end


def budget_month_for_salary_date(value: str | date) -> str:
    """Return the Flow budget month funded by a salary credit.

    Business rule: a salary credited at the end of month N finances month N+1.
    This is intentionally independent from payslip reconciliation.
    """
    booking = date.fromisoformat(value) if isinstance(value, str) else value
    if booking.month == 12:
        return f'{booking.year + 1:04d}-01'
    return f'{booking.year:04d}-{booking.month + 1:02d}'


def _employer_tokens(employer: str | None) -> tuple[str, ...]:
    normalized = normalize_label(employer or '')
    return tuple(token for token in re.findall(r'[A-Z0-9]{4,}', normalized) if token not in {'SAS', 'SARL'})


def credible_employer_candidates(conn, period: str, employer: str | None = None):
    bounds = _period_matching_window(period)
    if not bounds:
        return []
    start, _, end = bounds
    tokens = _employer_tokens(employer)
    rows = conn.execute(
        '''SELECT * FROM transactions
           WHERE amount_cents>=? AND is_internal_transfer=0
             AND booking_date>=? AND booking_date<?
           ORDER BY booking_date,id''',
        (MIN_SALARY_CENTS, start.isoformat(), end.isoformat()),
    ).fetchall()
    result = []
    for tx in rows:
        label = normalize_label(tx['label'])
        token_hits = sum(1 for token in tokens if token in label)
        salary_hint = any(hint in label for hint in ('SALAIRE', 'SALAIRES', 'KARDHAM', 'PAYROLL'))
        if token_hits or salary_hint:
            result.append(tx)
    return result


def reconcile_payroll(conn) -> dict:
    ensure_intelligence_schema(conn)
    payrolls = conn.execute('''
        SELECT p.* FROM payroll_records p
        LEFT JOIN payroll_transaction_matches m ON m.payroll_record_id=p.id
        WHERE m.id IS NULL
        ORDER BY p.period,p.id
    ''').fetchall()

    matched = 0
    unresolved = 0
    for payroll in payrolls:
        period = payroll['period']
        net_paid = payroll['net_paid_cents']
        bounds = _period_matching_window(period) if period else None
        if net_paid is None or not bounds:
            unresolved += 1
            continue

        start, month_end, end = bounds
        tokens = _employer_tokens(payroll['employer'])
        candidates = conn.execute('''
            SELECT t.* FROM transactions t
            LEFT JOIN payroll_transaction_matches m ON m.transaction_id=t.id
            WHERE t.amount_cents>0
              AND t.booking_date>=? AND t.booking_date<?
              AND t.is_internal_transfer=0
              AND m.id IS NULL
            ORDER BY ABS(t.amount_cents-?), t.booking_date, t.id
        ''', (start.isoformat(), end.isoformat(), net_paid)).fetchall()

        scored = []
        for tx in candidates:
            amount_diff = abs(tx['amount_cents'] - net_paid)
            if amount_diff > PAYROLL_AMOUNT_TOLERANCE_CENTS:
                continue
            label = normalize_label(tx['label'])
            token_hits = sum(1 for token in tokens if token in label)
            salary_hint = any(hint in label for hint in ('SALAIRE', 'SALAIRES', 'KARDHAM', 'PAYROLL'))
            if not (token_hits or salary_hint):
                continue
            amount_score = max(0.0, 1.0 - amount_diff / PAYROLL_AMOUNT_TOLERANCE_CENTS)
            date_distance = abs((date.fromisoformat(tx['booking_date']) - month_end).days)
            date_score = max(0.0, 1.0 - date_distance / 12.0)
            employer_score = 0.25 if token_hits else 0.0
            hint_score = 0.20 if salary_hint else 0.0
            confidence = min(1.0, 0.45 * amount_score + 0.10 * date_score + employer_score + hint_score)
            scored.append((confidence, amount_diff, date_distance, tx))

        selected = None
        if scored:
            scored.sort(key=lambda item: (-item[0], item[1], item[2], item[3]['id']))
            confidence, amount_diff, date_distance, tx = scored[0]
            if confidence >= 0.72:
                selected = (
                    tx,
                    confidence,
                    f'same-period payroll match; period={period}; amount_diff={amount_diff}; '
                    f'date_distance={date_distance}; budget_month={budget_month_for_salary_date(tx["booking_date"])}; '
                    f'employer={payroll["employer"] or "unknown"}',
                )

        if selected is None:
            strong = []
            for tx in candidates:
                if tx['amount_cents'] < MIN_SALARY_CENTS:
                    continue
                label = normalize_label(tx['label'])
                token_hits = sum(1 for token in tokens if token in label)
                salary_hint = any(hint in label for hint in ('SALAIRE', 'SALAIRES', 'KARDHAM', 'PAYROLL'))
                if token_hits or salary_hint:
                    strong.append(tx)
            if len(strong) == 1:
                tx = strong[0]
                amount_diff = abs(tx['amount_cents'] - net_paid)
                selected = (
                    tx,
                    0.90 if amount_diff <= PAYROLL_AMOUNT_TOLERANCE_CENTS else 0.82,
                    f'same-period unique employer fallback; period={period}; amount_diff={amount_diff}; '
                    f'parsed_net_paid={net_paid}; budget_month={budget_month_for_salary_date(tx["booking_date"])}; '
                    f'employer={payroll["employer"] or "unknown"}',
                )

        if selected is None:
            unresolved += 1
            continue

        tx, confidence, reason = selected
        cur = conn.execute('''
            INSERT OR IGNORE INTO payroll_transaction_matches(payroll_record_id,transaction_id,confidence,match_reason)
            VALUES(?,?,?,?)
        ''', (payroll['id'], tx['id'], round(confidence, 4), reason))
        if cur.rowcount <= 0:
            unresolved += 1
            continue
        conn.execute(
            "UPDATE transactions SET category=COALESCE(category,'Salaire'), transaction_type='income' WHERE id=?",
            (tx['id'],),
        )
        matched += 1

    return {'matched': matched, 'unresolved': unresolved}
