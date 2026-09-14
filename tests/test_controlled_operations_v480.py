from pathlib import Path

from app.v48_routes import BulkCategoryIn, _bulk_where, _rule_key, _suggestion_key


def test_bulk_where_defaults_to_uncategorized_non_transfer_rows():
    payload = BulkCategoryIn(pattern='monoprix', category='Alimentation')
    where, params = _bulk_where(payload)
    assert "UPPER(COALESCE(t.user_label,t.label)) LIKE ?" in where
    assert "COALESCE(t.is_internal_transfer,0)=0" in where
    assert "COALESCE(t.category,'')=''" in where
    assert params == ['%MONOPRIX%']


def test_bulk_where_can_scope_an_account_without_overwriting_categories():
    payload = BulkCategoryIn(pattern='uber', category='Transport', account_id=3, only_uncategorized=False)
    where, params = _bulk_where(payload)
    assert 't.account_id=?' in where
    assert "COALESCE(t.category,'')=''" not in where
    assert params == ['%UBER%', 3]


def test_bulk_and_recurring_keys_are_deterministic():
    assert _rule_key(' Monoprix ') == _rule_key('MONOPRIX')
    suggestion = {'account_id': 1, 'key': 'NETFLIX', 'label': 'Netflix', 'amount_cents': -1399}
    assert _suggestion_key(suggestion) == _suggestion_key(dict(suggestion))
    assert _suggestion_key(suggestion).startswith('recurring:')


def test_v48_ui_requires_preview_before_apply_and_explicit_recurring_decision():
    js = Path('app/static/v48-operations-ui.js').read_text(encoding='utf-8')
    assert '/api/v4.8/bulk-category/preview' in js
    assert '/api/v4.8/bulk-category/apply' in js
    assert 'Confirmer et appliquer' in js
    assert '/api/v4.8/recurring-review/decision' in js
    assert 'Accepter' in js and 'Rejeter' in js
