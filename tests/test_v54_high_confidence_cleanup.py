from app.imports import infer_transaction_type
from maintenance.classify_high_confidence_imports import suggested_rule


def test_high_confidence_rules_cover_clear_merchants():
    assert suggested_rule('CB HELLOFRESH FRANC') == (
        'CB HELLOFRESH', 'Alimentation', None
    )
    assert suggested_rule('CB DAMES MAGIC 1') == (
        'CB DAMES MAGIC 1', 'Restaurants', None
    )
    assert suggested_rule('CB TRANSAVIA') == (
        'CB TRANSAVIA', 'Transport', None
    )


def test_person_transfers_and_ambiguous_merchants_remain_unclassified():
    for label in (
        'VIR INST MLE MAYOT LUCILLE',
        'VIR INST MME MICHELE NAHAS',
        'CB SEIC BEAUMARCHAI',
        'CB FBG ST ANTOINE',
        'CB LYDIA*LYDIA SOLU',
        'TOTAL INCIDENTS FONCTIONNEMENT',
    ):
        assert suggested_rule(label) is None


def test_positive_card_rule_is_a_refund_and_negative_card_rule_is_an_expense():
    assert infer_transaction_type('CB SNCF-VOYAGEURS', 5275) == 'refund'
    assert infer_transaction_type('CB SNCF-VOYAGEURS', -5275) == 'expense'


def test_health_reimbursements_keep_refund_semantics():
    assert suggested_rule('VIREMENT CPAM 75 PRESTATIONS') == (
        'VIREMENT CPAM 75 PRESTATIONS', 'Remboursement', 'refund'
    )
