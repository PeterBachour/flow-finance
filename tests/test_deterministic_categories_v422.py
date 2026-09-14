from maintenance.audit_repeated_merchant_classification import classify_merchant
from maintenance.apply_deterministic_categories_v422 import RULES


def test_tax_and_tcl_are_deterministic():
    tier, category, confidence, _ = classify_merchant('PRLV SEPA DIRECTION GENERALE DES FINANCES PUBLIQUE')
    assert tier == 'auto_classifiable'
    assert category == 'Impôts'
    assert confidence >= 0.99

    tier, category, confidence, _ = classify_merchant('CB TCL 69 LYO 18/04/26')
    assert tier == 'auto_classifiable'
    assert category == 'Transport'
    assert confidence >= 0.99


def test_expanded_apply_rules_stay_in_auto_classifiable_tier():
    for pattern, category, _ in RULES:
        tier, proposed, confidence, _ = classify_merchant(pattern)
        assert tier == 'auto_classifiable'
        assert proposed == category
        assert confidence >= 0.92


def test_ambiguous_merchants_are_not_auto_classified():
    for merchant in ('LGA', 'BOURSORAMA', 'LE POPUP', 'VIR INST EMMANUEL DAVID B'):
        tier, _, _, _ = classify_merchant(merchant)
        assert tier != 'auto_classifiable'


def test_apply_rules_only_use_operational_flow_categories():
    operational = {'Impôts', 'Transport', 'Restaurants', 'Shopping'}
    assert {category for _, category, _ in RULES} <= operational


def test_apply_rules_exclude_broad_or_context_sensitive_merchants():
    patterns = {pattern for pattern, _, _ in RULES}
    for excluded in ('APPLE.COM/BILL', 'AMAZON PAYMENTS', 'FNAC', 'HOTEL', 'AIRBNB', 'SIXT'):
        assert excluded not in patterns
