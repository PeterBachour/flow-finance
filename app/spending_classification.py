from __future__ import annotations

VARIABLE_CATEGORIES = {
    'Alimentation',
    'Restaurants',
    'Shopping',
    'Loisirs',
    'Santé',
    'Transport',
}

FIXED_CATEGORIES = {
    'Logement',
    'Télécom',
    'Assurances',
    'Crédits',
    'Impôts',
    'Frais bancaires',
    'Services numériques',
}

NON_ROUTINE_CATEGORIES = {'Voyage', 'Dépense exceptionnelle'}
SAVINGS_CATEGORIES = {'Épargne', 'Investissement'}
EXCLUDED_CATEGORIES = {
    'Salaire',
    'Remboursement',
    'Transfert interne',
    'Frais professionnel remboursé',
}

FIXED_VARIABLE_CATEGORY_PATTERNS = {
    'Transport': ('NAVIGO', 'COMUTITRES', 'VELIB', 'VÉLIB'),
}


def normalize(value: str | None) -> str:
    return ' '.join((value or '').upper().split())


def accepted_recurring_labels(conn) -> set[str]:
    return {
        normalize(row['label'])
        for row in conn.execute(
            "SELECT label FROM recurring_transactions WHERE detection_status='accepted' AND amount_cents<0"
        ).fetchall()
        if row['label']
    }


def matches_validated_recurrence(label: str | None, recurring_labels: set[str]) -> bool:
    label_norm = normalize(label)
    if not label_norm:
        return False
    if label_norm in recurring_labels:
        return True
    return any(len(recurring) >= 5 and recurring in label_norm for recurring in recurring_labels)


def matches_fixed_variable_pattern(category: str, label: str | None) -> bool:
    label_norm = normalize(label)
    return any(pattern in label_norm for pattern in FIXED_VARIABLE_CATEGORY_PATTERNS.get(category, ()))


def classify_outflow(row, recurring_labels: set[str]) -> str:
    category = (row['category'] or '').strip()
    tx_type = normalize(row['transaction_type'])

    if category in SAVINGS_CATEGORIES or tx_type in {'SAVING', 'INVESTMENT'}:
        return 'savings'
    if int(row['is_internal_transfer'] or 0) == 1 or category == 'Transfert interne' or tx_type == 'TRANSFER':
        return 'internal'
    if matches_validated_recurrence(row['label'], recurring_labels):
        return 'fixed'
    if category in FIXED_CATEGORIES:
        return 'fixed'
    if category in NON_ROUTINE_CATEGORIES:
        return 'non_routine'
    if category in VARIABLE_CATEGORIES:
        if matches_fixed_variable_pattern(category, row['label']):
            return 'fixed'
        return 'variable'
    if category in EXCLUDED_CATEGORIES or tx_type in {'INCOME', 'REFUND'}:
        return 'excluded'
    if not category:
        return 'unknown'
    return 'other_classified'
