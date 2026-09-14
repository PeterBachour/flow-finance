from __future__ import annotations

from datetime import date, timedelta

from .v5_planning import build_v5_plan


def _parse_date(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _event_status(*, amount_cents: int, balance_after_cents: int, protected_cents: int) -> str:
    if amount_cents >= 0:
        return 'income'
    if balance_after_cents < 0:
        return 'critical'
    if balance_after_cents < protected_cents:
        return 'high'
    buffer_cents = balance_after_cents - protected_cents
    if protected_cents > 0 and buffer_cents < round(protected_cents * 0.25):
        return 'watch'
    return 'safe'


def build_upcoming_events(conn, *, as_of: date, days: int = 45) -> dict:
    """Return a chronological read-only agenda derived from the canonical forecast.

    No transaction, commitment or synthetic bank movement is created here. The
    function only normalizes events already produced by the validated forecast.
    """
    days = max(7, min(120, int(days)))
    horizon_end = as_of + timedelta(days=days)
    months = max(1, min(12, ((horizon_end.year - as_of.year) * 12 + horizon_end.month - as_of.month) + 1))
    plan = build_v5_plan(conn, months=months, today=as_of)
    projection = plan.get('projection') or {}
    protected = int(projection.get('protected_cents') or 0)

    items: list[dict] = []
    for month in projection.get('months') or []:
        for raw in month.get('events') or []:
            event_date = _parse_date(raw.get('date'))
            if event_date is None or event_date < as_of or event_date > horizon_end:
                continue
            amount = int(raw.get('amount_cents') or 0)
            balance_after = int(raw.get('balance_after_cents') or 0)
            status = _event_status(
                amount_cents=amount,
                balance_after_cents=balance_after,
                protected_cents=protected,
            )
            items.append({
                'date': event_date.isoformat(),
                'days_away': (event_date - as_of).days,
                'label': raw.get('label') or 'Événement financier',
                'amount_cents': amount,
                'direction': 'income' if amount >= 0 else 'outflow',
                'balance_after_cents': balance_after,
                'protected_cents': protected,
                'distance_to_protection_cents': balance_after - protected,
                'status': status,
                'source': raw.get('source'),
                'event_type': raw.get('event_type') or raw.get('type'),
            })

    items.sort(key=lambda row: (row['date'], 0 if row['direction'] == 'outflow' else 1, row['label']))
    outflows = [item for item in items if item['direction'] == 'outflow']
    incomes = [item for item in items if item['direction'] == 'income']
    sensitive = [item for item in outflows if item['status'] in {'watch', 'high', 'critical'}]

    return {
        'schema_version': '5.1-rc',
        'as_of': as_of.isoformat(),
        'horizon_end': horizon_end.isoformat(),
        'days': days,
        'protected_cents': protected,
        'summary': {
            'event_count': len(items),
            'outflow_count': len(outflows),
            'income_count': len(incomes),
            'sensitive_count': len(sensitive),
            'total_outflows_cents': sum(abs(int(item['amount_cents'])) for item in outflows),
            'total_inflows_cents': sum(int(item['amount_cents']) for item in incomes),
            'next_outflow': outflows[0] if outflows else None,
            'next_income': incomes[0] if incomes else None,
        },
        'events': items,
        'principle': 'Agenda financier en lecture seule dérivé du forecast canonique. Aucun mouvement bancaire n’est inventé ou enregistré.',
    }
