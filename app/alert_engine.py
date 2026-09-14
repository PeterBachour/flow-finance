from datetime import date, timedelta


def _alert(code: str, severity: str, title: str, message: str, action: str | None = None) -> dict:
    return {'code': code, 'severity': severity, 'title': title, 'message': message, 'action': action}


def build_actionable_alerts(*, dashboard: dict, month_prep: dict, today: date, snapshot_max_age_days: int = 3, upcoming_window_days: int = 7) -> list[dict]:
    alerts: list[dict] = []
    forecast = dashboard.get('projections', {}).get('realistic') or dashboard.get('forecast') or {}
    low = forecast.get('low_point') or {}
    low_balance = int(low.get('balance_cents') or 0)
    safe = int(forecast.get('safe_to_spend_cents') or 0)
    reserve = int(forecast.get('safety_reserve_cents') or 0)
    allocated = int(forecast.get('allocated_cents') or dashboard.get('allocated_cents') or 0)

    if low_balance < 0:
        alerts.append(_alert(
            'negative-low-point', 'critical', 'Découvert prévisionnel',
            f"La projection réaliste atteint {low_balance / 100:.2f} € le {low.get('date', '—')}.",
            'Réduire ou décaler une sortie avant cette date.',
        ))
    elif safe <= 0 and (reserve > 0 or allocated > 0):
        alerts.append(_alert(
            'safe-exhausted', 'warning', 'Disponible sans risque épuisé',
            'La trésorerie projetée reste positive, mais elle est entièrement absorbée par la réserve et les allocations.',
            'Éviter une nouvelle dépense non prévue ou revoir une allocation.',
        ))

    for account in dashboard.get('accounts', []):
        if account.get('kind') not in {'checking', 'cash'}:
            continue
        as_of = account.get('balance_as_of')
        if not as_of:
            alerts.append(_alert(
                f"snapshot-missing-{account.get('id')}", 'warning', 'Solde réel non daté',
                f"Le solde de {account.get('name', 'ce compte')} n'a pas de date d'observation.",
                'Mettre à jour le solde réel dans Patrimoine.',
            ))
            continue
        try:
            observed = date.fromisoformat(as_of)
        except ValueError:
            continue
        age = (today - observed).days
        if age > snapshot_max_age_days:
            alerts.append(_alert(
                f"snapshot-stale-{account.get('id')}", 'warning', 'Solde réel à actualiser',
                f"Le solde de {account.get('name', 'ce compte')} date de {age} jours (seuil {snapshot_max_age_days} j).",
                'Actualiser le solde avant de prendre une décision de dépense.',
            ))

    horizon = today + timedelta(days=upcoming_window_days)
    upcoming = []
    for event in forecast.get('events', []):
        try:
            due = date.fromisoformat(event['date'])
        except (KeyError, TypeError, ValueError):
            continue
        amount = int(event.get('amount_cents') or 0)
        if today <= due <= horizon and amount < 0:
            upcoming.append((due, -amount, event.get('label') or 'Charge'))
    if upcoming:
        due_total = sum(amount for _, amount, _ in upcoming)
        if safe > 0 and due_total > safe:
            alerts.append(_alert(
                'upcoming-over-safe', 'warning', 'Charges imminentes supérieures au disponible',
                f"{due_total / 100:.2f} € de sorties sont prévues sous {upcoming_window_days} jours pour {safe / 100:.2f} € de disponible sans risque.",
                'Vérifier les prochaines échéances avant toute nouvelle dépense.',
            ))

    if month_prep.get('status') == 'attention':
        reasons = month_prep.get('blockers') or []
        alerts.append(_alert(
            'next-month-unprepared', 'warning', 'Mois suivant à préparer',
            ' · '.join(reasons) if reasons else 'Des éléments structurants manquent pour préparer le mois suivant.',
            'Ouvrir Mois et compléter les éléments manquants.',
        ))
    elif month_prep.get('status') == 'review':
        warnings = month_prep.get('warnings') or []
        alerts.append(_alert(
            'next-month-review', 'info', 'Mois suivant à vérifier',
            ' · '.join(warnings) if warnings else 'Le mois suivant est presque prêt mais nécessite une vérification.',
            'Ouvrir Mois pour finaliser la préparation.',
        ))

    severity_order = {'critical': 0, 'warning': 1, 'info': 2}
    alerts.sort(key=lambda item: (severity_order.get(item['severity'], 9), item['code']))
    return alerts
