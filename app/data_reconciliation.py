from __future__ import annotations

from datetime import date


def _table_exists(conn, name: str) -> bool:
    return bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (name,),
    ).fetchone())


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def reconcile_account_balances(conn) -> dict:
    """Compare account snapshots with the ledger reconstructed from a verified statement.

    This function is read-only. A verified statement closing balance is used as
    the anchor; confirmed ledger movements strictly after the statement period
    and up to the account balance date are then applied. The reconstructed
    balance must equal the stored current balance for the account to be marked
    reconciled.
    """
    accounts = conn.execute(
        "SELECT id,name,current_balance_cents,balance_as_of FROM accounts WHERE is_active=1 ORDER BY id"
    ).fetchall()

    has_imports = _table_exists(conn, 'imports')
    results: list[dict] = []
    reconciled_count = 0
    mismatch_count = 0
    unavailable_count = 0

    for account in accounts:
        balance_date = _parse_date(account['balance_as_of'])
        base = {
            'account_id': int(account['id']),
            'account_name': account['name'],
            'balance_as_of': account['balance_as_of'],
            'actual_balance_cents': int(account['current_balance_cents'] or 0),
        }
        if balance_date is None:
            unavailable_count += 1
            results.append({
                **base,
                'status': 'unavailable_no_balance_date',
                'reason': 'Le solde courant n’a pas de date de référence valide.',
                'anchor': None,
                'ledger_delta_cents': None,
                'expected_balance_cents': None,
                'difference_cents': None,
            })
            continue

        anchor = None
        if has_imports:
            anchor = conn.execute(
                """
                SELECT id,filename,period_end,closing_balance_cents,quality_status
                FROM imports
                WHERE account_id=?
                  AND status='completed'
                  AND closing_balance_cents IS NOT NULL
                  AND period_end IS NOT NULL
                  AND period_end<=?
                  AND quality_status='verified'
                ORDER BY period_end DESC,id DESC
                LIMIT 1
                """,
                (account['id'], balance_date.isoformat()),
            ).fetchone()

        if not anchor:
            unavailable_count += 1
            results.append({
                **base,
                'status': 'unavailable_no_verified_statement',
                'reason': 'Aucun relevé vérifié avec solde de clôture ne permet de reconstruire ce compte.',
                'anchor': None,
                'ledger_delta_cents': None,
                'expected_balance_cents': None,
                'difference_cents': None,
            })
            continue

        period_end = _parse_date(anchor['period_end'])
        if period_end is None:
            unavailable_count += 1
            results.append({
                **base,
                'status': 'unavailable_invalid_statement_period',
                'reason': 'La période du relevé de référence est invalide.',
                'anchor': dict(anchor),
                'ledger_delta_cents': None,
                'expected_balance_cents': None,
                'difference_cents': None,
            })
            continue

        delta = int(conn.execute(
            """
            SELECT COALESCE(SUM(amount_cents),0) total
            FROM transactions
            WHERE account_id=?
              AND booking_date>?
              AND booking_date<=?
              AND COALESCE(status,'confirmed')='confirmed'
            """,
            (account['id'], period_end.isoformat(), balance_date.isoformat()),
        ).fetchone()['total'])
        expected = int(anchor['closing_balance_cents']) + delta
        actual = int(account['current_balance_cents'] or 0)
        difference = actual - expected
        status = 'reconciled' if difference == 0 else 'mismatch'
        if status == 'reconciled':
            reconciled_count += 1
        else:
            mismatch_count += 1

        results.append({
            **base,
            'status': status,
            'reason': (
                'Solde courant cohérent avec le dernier relevé vérifié et le ledger.'
                if status == 'reconciled'
                else 'Le solde courant ne correspond pas au solde reconstruit depuis le relevé vérifié.'
            ),
            'anchor': {
                'import_id': int(anchor['id']),
                'filename': anchor['filename'],
                'period_end': anchor['period_end'],
                'closing_balance_cents': int(anchor['closing_balance_cents']),
                'quality_status': anchor['quality_status'],
            },
            'ledger_delta_cents': delta,
            'expected_balance_cents': expected,
            'difference_cents': difference,
        })

    overall = 'reconciled'
    if mismatch_count:
        overall = 'mismatch'
    elif unavailable_count:
        overall = 'incomplete'

    return {
        'status': overall,
        'account_count': len(accounts),
        'reconciled_count': reconciled_count,
        'mismatch_count': mismatch_count,
        'unavailable_count': unavailable_count,
        'accounts': results,
        'read_only': True,
        'formula': 'verified statement closing balance + confirmed ledger movements after period end = expected current balance',
    }
