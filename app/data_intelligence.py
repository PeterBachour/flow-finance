from __future__ import annotations

import calendar
import hashlib
import re
from collections import defaultdict
from datetime import date, timedelta
from statistics import median

from .imports import normalize_label


EXCLUDED_RECURRING_KEYS = {
    'TOTAL INCIDENTS FONCTIONNEMENT',
}


def ensure_intelligence_schema(conn) -> None:
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS payroll_transaction_matches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        payroll_record_id INTEGER NOT NULL REFERENCES payroll_records(id) ON DELETE CASCADE,
        transaction_id INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
        confidence REAL NOT NULL,
        match_reason TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(payroll_record_id),
        UNIQUE(transaction_id)
    );
    CREATE TABLE IF NOT EXISTS recurring_occurrences (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        recurring_id INTEGER NOT NULL REFERENCES recurring_transactions(id) ON DELETE CASCADE,
        transaction_id INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
        booking_date TEXT NOT NULL,
        amount_cents INTEGER NOT NULL,
        detected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(recurring_id, transaction_id)
    );
    CREATE INDEX IF NOT EXISTS idx_recurring_occurrences_recurring_date
      ON recurring_occurrences(recurring_id, booking_date);
    ''')
    columns = {row[1] for row in conn.execute('PRAGMA table_info(recurring_transactions)').fetchall()}
    additions = {
        'merchant_key': 'TEXT',
        'recurrence_type': "TEXT NOT NULL DEFAULT 'monthly'",
        'usual_day': 'INTEGER',
        'day_tolerance': 'INTEGER NOT NULL DEFAULT 0',
        'amount_min_cents': 'INTEGER',
        'amount_max_cents': 'INTEGER',
        'last_seen_date': 'TEXT',
        'next_expected_date': 'TEXT',
        'occurrence_count': 'INTEGER NOT NULL DEFAULT 0',
        'confidence': 'REAL',
        'detection_status': "TEXT NOT NULL DEFAULT 'manual'",
    }
    for name, definition in additions.items():
        if name not in columns:
            conn.execute(f'ALTER TABLE recurring_transactions ADD COLUMN {name} {definition}')
    conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_recurring_merchant_key ON recurring_transactions(account_id,merchant_key) WHERE merchant_key IS NOT NULL')


def _employer_tokens(employer: str | None) -> tuple[str, ...]:
    normalized = normalize_label(employer or '')
    return tuple(token for token in re.findall(r'[A-Z0-9]{4,}', normalized) if token not in {'SAS', 'SARL'})


def _period_bounds(period: str) -> tuple[date, date, date] | None:
    try:
        year, month = (int(v) for v in period.split('-', 1))
    except Exception:
        return None
    start = date(year, month, 1)
    month_end = date(year, month, calendar.monthrange(year, month)[1])
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    return start, month_end, next_month + timedelta(days=7)


def _fallback_employer_candidate(candidates, tokens: tuple[str, ...], month_end: date):
    strong = []
    for tx in candidates:
        label = normalize_label(tx['label'])
        token_hits = sum(1 for token in tokens if token in label)
        salary_hint = any(hint in label for hint in ('SALAIRE', 'SALAIRES', 'KARDHAM', 'PAYROLL'))
        booking = date.fromisoformat(tx['booking_date'])
        in_pay_window = booking >= month_end - timedelta(days=12) and booking <= month_end + timedelta(days=7)
        if tx['amount_cents'] >= 100000 and in_pay_window and (token_hits or salary_hint):
            strong.append(tx)
    if not strong:
        return None
    strong.sort(key=lambda tx: (-tx['amount_cents'], abs((date.fromisoformat(tx['booking_date']) - month_end).days), tx['id']))
    if len(strong) == 1:
        return strong[0], 0.90, 'employer-period unique fallback'
    first, second = strong[0], strong[1]
    if first['amount_cents'] >= int(second['amount_cents'] * 1.20):
        return first, 0.84, 'employer-period dominant fallback'
    return None


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
        if not period or net_paid is None:
            unresolved += 1
            continue
        bounds = _period_bounds(period)
        if not bounds:
            unresolved += 1
            continue
        start, month_end, end = bounds
        candidates = conn.execute('''
            SELECT t.* FROM transactions t
            LEFT JOIN payroll_transaction_matches m ON m.transaction_id=t.id
            WHERE t.amount_cents > 0
              AND t.booking_date >= ? AND t.booking_date < ?
              AND t.is_internal_transfer=0
              AND m.id IS NULL
            ORDER BY ABS(t.amount_cents-?), t.booking_date, t.id
        ''', (start.isoformat(), end.isoformat(), net_paid)).fetchall()
        tokens = _employer_tokens(payroll['employer'])
        scored = []
        for tx in candidates:
            amount_diff = abs(tx['amount_cents'] - net_paid)
            if amount_diff > 5000:
                continue
            label = normalize_label(tx['label'])
            token_hits = sum(1 for token in tokens if token in label)
            salary_hint = any(hint in label for hint in ('SALAIRE', 'SALAIRES', 'KARDHAM', 'PAYROLL'))
            amount_score = max(0.0, 1.0 - amount_diff / 5000.0)
            employer_score = 0.25 if token_hits else 0.0
            hint_score = 0.2 if salary_hint else 0.0
            confidence = min(1.0, 0.55 * amount_score + employer_score + hint_score)
            scored.append((confidence, amount_diff, tx))

        selected = None
        if scored:
            scored.sort(key=lambda item: (-item[0], item[1], item[2]['booking_date']))
            confidence, amount_diff, tx = scored[0]
            if confidence >= 0.72:
                selected = (tx, confidence, f'amount match; period={period}; amount_diff={amount_diff}; employer={payroll["employer"] or "unknown"}')

        if selected is None:
            fallback = _fallback_employer_candidate(candidates, tokens, month_end)
            if fallback:
                tx, confidence, fallback_reason = fallback
                amount_diff = abs(tx['amount_cents'] - net_paid)
                selected = (
                    tx,
                    confidence,
                    f'{fallback_reason}; period={period}; amount_diff={amount_diff}; parsed_net_paid={net_paid}; employer={payroll["employer"] or "unknown"}',
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
        conn.execute("UPDATE transactions SET category=COALESCE(category,'Salaire'), transaction_type='income' WHERE id=?", (tx['id'],))
        matched += 1
    return {'matched': matched, 'unresolved': unresolved}


def merchant_key(label: str) -> str:
    value = normalize_label(label)
    value = re.sub(r'\b\d{2}/\d{2}/\d{2,4}\b', ' ', value)
    value = re.sub(r'\b\d{6,}\b', ' ', value)
    value = re.sub(r'\b(?:REF|CLIENT|MANDAT|DOSSIER)\b.*$', ' ', value)
    value = re.sub(r'\s+', ' ', value).strip()
    tokens = value.split()
    if not tokens:
        return 'UNKNOWN'
    if tokens[0] in {'PRLV', 'VIR', 'VIREMENT', 'PRET', 'COTISATION'}:
        tokens = tokens[:6]
    elif tokens[0] == 'CB':
        tokens = tokens[:5]
    return ' '.join(tokens)


def recurring_quality_status(key: str, day_tolerance: int, amount_min: int, amount_max: int) -> tuple[str, str]:
    if key in EXCLUDED_RECURRING_KEYS or key.startswith('TOTAL INCIDENTS'):
        return 'excluded', 'bank statement aggregate, not a merchant recurrence'
    if day_tolerance > 10:
        return 'review_date', f'day tolerance too large ({day_tolerance} days)'
    spread = max(0, amount_max - amount_min)
    spread_ratio = spread / max(1, amount_max)
    if spread_ratio > 0.45:
        return 'review_amount', f'amount spread too large ({spread_ratio:.1%})'
    return 'accepted', 'stable recurrence profile'


def _month_index(value: str) -> int:
    year, month = (int(v) for v in value.split('-', 1))
    return year * 12 + month


def _strong_monthly_cadence(occurrences: list[dict]) -> bool:
    months = sorted({_month_index(o['booking_date'][:7]) for o in occurrences})
    if len(months) < 4:
        return False
    span = months[-1] - months[0] + 1
    coverage_ratio = len(months) / max(1, span)
    occurrence_density = len(occurrences) / max(1, len(months))
    return coverage_ratio >= 0.65 and occurrence_density <= 1.25


def _next_month_day(last_seen: date, usual_day: int) -> date:
    year = last_seen.year + (1 if last_seen.month == 12 else 0)
    month = 1 if last_seen.month == 12 else last_seen.month + 1
    max_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(max(1, usual_day), max_day))


def _confidence(occurrences: list[dict], day_tolerance: int, amount_spread: int) -> float:
    count_score = min(1.0, len(occurrences) / 8.0)
    day_score = max(0.0, 1.0 - day_tolerance / 8.0)
    median_amount = max(1, abs(int(median([o['amount_cents'] for o in occurrences]))))
    amount_score = max(0.0, 1.0 - amount_spread / max(100, median_amount * 0.35))
    return round(0.45 * count_score + 0.30 * day_score + 0.25 * amount_score, 4)


def detect_recurring_transactions(conn, account_id: int | None = None) -> dict:
    ensure_intelligence_schema(conn)
    params: tuple = ()
    where = "WHERE t.amount_cents < 0 AND t.is_internal_transfer=0"
    if account_id is not None:
        where += " AND t.account_id=?"
        params = (account_id,)
    rows = conn.execute(f'''
        SELECT t.id,t.account_id,t.booking_date,t.amount_cents,t.label,t.category,t.transaction_type
        FROM transactions t
        {where}
        ORDER BY t.account_id,t.booking_date,t.id
    ''', params).fetchall()
    grouped: dict[tuple[int, str], list[dict]] = defaultdict(list)
    for row in rows:
        key = merchant_key(row['label'])
        grouped[(row['account_id'], key)].append(dict(row))

    detected = 0
    updated = 0
    accepted = 0
    review_date = 0
    review_amount = 0
    excluded = 0
    for (acct, key), occurrences in grouped.items():
        months = {o['booking_date'][:7] for o in occurrences}
        if len(occurrences) < 3 or len(months) < 3:
            continue
        parsed_dates = [date.fromisoformat(o['booking_date']) for o in occurrences]
        days = [d.day for d in parsed_dates]
        amounts_abs = [abs(o['amount_cents']) for o in occurrences]
        usual_day = int(round(median(days)))
        day_tolerance = max(abs(day - usual_day) for day in days)
        amount_median = int(round(median(amounts_abs)))
        amount_min = min(amounts_abs)
        amount_max = max(amounts_abs)
        spread = amount_max - amount_min
        last_seen = max(parsed_dates)

        quality_status, _ = recurring_quality_status(key, day_tolerance, amount_min, amount_max)
        if quality_status == 'excluded':
            excluded += 1
            continue

        confidence = _confidence(occurrences, day_tolerance, spread)
        if quality_status == 'accepted':
            if confidence < 0.52:
                continue
        elif not _strong_monthly_cadence(occurrences):
            # Abnormal profiles are only useful for review if the history still
            # demonstrates a clear monthly cadence. This suppresses incidental
            # merchants that merely appear in several months.
            continue

        if quality_status == 'accepted':
            accepted += 1
        elif quality_status == 'review_date':
            review_date += 1
        elif quality_status == 'review_amount':
            review_amount += 1

        next_expected = _next_month_day(last_seen, usual_day)
        source_key = 'recurring:auto:' + hashlib.sha256(f'{acct}|{key}'.encode()).hexdigest()
        existing = conn.execute('SELECT id FROM recurring_transactions WHERE account_id=? AND merchant_key=?', (acct, key)).fetchone()
        label = key.title()
        category = next((o['category'] for o in reversed(occurrences) if o.get('category')), None)
        is_active = int(quality_status == 'accepted')
        if existing:
            recurring_id = existing['id']
            conn.execute('''
                UPDATE recurring_transactions
                SET label=?,amount_cents=?,day_of_month=?,category=COALESCE(?,category),
                    tolerance_cents=?,usual_day=?,day_tolerance=?,amount_min_cents=?,amount_max_cents=?,
                    last_seen_date=?,next_expected_date=?,occurrence_count=?,confidence=?,detection_status=?,
                    source_type='history',source_key=?,is_active=?
                WHERE id=?
            ''', (label, -amount_median, usual_day, category, spread, usual_day, day_tolerance, amount_min, amount_max,
                  last_seen.isoformat(), next_expected.isoformat(), len(occurrences), confidence, quality_status,
                  source_key, is_active, recurring_id))
            updated += 1
        else:
            cur = conn.execute('''
                INSERT INTO recurring_transactions(
                    account_id,label,amount_cents,day_of_month,category,kind,certainty,tolerance_cents,is_active,
                    source_type,source_key,merchant_key,recurrence_type,usual_day,day_tolerance,amount_min_cents,
                    amount_max_cents,last_seen_date,next_expected_date,occurrence_count,confidence,detection_status
                ) VALUES(?,?,?,?,?,'commitment','expected',?,?,'history',?,?,'monthly',?,?,?,?,?,?,?,?,?)
            ''', (acct, label, -amount_median, usual_day, category, spread, is_active, source_key, key, usual_day, day_tolerance,
                  amount_min, amount_max, last_seen.isoformat(), next_expected.isoformat(), len(occurrences), confidence, quality_status))
            recurring_id = cur.lastrowid
            detected += 1
        for occurrence in occurrences:
            conn.execute('''
                INSERT OR IGNORE INTO recurring_occurrences(recurring_id,transaction_id,booking_date,amount_cents)
                VALUES(?,?,?,?)
            ''', (recurring_id, occurrence['id'], occurrence['booking_date'], occurrence['amount_cents']))
    return {
        'detected': detected,
        'updated': updated,
        'accepted': accepted,
        'review_date': review_date,
        'review_amount': review_amount,
        'excluded': excluded,
    }


def refresh_financial_intelligence(conn, account_id: int | None = None) -> dict:
    payroll = reconcile_payroll(conn)
    recurring = detect_recurring_transactions(conn, account_id=account_id)
    return {'payroll': payroll, 'recurring': recurring}
