from __future__ import annotations

from datetime import date
import re

from .imports import normalize_label


TRANSFER_HINTS = (
    'VIR ',
    'VIREMENT',
    'VIR.PERMANENT',
    'VIR PERMANENT',
)

# Flow is a personal finance application. These prefixes represent transfers
# explicitly carrying the account owner's identity in the bank label. They can
# be treated as internal even when only one side of the transfer is currently
# imported. This remains distinct from pair-confirmed transfers between two
# imported accounts.
#
# VIR.PERMANENT BACHOUR and VIR SEPA BACHOUR were manually validated by the
# account owner as transfers to another one of their accounts. Keep the exact
# prefixes narrow so unrelated third-party transfers remain ordinary cashflow.
OWNER_TRANSFER_PREFIXES = (
    'VIR SEPA M PETER BACHOUR',
    'VIR INST M PETER BACHOUR',
    'VIR INST M. PETER BACHOUR',
    'VIREMENT M PETER BACHOUR',
    'VIREMENT M. PETER BACHOUR',
    'VIREMENT BACHOUR P',
    'VIR.PERMANENT BACHOUR',
    'VIR SEPA BACHOUR',
)


def ensure_transfer_schema(conn) -> None:
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS internal_transfer_matches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        debit_transaction_id INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
        credit_transaction_id INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
        amount_cents INTEGER NOT NULL,
        day_gap INTEGER NOT NULL,
        confidence REAL NOT NULL,
        status TEXT NOT NULL DEFAULT 'confirmed',
        match_reason TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(debit_transaction_id),
        UNIQUE(credit_transaction_id)
    );
    CREATE TABLE IF NOT EXISTS internal_transfer_candidates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        transaction_id INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
        reason TEXT NOT NULL,
        confidence REAL NOT NULL,
        status TEXT NOT NULL DEFAULT 'review',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(transaction_id)
    );
    ''')


def _looks_like_transfer(label: str) -> bool:
    value = normalize_label(label or '')
    return any(hint in value for hint in TRANSFER_HINTS)


def _looks_like_owner_transfer(label: str) -> bool:
    value = normalize_label(label or '')
    return value.startswith(OWNER_TRANSFER_PREFIXES)


def _label_tokens(label: str) -> set[str]:
    value = normalize_label(label or '')
    ignored = {'VIR', 'VIREMENT', 'PERMANENT', 'SEPA', 'EMIS', 'RECU', 'DE', 'A', 'AU', 'VERS'}
    return {token for token in re.findall(r'[A-Z0-9]{3,}', value) if token not in ignored}


def _label_similarity(a: str, b: str) -> float:
    ta = _label_tokens(a)
    tb = _label_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(1, len(ta | tb))


def detect_internal_transfers(conn, *, max_day_gap: int = 3) -> dict:
    """Detect internal transfers conservatively.

    Confidence tiers:
    - pair-confirmed: exact opposite amount on another imported account;
    - identity-confirmed: bank label explicitly carries the owner's identity or
      an exact owner-validated transfer prefix;
    - review: transfer-like labels that are neither of the above.

    Only the first two tiers are excluded from spending automatically.
    """
    ensure_transfer_schema(conn)

    rows = [dict(r) for r in conn.execute('''
        SELECT id,account_id,booking_date,amount_cents,label,is_internal_transfer,destination_account_id
        FROM transactions
        ORDER BY booking_date,id
    ''').fetchall()]

    identity_confirmed = 0
    for row in rows:
        if not _looks_like_owner_transfer(row['label']):
            continue
        if not row['is_internal_transfer']:
            conn.execute(
                "UPDATE transactions SET is_internal_transfer=1, transaction_type='transfer', category='Transfert interne' WHERE id=?",
                (row['id'],),
            )
        conn.execute('''
            INSERT INTO internal_transfer_candidates(transaction_id,reason,confidence,status)
            VALUES(?,?,?,'confirmed_identity')
            ON CONFLICT(transaction_id) DO UPDATE SET
              reason=excluded.reason,confidence=excluded.confidence,status=excluded.status
        ''', (
            row['id'],
            'bank label matches an owner-confirmed internal-transfer prefix; counterpart account not yet imported',
            0.98,
        ))
        identity_confirmed += 1

    rows = [dict(r) for r in conn.execute('''
        SELECT id,account_id,booking_date,amount_cents,label,is_internal_transfer,destination_account_id
        FROM transactions
        ORDER BY booking_date,id
    ''').fetchall()]

    debits = [r for r in rows if r['amount_cents'] < 0 and not r['is_internal_transfer']]
    credits = [r for r in rows if r['amount_cents'] > 0 and not r['is_internal_transfer']]
    used_credit_ids: set[int] = set()
    confirmed = 0

    for debit in debits:
        ddate = date.fromisoformat(debit['booking_date'])
        candidates = []
        for credit in credits:
            if credit['id'] in used_credit_ids:
                continue
            if credit['account_id'] == debit['account_id']:
                continue
            if credit['amount_cents'] != -debit['amount_cents']:
                continue
            cdate = date.fromisoformat(credit['booking_date'])
            gap = abs((cdate - ddate).days)
            if gap > max_day_gap:
                continue
            similarity = _label_similarity(debit['label'], credit['label'])
            transfer_hint = _looks_like_transfer(debit['label']) or _looks_like_transfer(credit['label'])
            confidence = 0.90 + (0.05 if transfer_hint else 0.0) + min(0.04, similarity * 0.04)
            candidates.append((min(confidence, 0.99), gap, -similarity, credit))

        if not candidates:
            continue
        candidates.sort(key=lambda item: (-item[0], item[1], item[2], item[3]['id']))
        confidence, gap, _, credit = candidates[0]
        cur = conn.execute('''
            INSERT OR IGNORE INTO internal_transfer_matches(
                debit_transaction_id,credit_transaction_id,amount_cents,day_gap,confidence,status,match_reason
            ) VALUES(?,?,?,?,?,'confirmed',?)
        ''', (
            debit['id'], credit['id'], -debit['amount_cents'], gap, round(confidence, 4),
            'exact opposite amount on different accounts within date window',
        ))
        if cur.rowcount <= 0:
            continue
        conn.execute(
            "UPDATE transactions SET is_internal_transfer=1, transaction_type='transfer', destination_account_id=? WHERE id=?",
            (credit['account_id'], debit['id']),
        )
        conn.execute(
            "UPDATE transactions SET is_internal_transfer=1, transaction_type='transfer', destination_account_id=? WHERE id=?",
            (debit['account_id'], credit['id']),
        )
        used_credit_ids.add(credit['id'])
        confirmed += 1

    conn.execute("DELETE FROM internal_transfer_candidates WHERE status='review'")

    review = 0
    for row in rows:
        fresh = conn.execute('SELECT is_internal_transfer FROM transactions WHERE id=?', (row['id'],)).fetchone()
        if fresh and fresh['is_internal_transfer']:
            continue
        if not _looks_like_transfer(row['label']):
            continue
        value = normalize_label(row['label'] or '')
        # Surname-only matches are not sufficient: relatives/third parties can
        # legitimately share BACHOUR. Keep review limited to explicit owner
        # identity hints not already covered by trusted prefixes.
        owner_hint = 'PETER' in value
        if not owner_hint:
            continue
        cur = conn.execute('''
            INSERT OR IGNORE INTO internal_transfer_candidates(transaction_id,reason,confidence,status)
            VALUES(?,?,?,'review')
        ''', (row['id'], 'owner-like transfer label not covered by trusted identity prefixes', 0.60))
        review += int(cur.rowcount > 0)

    return {
        'confirmed_pairs': confirmed,
        'confirmed_identity': identity_confirmed,
        'review_candidates': review,
    }
