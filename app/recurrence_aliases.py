from __future__ import annotations

from collections import defaultdict
from datetime import date
from statistics import median

from .imports import normalize_label


# Explicit business-confirmed recurring aliases. These mappings are deliberately
# narrow: they encode known continuity decisions and must not be generalized to
# other merchants automatically.
RECURRENCE_ALIAS_GROUPS = {
    'CANAL PLUS': (
        'CANAL SAT',
        'CANAL PLUS FR',
    ),
    'LOGEMENT SAINT SABIN': (
        'APPART SAINT SABI',
        'IMMOBILIER DE CARNE',
        'IMMOBILIER DE CAR',
    ),
}

ALIAS_FRESHNESS_DAYS = 45


def alias_group_for_label(label: str | None) -> str | None:
    value = normalize_label(label or '')
    for canonical, aliases in RECURRENCE_ALIAS_GROUPS.items():
        if any(alias in value for alias in aliases):
            return canonical
    return None


def _next_expected(last_seen: date, usual_day: int) -> date:
    import calendar

    year = last_seen.year + (1 if last_seen.month == 12 else 0)
    month = 1 if last_seen.month == 12 else last_seen.month + 1
    return date(year, month, min(max(1, usual_day), calendar.monthrange(year, month)[1]))


def apply_confirmed_recurrence_aliases(conn, account_id: int | None = None) -> dict:
    """Merge explicitly confirmed recurring aliases into canonical profiles.

    The source transactions remain untouched. Only derived recurring profiles and
    recurring_occurrence links are consolidated so history follows the real
    continuity of the charge.

    A business-confirmed alias does not automatically mean the charge is still
    active. If its last observed transaction is older than ALIAS_FRESHNESS_DAYS
    relative to the latest imported bank transaction, the canonical profile is
    kept as historical/inactive and no next expected date is produced.
    """
    params: tuple = ()
    where = 'WHERE t.amount_cents < 0 AND t.is_internal_transfer=0'
    if account_id is not None:
        where += ' AND t.account_id=?'
        params = (account_id,)

    rows = conn.execute(f'''
        SELECT t.id,t.account_id,t.booking_date,t.amount_cents,t.label,t.category
        FROM transactions t
        {where}
        ORDER BY t.account_id,t.booking_date,t.id
    ''', params).fetchall()

    latest_transaction_row = conn.execute('SELECT MAX(booking_date) latest FROM transactions').fetchone()
    latest_transaction_date = (
        date.fromisoformat(latest_transaction_row['latest'])
        if latest_transaction_row and latest_transaction_row['latest']
        else None
    )

    grouped: dict[tuple[int, str], list] = defaultdict(list)
    for row in rows:
        canonical = alias_group_for_label(row['label'])
        if canonical:
            grouped[(row['account_id'], canonical)].append(row)

    merged_profiles = 0
    merged_occurrences = 0
    active_profiles = 0
    historical_profiles = 0

    for (acct, canonical), occurrences in grouped.items():
        months = {row['booking_date'][:7] for row in occurrences}
        if len(occurrences) < 2 or len(months) < 2:
            continue

        dates = [date.fromisoformat(row['booking_date']) for row in occurrences]
        amounts = [abs(int(row['amount_cents'])) for row in occurrences]
        last_seen = max(dates)

        # Use the most recent phase to describe cadence. This avoids old provider
        # history distorting the day-of-month after a confirmed alias transition.
        recent_occurrences = sorted(
            occurrences,
            key=lambda row: (row['booking_date'], row['id']),
        )[-3:]
        recent_days = [date.fromisoformat(row['booking_date']).day for row in recent_occurrences]
        usual_day = int(round(median(recent_days)))
        day_tolerance = max(abs(day - usual_day) for day in recent_days)

        latest = max(occurrences, key=lambda row: (row['booking_date'], row['id']))
        current_amount = abs(int(latest['amount_cents']))
        amount_min = min(amounts)
        amount_max = max(amounts)
        category = next((row['category'] for row in reversed(occurrences) if row['category']), None)
        source_key = f'recurring:confirmed-alias:{acct}:{canonical.lower().replace(" ", "-")}'

        age_days = (
            max(0, (latest_transaction_date - last_seen).days)
            if latest_transaction_date is not None
            else 999999
        )
        is_fresh = age_days <= ALIAS_FRESHNESS_DAYS
        is_active = 1 if is_fresh else 0
        detection_status = 'accepted' if is_fresh else 'confirmed_alias_history'
        next_expected_date = _next_expected(last_seen, usual_day).isoformat() if is_fresh else None
        if is_fresh:
            active_profiles += 1
        else:
            historical_profiles += 1

        existing_alias = conn.execute(
            'SELECT id FROM recurring_transactions WHERE source_key=? LIMIT 1',
            (source_key,),
        ).fetchone()
        existing_alias_id = existing_alias['id'] if existing_alias else None

        member_profiles = conn.execute('''
            SELECT id,label,merchant_key FROM recurring_transactions
            WHERE account_id=?
        ''', (acct,)).fetchall()
        member_ids = [
            row['id'] for row in member_profiles
            if row['id'] != existing_alias_id
            and (
                alias_group_for_label(row['label']) == canonical
                or alias_group_for_label(row['merchant_key']) == canonical
            )
        ]
        if member_ids:
            placeholders = ','.join('?' for _ in member_ids)
            conn.execute(f'DELETE FROM recurring_transactions WHERE id IN ({placeholders})', tuple(member_ids))

        profile_values = (
            canonical.title(), -current_amount, usual_day, category,
            amount_max - amount_min, is_active, canonical,
            usual_day, day_tolerance, amount_min, amount_max,
            last_seen.isoformat(), next_expected_date, len(occurrences), detection_status,
        )

        if existing_alias_id is not None:
            conn.execute('''
                UPDATE recurring_transactions
                SET label=?,amount_cents=?,day_of_month=?,category=COALESCE(?,category),
                    kind='commitment',certainty='expected',tolerance_cents=?,is_active=?,
                    source_type='confirmed_alias',merchant_key=?,recurrence_type='monthly',
                    usual_day=?,day_tolerance=?,amount_min_cents=?,amount_max_cents=?,
                    last_seen_date=?,next_expected_date=?,occurrence_count=?,confidence=1.0,
                    detection_status=?
                WHERE id=?
            ''', profile_values + (existing_alias_id,))
            recurring_id = existing_alias_id
            conn.execute('DELETE FROM recurring_occurrences WHERE recurring_id=?', (recurring_id,))
        else:
            cur = conn.execute('''
                INSERT INTO recurring_transactions(
                    account_id,label,amount_cents,day_of_month,category,kind,certainty,tolerance_cents,is_active,
                    source_type,source_key,merchant_key,recurrence_type,usual_day,day_tolerance,amount_min_cents,
                    amount_max_cents,last_seen_date,next_expected_date,occurrence_count,confidence,detection_status
                ) VALUES(?,?,?,?,?,'commitment','expected',?,?,'confirmed_alias',?,?,'monthly',?,?,?,?,?,?,?,1.0,?)
            ''', (
                acct, canonical.title(), -current_amount, usual_day, category,
                amount_max - amount_min, is_active, source_key, canonical,
                usual_day, day_tolerance, amount_min, amount_max,
                last_seen.isoformat(), next_expected_date, len(occurrences), detection_status,
            ))
            recurring_id = cur.lastrowid

        for row in occurrences:
            conn.execute('''
                INSERT OR IGNORE INTO recurring_occurrences(recurring_id,transaction_id,booking_date,amount_cents)
                VALUES(?,?,?,?)
            ''', (recurring_id, row['id'], row['booking_date'], row['amount_cents']))
            merged_occurrences += 1
        merged_profiles += 1

    return {
        'merged_profiles': merged_profiles,
        'merged_occurrences': merged_occurrences,
        'active_profiles': active_profiles,
        'historical_profiles': historical_profiles,
        'latest_transaction_date': latest_transaction_date.isoformat() if latest_transaction_date else None,
    }
